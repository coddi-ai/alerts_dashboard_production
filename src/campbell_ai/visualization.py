"""Validated Plotly chart generation over dashboard-owned datasets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import CampbellDataError
from src.campbell_ai.models import VisualizationArtifact


@dataclass(frozen=True)
class _ChartSource:
    dataset: str
    label: str
    date_columns: tuple[str, ...]
    unit_columns: tuple[str, ...]
    dimensions: dict[str, tuple[str, ...]]
    metrics: dict[str, tuple[str, ...]]


CHART_SOURCES: dict[str, _ChartSource] = {
    "alerts": _ChartSource(
        "alerts",
        "Alertas",
        ("Timestamp", "Fecha", "event_ts"),
        ("UnitId", "Unit", "unit_id"),
        {
            "unit": ("UnitId", "Unit", "unit_id"),
            "system": ("sistema", "System", "system"),
            "subsystem": ("subsistema", "Subsystem", "subsystem"),
            "component": ("componente", "Component", "component"),
            "trigger": ("Trigger_type", "Trigger", "trigger_type"),
        },
        {},
    ),
    "maintenance_actions": _ChartSource(
        "maintenance_actions",
        "Acciones de mantenimiento",
        ("change_date", "event_ts", "Timestamp"),
        ("machine_code", "machine_id", "UnitId"),
        {
            "unit": ("machine_code", "machine_id", "UnitId"),
            "system": ("action_system_name", "job_system_name"),
            "component": ("component_names", "componentName"),
            "action_type": ("action_type_name", "action_type"),
        },
        {},
    ),
    "oil_machine_status": _ChartSource(
        "oil_machine_status",
        "Estado por aceite",
        ("latest_sample_date", "sampleDate", "reportDate"),
        ("unit_id", "unitId", "UnitId"),
        {
            "unit": ("unit_id", "unitId", "UnitId"),
            "status": ("overall_status", "report_status"),
        },
        {
            "priority_score": ("priority_score",),
            "machine_score": ("machine_score",),
            "components_alerta": ("components_alerta",),
            "components_anormal": ("components_anormal",),
        },
    ),
    "telemetry_machine_status": _ChartSource(
        "telemetry_machine_status",
        "Estado por telemetría",
        (),
        ("unit_id", "unitId", "UnitId"),
        {
            "unit": ("unit_id", "unitId", "UnitId"),
            "status": ("overall_status", "component_status"),
            "evaluation_week": ("evaluation_week",),
        },
        {
            "priority_score": ("priority_score",),
            "machine_score": ("machine_score",),
            "components_alerta": ("components_alerta",),
            "components_anormal": ("components_anormal",),
        },
    ),
}

CHART_TYPES = {"bar", "line", "pie", "pareto", "heatmap", "stacked_bar"}
AGGREGATIONS = {"count", "sum", "mean", "max", "min"}
TIME_DIMENSIONS = {"day", "week", "month"}
COLORS = ["#10a37f", "#2563eb", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2"]


class DashboardVisualizationService:
    """Build figures from an allowlist of data, dimensions, metrics and operations."""

    def __init__(self, repository: DashboardDataRepository):
        self.repository = repository

    @staticmethod
    def _column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
        return DashboardDataRepository._resolve_column(frame, candidates)

    @staticmethod
    def _clean_category(series: pd.Series) -> pd.Series:
        return (
            series.fillna("Sin información")
            .astype(str)
            .str.strip()
            .replace("", "Sin información")
        )

    def _dimension_series(
        self,
        frame: pd.DataFrame,
        dates: pd.Series | None,
        source: _ChartSource,
        dimension: str,
    ) -> tuple[pd.Series, str]:
        if dimension in TIME_DIMENSIONS:
            if dates is None:
                raise CampbellDataError("La fuente no contiene una fecha utilizable")
            frequency = {"day": "D", "week": "W", "month": "M"}[dimension]
            periods = dates.dt.to_period(frequency)
            labels = periods.map(
                lambda value: str(value.start_time.date()) if pd.notna(value) else "Sin fecha"
            )
            names = {"day": "Día", "week": "Semana", "month": "Mes"}
            return labels, names[dimension]
        candidates = source.dimensions.get(dimension)
        if candidates is None:
            raise CampbellDataError("Dimensión no disponible para esta fuente")
        column = self._column(frame, candidates)
        if not column:
            raise CampbellDataError("La dimensión solicitada no existe en la fuente")
        return self._clean_category(frame[column]), dimension.replace("_", " ").title()

    def _metric_series(
        self,
        frame: pd.DataFrame,
        source: _ChartSource,
        metric: str,
    ) -> pd.Series | None:
        if metric == "count":
            return None
        candidates = source.metrics.get(metric)
        if candidates is None:
            raise CampbellDataError("Métrica no disponible para esta fuente")
        column = self._column(frame, candidates)
        if not column:
            raise CampbellDataError("La métrica solicitada no existe en la fuente")
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().sum() == 0:
            raise CampbellDataError("La métrica solicitada no contiene valores numéricos")
        return values

    @staticmethod
    def _aggregate(
        frame: pd.DataFrame,
        group_columns: list[str],
        metric_column: str | None,
        aggregation: str,
    ) -> pd.Series:
        if metric_column is None:
            return frame.groupby(group_columns, dropna=False).size()
        return frame.groupby(group_columns, dropna=False)[metric_column].agg(aggregation)

    def create_chart(
        self,
        client: str,
        dataset: str,
        chart_type: str,
        dimension: str,
        secondary_dimension: str = "",
        metric: str = "count",
        aggregation: str = "count",
        days: int = 60,
        start_date: str = "",
        end_date: str = "",
        unit_id: str = "",
        filter_dimension: str = "",
        filter_value: str = "",
        top_n: int = 10,
        title: str = "",
    ) -> VisualizationArtifact:
        source = CHART_SOURCES.get(str(dataset).strip().lower())
        if source is None:
            raise CampbellDataError("Fuente no permitida para visualización")

        kind = str(chart_type).strip().lower()
        if kind not in CHART_TYPES:
            raise CampbellDataError("Tipo de gráfico no permitido")
        primary = str(dimension).strip().lower()
        secondary = str(secondary_dimension).strip().lower()
        resolved_metric = str(metric or "count").strip().lower()
        resolved_aggregation = str(aggregation or "count").strip().lower()
        if resolved_aggregation not in AGGREGATIONS:
            raise CampbellDataError("Agregación no permitida")
        if resolved_metric == "count":
            resolved_aggregation = "count"
        elif resolved_aggregation == "count":
            raise CampbellDataError("Una métrica numérica requiere sum, mean, max o min")
        if kind == "line" and primary not in TIME_DIMENSIONS:
            raise CampbellDataError("El gráfico lineal requiere day, week o month")
        if kind in {"heatmap", "stacked_bar"} and not secondary:
            raise CampbellDataError("Este gráfico requiere secondary_dimension")
        if kind not in {"heatmap", "stacked_bar"} and secondary:
            raise CampbellDataError("secondary_dimension solo aplica a heatmap o stacked_bar")

        frame = self.repository.load(source.dataset, client).copy()
        date_col = self._column(frame, source.date_columns) if source.date_columns else None
        frame, dates, window = self.repository.filter_date_window(
            frame,
            date_col,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        unit_col = self._column(frame, source.unit_columns)
        if unit_id:
            if not unit_col:
                raise CampbellDataError("La fuente no permite filtrar por unidad")
            frame = frame[
                frame[unit_col].astype(str).str.casefold() == str(unit_id).casefold()
            ].copy()
            if dates is not None:
                dates = dates.loc[frame.index]

        if filter_dimension or filter_value:
            if not filter_dimension or not filter_value:
                raise CampbellDataError("El filtro requiere dimensión y valor")
            filter_key = str(filter_dimension).strip().lower()
            if filter_key in TIME_DIMENSIONS:
                raise CampbellDataError("Use start_date y end_date para filtros temporales")
            candidates = source.dimensions.get(filter_key)
            if candidates is None:
                raise CampbellDataError("Dimensión de filtro no permitida")
            filter_col = self._column(frame, candidates)
            if not filter_col:
                raise CampbellDataError("La dimensión de filtro no existe en la fuente")
            frame = frame[
                frame[filter_col]
                .astype(str)
                .str.contains(str(filter_value), case=False, na=False)
            ].copy()
            if dates is not None:
                dates = dates.loc[frame.index]
        if frame.empty:
            raise CampbellDataError("No hay datos para construir el gráfico solicitado")

        frame["__primary"] = self._dimension_series(frame, dates, source, primary)[0]
        primary_label = self._dimension_series(frame, dates, source, primary)[1]
        if secondary:
            frame["__secondary"] = self._dimension_series(
                frame, dates, source, secondary
            )[0]
            secondary_label = self._dimension_series(
                frame, dates, source, secondary
            )[1]
        else:
            secondary_label = ""
        metric_values = self._metric_series(frame, source, resolved_metric)
        metric_column = None
        if metric_values is not None:
            frame["__metric"] = metric_values
            metric_column = "__metric"
            frame = frame[frame["__metric"].notna()].copy()
        if frame.empty:
            raise CampbellDataError("No hay valores válidos para la métrica solicitada")

        limit = max(1, min(int(top_n), 30))
        value_label = (
            "Cantidad"
            if resolved_metric == "count"
            else f"{resolved_aggregation.title()} de {resolved_metric.replace('_', ' ')}"
        )
        figure = go.Figure()
        top_summary: dict[str, float | int] = {}

        if kind in {"heatmap", "stacked_bar"}:
            top_primary = frame["__primary"].value_counts().head(limit).index
            top_secondary = frame["__secondary"].value_counts().head(limit).index
            matrix_frame = frame[
                frame["__primary"].isin(top_primary)
                & frame["__secondary"].isin(top_secondary)
            ]
            grouped = self._aggregate(
                matrix_frame,
                ["__primary", "__secondary"],
                metric_column,
                resolved_aggregation,
            )
            matrix = grouped.unstack(fill_value=0)
            matrix = matrix.reindex(index=list(top_primary), columns=list(top_secondary), fill_value=0)
            if kind == "heatmap":
                figure.add_trace(
                    go.Heatmap(
                        x=[str(value) for value in matrix.columns],
                        y=[str(value) for value in matrix.index],
                        z=matrix.astype(float).values.tolist(),
                        colorscale="Viridis",
                        colorbar={"title": value_label},
                        hovertemplate=(
                            f"{primary_label}: %{{y}}<br>{secondary_label}: %{{x}}"
                            f"<br>{value_label}: %{{z}}<extra></extra>"
                        ),
                    )
                )
            else:
                for index, category in enumerate(matrix.columns):
                    figure.add_trace(
                        go.Bar(
                            name=str(category),
                            x=[str(value) for value in matrix.index],
                            y=[float(value) for value in matrix[category].values],
                            marker={"color": COLORS[index % len(COLORS)]},
                        )
                    )
                figure.update_layout(barmode="stack")
            top_summary = {
                str(index): float(value)
                for index, value in grouped.sort_values(ascending=False).head(5).items()
            }
            categories = int(matrix.shape[0] * matrix.shape[1])
            aggregated_total = float(grouped.sum())
        else:
            grouped = self._aggregate(
                frame,
                ["__primary"],
                metric_column,
                resolved_aggregation,
            )
            if primary in TIME_DIMENSIONS:
                grouped = grouped.sort_index()
            else:
                grouped = grouped.sort_values(ascending=False)
                if kind == "pareto" and len(grouped) > limit:
                    retained = grouped.head(max(1, limit - 1))
                    grouped = pd.concat(
                        [
                            retained,
                            pd.Series(
                                {"Otros": grouped.iloc[len(retained) :].sum()},
                                dtype=float,
                            ),
                        ]
                    )
                else:
                    grouped = grouped.head(limit)
            labels = [str(value) for value in grouped.index]
            values = [float(value) for value in grouped.values]
            if kind == "line":
                figure.add_trace(
                    go.Scatter(
                        x=labels,
                        y=values,
                        mode="lines+markers",
                        name=value_label,
                        line={"color": COLORS[0], "width": 3},
                    )
                )
            elif kind == "pie":
                figure.add_trace(go.Pie(labels=labels, values=values, hole=0.42))
            elif kind == "pareto":
                total = sum(values)
                cumulative: list[float] = []
                running = 0.0
                for value in values:
                    running += value
                    cumulative.append((running / total * 100) if total else 0.0)
                figure.add_trace(
                    go.Bar(
                        x=labels,
                        y=values,
                        name=value_label,
                        marker={"color": COLORS[0]},
                    )
                )
                figure.add_trace(
                    go.Scatter(
                        x=labels,
                        y=cumulative,
                        name="% acumulado",
                        mode="lines+markers",
                        yaxis="y2",
                        line={"color": "#dc2626", "width": 3},
                    )
                )
                figure.update_layout(
                    yaxis2={
                        "title": "% acumulado",
                        "overlaying": "y",
                        "side": "right",
                        "range": [0, 105],
                        "ticksuffix": "%",
                    }
                )
            else:
                figure.add_trace(
                    go.Bar(x=labels, y=values, marker={"color": COLORS[0]}, name=value_label)
                )
            top_summary = {
                label: int(value) if float(value).is_integer() else round(value, 3)
                for label, value in zip(labels[:5], values[:5])
            }
            categories = len(labels)
            aggregated_total = float(sum(values))

        resolved_title = str(title or "").strip()[:140]
        if not resolved_title:
            if kind == "pareto":
                resolved_title = f"Pareto de {source.label.lower()} por {primary_label.lower()}"
            elif kind == "heatmap":
                resolved_title = (
                    f"Mapa de calor de {source.label.lower()}: "
                    f"{primary_label.lower()} × {secondary_label.lower()}"
                )
            else:
                resolved_title = f"{source.label} por {primary_label.lower()}"
        if unit_id:
            resolved_title += f" · {unit_id}"

        figure.update_layout(
            title=resolved_title,
            template="plotly_white",
            margin={"l": 55, "r": 55, "t": 65, "b": 80},
            height=440 if kind == "heatmap" else 410,
            showlegend=kind in {"pie", "pareto", "stacked_bar"},
            hovermode="closest",
        )
        if kind not in {"pie", "heatmap"}:
            figure.update_xaxes(title=primary_label, automargin=True)
            figure.update_yaxes(title=value_label, rangemode="tozero", automargin=True)
        elif kind == "heatmap":
            figure.update_xaxes(title=secondary_label, automargin=True)
            figure.update_yaxes(title=primary_label, automargin=True)

        summary: dict[str, Any] = {
            "records_analyzed": int(len(frame)),
            "aggregated_total": (
                int(aggregated_total)
                if float(aggregated_total).is_integer()
                else round(aggregated_total, 3)
            ),
            "categories": categories,
            "top": top_summary,
            "window": window,
            "unit_id": unit_id or None,
            "dimension": primary,
            "secondary_dimension": secondary or None,
            "metric": resolved_metric,
            "aggregation": resolved_aggregation,
        }
        return VisualizationArtifact(
            title=resolved_title,
            description=(
                f"{source.label}: {summary['records_analyzed']} registros analizados; "
                f"gráfico {kind} con métrica {resolved_metric}."
            ),
            dataset=source.dataset,
            chart_type=kind,
            figure=json.loads(figure.to_json()),
            summary=summary,
        )
