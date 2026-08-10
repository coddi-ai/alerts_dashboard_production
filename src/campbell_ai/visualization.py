"""Validated Plotly chart generation over dashboard-owned datasets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.campbell_ai.data import DashboardDataRepository
from src.charts import CHART_KINDS
from src.charts.builders import (
    build_area,
    build_box,
    build_category_bar,
    build_heatmap,
    build_histogram,
    build_pareto,
    build_pie,
    build_scatter,
    build_stacked_bar,
    build_time_series,
    build_treemap,
)
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
    # Keep only the newest row per group so a chart shows current condition instead of
    # stacking every historical evaluation, matching what the query tools report.
    latest_by: tuple[tuple[str, ...], ...] = ()
    latest_order: tuple[tuple[str, ...], ...] = ()


# Tribology essay/element columns from oil_classified, exposed as chart-able
# metrics so a historical oil trend (not just the latest-sample snapshot every
# other oil chart shows) can be plotted the same way telemetry/alert metrics are:
# create_dashboard_chart(dataset="oil_components", chart_type="line",
# dimension="day", metric="hierro", unit_id=...). Keys are lowercase because
# create_chart() lowercases the requested metric before this lookup; values are
# the real (accented, capitalized) column name to resolve against the frame.
_OIL_ESSAY_METRICS: dict[str, tuple[str, ...]] = {
    name.lower(): (name,)
    for name in (
        "Hierro", "Cromo", "Aluminio", "Cobre", "Plomo", "Níquel", "Plata",
        "Estaño", "Titanio", "Vanadio", "Manganeso", "Silicio", "Potasio",
        "Sodio", "Zinc", "Bario", "Boro", "Calcio", "Molibdeno", "Magnesio",
        "Fósforo", "Índice PQ", "Oxidación", "Hollín", "Viscocidad", "Agua",
        "Refrigerante", "Combustible",
    )
}

CHART_SOURCES: dict[str, _ChartSource] = {
    "alerts": _ChartSource(
        "alerts",
        "Alertas",
        ("Timestamp", "Fecha", "event_ts"),
        ("UnitId", "Unit", "unit_id"),
        {
            "unit": ("UnitId", "Unit", "unit_id"),
            "system": ("sistema", "System", "system"),
            "subsystem": ("subsistema", "SubSystem", "Subsystem"),
            "component": ("componente", "Component", "component"),
            "trigger": ("Trigger_type", "Trigger", "trigger_type"),
            "trigger_var": ("Trigger_Var", "trigger_var"),
            "source_type": ("SourceType", "source_type"),
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
        "Condición de aceite",
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
        "Condición de telemetría",
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
        latest_by=(("unit_id", "unitId", "UnitId"),),
        latest_order=(("evaluation_year",), ("evaluation_week",)),
    ),
    "telemetry_components": _ChartSource(
        "telemetry_classified",
        "Componentes de telemetría",
        (),
        ("unit_id", "unitId", "UnitId"),
        {
            "unit": ("unit_id", "unitId", "UnitId"),
            "component": ("component", "componentName"),
            "status": ("component_status", "overall_status"),
            "criticality": ("criticality",),
            "evaluation_week": ("evaluation_week",),
        },
        {
            "component_score": ("component_score",),
            "signal_coverage": ("signal_coverage",),
        },
        latest_by=(("unit_id", "unitId", "UnitId"), ("component", "componentName")),
        latest_order=(("evaluation_year",), ("evaluation_week",)),
    ),
    "oil_components": _ChartSource(
        "oil_classified",
        "Componentes de aceite",
        ("sampleDate", "reportDate"),
        ("unitId", "unit_id", "UnitId"),
        {
            "unit": ("unitId", "unit_id", "UnitId"),
            "component": ("componentNameNormalized", "componentName"),
            "status": ("report_status", "overall_status"),
            "anomaly_type": ("anomalyType",),
        },
        {
            "severity_score": ("severity_score",),
            "classification_score": ("classification_score",),
            **_OIL_ESSAY_METRICS,
        },
    ),
    "maintenance_summary": _ChartSource(
        "maintenance_summary",
        "Resumen semanal de mantenimiento",
        (),
        ("UnitId", "machine_code", "machine_id"),
        {"unit": ("UnitId", "machine_code", "machine_id")},
        {},
    ),
}

CHART_TYPES = set(CHART_KINDS)
AGGREGATIONS = {"count", "sum", "mean", "max", "min"}
TIME_DIMENSIONS = {"day", "week", "month"}

# Charts that read one value per row rather than an aggregate per category.
ROW_LEVEL_TYPES = {"histogram", "box", "scatter"}
# Charts that need a second dimension to have any meaning.
PAIRED_TYPES = {"heatmap", "stacked_bar"}


def secondary_metric_requested(secondary: str) -> bool:
    """A scatter reuses `secondary_dimension` to name its second metric."""
    return bool(str(secondary or "").strip())

# Spanish axis and legend labels; the raw dimension keys are English internals.
DIMENSION_LABELS: dict[str, str] = {
    "unit": "Equipo",
    "system": "Sistema",
    "subsystem": "Subsistema",
    "component": "Componente",
    "trigger": "Tipo de disparador",
    "trigger_var": "Variable disparadora",
    "source_type": "Fuente",
    "action_type": "Tipo de acción",
    "status": "Estado",
    "criticality": "Criticidad",
    "anomaly_type": "Tipo de anomalía",
    "evaluation_week": "Semana de evaluación",
    "day": "Día",
    "week": "Semana",
    "month": "Mes",
}

METRIC_LABELS: dict[str, str] = {
    "count": "Cantidad",
    "priority_score": "puntaje de prioridad",
    "machine_score": "puntaje del equipo",
    "components_alerta": "componentes en alerta",
    "components_anormal": "componentes anormales",
    "component_score": "puntaje del componente",
    "signal_coverage": "cobertura de señal",
    "severity_score": "puntaje de severidad",
    "classification_score": "puntaje de clasificación",
}

AGGREGATION_LABELS: dict[str, str] = {
    "sum": "Suma",
    "mean": "Promedio",
    "max": "Máximo",
    "min": "Mínimo",
}


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
            DashboardDataRepository._categorical(series)
            .fillna("Sin información")
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
            return labels, DIMENSION_LABELS[dimension]
        candidates = source.dimensions.get(dimension)
        if candidates is None:
            raise CampbellDataError(
                f"Dimensión '{dimension}' no disponible para esta fuente. "
                f"Disponibles: {', '.join(sorted(source.dimensions))}"
            )
        column = self._column(frame, candidates)
        if not column:
            raise CampbellDataError("La dimensión solicitada no existe en la fuente")
        label = DIMENSION_LABELS.get(dimension, dimension.replace("_", " ").capitalize())
        series = self._clean_category(frame[column])
        if dimension == "trigger_var":
            # Category values here are raw signal codes (EngCoolTemp, AirFltr...);
            # translate each so axis ticks and legend entries read in Spanish
            # instead of the technical column name.
            series = series.map(
                lambda value: DashboardDataRepository._translate_signal_list(value)
                or value
            )
        return series, label

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

    def _keep_latest(self, frame: pd.DataFrame, source: _ChartSource) -> pd.DataFrame:
        """Reduce a periodically re-evaluated source to its most recent row per group."""
        if not source.latest_by:
            return frame
        group_columns = [
            column
            for column in (self._column(frame, candidates) for candidates in source.latest_by)
            if column
        ]
        order_columns = [
            column
            for column in (self._column(frame, candidates) for candidates in source.latest_order)
            if column
        ]
        if not group_columns or not order_columns:
            return frame
        ranked = frame.copy()
        for column in order_columns:
            ranked[column] = pd.to_numeric(ranked[column], errors="coerce")
        return (
            ranked.sort_values(order_columns, ascending=True)
            .groupby(group_columns, dropna=False)
            .tail(1)
            .copy()
        )

    @staticmethod
    def _metric_label(metric: str) -> str:
        key = str(metric or "").strip().lower()
        return METRIC_LABELS.get(key, key.replace("_", " ")).capitalize()

    def _build_row_level(
        self,
        *,
        frame: pd.DataFrame,
        source: _ChartSource,
        kind: str,
        primary: str,
        primary_label: str,
        secondary_label: str,
        value_label: str,
        resolved_title: str,
        subtitle: str,
        unit_id: str,
        limit: int,
    ):
        """Build a chart that plots raw rows: histogram, box or scatter.

        These read one value per record instead of an aggregate per category, so they
        answer "how is this spread" rather than "which category is largest".
        """
        values = pd.to_numeric(frame["__metric"], errors="coerce").dropna()
        if values.empty:
            raise CampbellDataError("La métrica solicitada no contiene valores numéricos")

        if not resolved_title:
            resolved_title = self._default_title(
                source, kind, primary, primary_label, secondary_label, value_label
            )
        if unit_id:
            resolved_title += f" · {unit_id}"

        if kind == "histogram":
            figure = build_histogram(
                [float(value) for value in values],
                title=resolved_title,
                value_label=value_label,
                bins=max(5, min(limit * 2, 40)),
                subtitle=subtitle,
            )
            summary = {
                "min": round(float(values.min()), 3),
                "max": round(float(values.max()), 3),
                "mean": round(float(values.mean()), 3),
                "median": round(float(values.median()), 3),
            }
            return figure, summary, int(values.nunique()), float(values.sum()), resolved_title

        if kind == "box":
            grouped: dict[str, list[float]] = {}
            for label, chunk in frame.groupby("__primary", dropna=False):
                numeric = pd.to_numeric(chunk["__metric"], errors="coerce").dropna()
                if not numeric.empty:
                    grouped[str(label)] = [float(value) for value in numeric]
            # Keep the categories with the most observations so the plot stays readable.
            ordered = dict(
                sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)[:limit]
            )
            if not ordered:
                raise CampbellDataError("No hay valores para comparar distribuciones")
            figure = build_box(
                ordered,
                title=resolved_title,
                dimension_label=primary_label,
                value_label=value_label,
                subtitle=subtitle,
            )
            summary = {
                label: round(float(pd.Series(items).median()), 3)
                for label, items in list(ordered.items())[:5]
            }
            return figure, summary, len(ordered), float(values.sum()), resolved_title

        # scatter: one point per row, labelled by the primary dimension
        secondary_values = pd.to_numeric(
            frame["__secondary_metric"], errors="coerce"
        )
        valid = frame.assign(
            __x=pd.to_numeric(frame["__metric"], errors="coerce"),
            __y=secondary_values,
        ).dropna(subset=["__x", "__y"])
        if valid.empty:
            raise CampbellDataError(
                "No hay filas con ambas métricas presentes para el scatter"
            )
        status_column = self._column(frame, source.dimensions.get("status", ()))
        points = [
            {
                "label": str(row["__primary"]),
                "x": float(row["__x"]),
                "y": float(row["__y"]),
                "status": str(row[status_column]) if status_column else "",
            }
            for _, row in valid.head(max(limit, 30)).iterrows()
        ]
        figure = build_scatter(
            points,
            title=resolved_title,
            x_label=value_label,
            y_label=secondary_label,
            subtitle=subtitle,
        )
        summary = {
            str(point["label"]): [round(point["x"], 3), round(point["y"], 3)]
            for point in points[:5]
        }
        return figure, summary, len(points), float(valid["__x"].sum()), resolved_title

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
            raise CampbellDataError(
                f"Fuente no permitida para visualización: {dataset!r}. "
                f"Disponibles: {', '.join(sorted(CHART_SOURCES))}"
            )

        kind = str(chart_type).strip().lower()
        if kind not in CHART_TYPES:
            raise CampbellDataError(
                f"Tipo de gráfico no permitido: {chart_type!r}. "
                f"Disponibles: {', '.join(sorted(CHART_TYPES))}"
            )
        primary = str(dimension).strip().lower()
        secondary = str(secondary_dimension).strip().lower()
        resolved_metric = str(metric or "count").strip().lower()
        resolved_aggregation = str(aggregation or "count").strip().lower()
        if resolved_aggregation not in AGGREGATIONS:
            raise CampbellDataError(
                f"Agregación no permitida: {aggregation!r}. "
                f"Disponibles: {', '.join(sorted(AGGREGATIONS))}"
            )
        # Row-level charts plot the raw values, so an aggregation would flatten them.
        if kind in ROW_LEVEL_TYPES:
            if resolved_metric == "count":
                raise CampbellDataError(
                    f"El gráfico {kind} requiere una métrica numérica en 'metric', "
                    f"no 'count'. Disponibles para esta fuente: "
                    f"{', '.join(sorted(source.metrics)) or 'ninguna'}"
                )
            resolved_aggregation = "none"
        elif resolved_metric == "count":
            resolved_aggregation = "count"
        elif resolved_aggregation == "count":
            raise CampbellDataError("Una métrica numérica requiere sum, mean, max o min")

        if kind in {"line", "area"} and primary not in TIME_DIMENSIONS:
            raise CampbellDataError(
                f"El gráfico {kind} requiere una dimensión temporal: day, week o month"
            )
        if kind in PAIRED_TYPES and not secondary:
            raise CampbellDataError("Este gráfico requiere secondary_dimension")
        if kind == "scatter" and not secondary_metric_requested(secondary):
            raise CampbellDataError(
                "El gráfico scatter requiere una segunda métrica numérica en "
                "'secondary_dimension' (por ejemplo secondary_dimension=\"machine_score\")"
            )
        if kind not in PAIRED_TYPES | {"scatter"} and secondary:
            raise CampbellDataError(
                "secondary_dimension solo aplica a heatmap, stacked_bar o scatter"
            )
        if kind == "histogram" and primary not in {"", "unit"}:
            # The histogram bins the metric itself; a category would be ignored.
            raise CampbellDataError(
                "El histograma no usa 'dimension' para agrupar: bina la métrica. "
                "Usa box si quieres comparar la distribución entre categorías."
            )

        frame = self.repository.load(source.dataset, client).copy()
        frame = self._keep_latest(frame, source)
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
            frame = self.repository._filter_unit(frame, unit_col, str(unit_id)).copy()
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

        if kind == "histogram":
            # No grouping dimension: the metric itself is the axis.
            frame["__primary"] = ""
            primary_label = ""
        else:
            frame["__primary"], primary_label = self._dimension_series(
                frame, dates, source, primary
            )
        if kind == "scatter":
            # `secondary_dimension` names the second metric, not a category.
            secondary_values = self._metric_series(frame, source, secondary)
            if secondary_values is None:
                raise CampbellDataError(
                    "La segunda métrica del scatter no puede ser 'count'"
                )
            frame["__secondary_metric"] = secondary_values
            secondary_label = self._metric_label(secondary)
        elif secondary:
            frame["__secondary"], secondary_label = self._dimension_series(
                frame, dates, source, secondary
            )
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
        if resolved_metric == "count":
            value_label = METRIC_LABELS["count"]
        elif kind in ROW_LEVEL_TYPES:
            # No aggregation happened, so the label must not claim one.
            value_label = self._metric_label(resolved_metric)
        else:
            metric_name = METRIC_LABELS.get(
                resolved_metric, resolved_metric.replace("_", " ")
            )
            aggregation_name = AGGREGATION_LABELS.get(
                resolved_aggregation, resolved_aggregation.capitalize()
            )
            value_label = f"{aggregation_name} de {metric_name}"
        top_summary: dict[str, float | int] = {}
        resolved_title = str(title or "").strip()[:140]
        subtitle = self._window_subtitle(window)

        if kind in ROW_LEVEL_TYPES:
            figure, top_summary, categories, aggregated_total, resolved_title = (
                self._build_row_level(
                    frame=frame,
                    source=source,
                    kind=kind,
                    primary=primary,
                    primary_label=primary_label,
                    secondary_label=secondary_label,
                    value_label=value_label,
                    resolved_title=resolved_title,
                    subtitle=subtitle,
                    unit_id=unit_id,
                    limit=limit,
                )
            )
        elif kind in {"heatmap", "stacked_bar"}:
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
            matrix = matrix.reindex(
                index=list(top_primary), columns=list(top_secondary), fill_value=0
            )
            top_summary = {
                (
                    " × ".join(str(part) for part in index)
                    if isinstance(index, tuple)
                    else str(index)
                ): (int(value) if float(value).is_integer() else round(float(value), 3))
                for index, value in grouped.sort_values(ascending=False).head(5).items()
            }
            categories = int(matrix.shape[0] * matrix.shape[1])
            aggregated_total = float(grouped.sum())
            if not resolved_title:
                resolved_title = self._default_title(
                    source, kind, primary, primary_label, secondary_label, value_label
                )
            if unit_id:
                resolved_title += f" · {unit_id}"
            builder = build_heatmap if kind == "heatmap" else build_stacked_bar
            figure = builder(
                matrix,
                title=resolved_title,
                dimension_label=primary_label,
                secondary_label=secondary_label,
                value_label=value_label,
                subtitle=subtitle,
            )
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
            top_summary = {
                label: int(value) if float(value).is_integer() else round(value, 3)
                for label, value in zip(labels[:5], values[:5])
            }
            categories = len(labels)
            aggregated_total = float(sum(values))
            if not resolved_title:
                resolved_title = self._default_title(
                    source, kind, primary, primary_label, secondary_label, value_label
                )
            if unit_id:
                resolved_title += f" · {unit_id}"
            if kind == "line":
                figure = build_time_series(
                    labels,
                    values,
                    title=resolved_title,
                    dimension_label=primary_label,
                    value_label=value_label,
                    subtitle=subtitle,
                )
            elif kind == "area":
                figure = build_area(
                    labels,
                    values,
                    title=resolved_title,
                    dimension_label=primary_label,
                    value_label=value_label,
                    subtitle=subtitle,
                )
            elif kind == "pie":
                figure = build_pie(
                    labels,
                    values,
                    title=resolved_title,
                    value_label=value_label,
                    subtitle=subtitle,
                )
            elif kind == "pareto":
                figure = build_pareto(
                    labels,
                    values,
                    title=resolved_title,
                    dimension_label=primary_label,
                    value_label=value_label,
                    subtitle=subtitle,
                )
            elif kind == "treemap":
                figure = build_treemap(
                    labels,
                    values,
                    title=resolved_title,
                    dimension_label=primary_label,
                    value_label=value_label,
                    subtitle=subtitle,
                )
            else:
                figure = build_category_bar(
                    labels,
                    values,
                    title=resolved_title,
                    dimension_label=primary_label,
                    value_label=value_label,
                    subtitle=subtitle,
                    horizontal=kind == "horizontal_bar",
                )

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
            "dimension_label": primary_label,
            "secondary_dimension": secondary or None,
            "metric": resolved_metric,
            "aggregation": resolved_aggregation,
            "value_label": value_label,
        }
        return VisualizationArtifact(
            title=resolved_title,
            description=self._describe(source, kind, summary, subtitle),
            dataset=source.dataset,
            chart_type=kind,
            figure=json.loads(figure.to_json()),
            parameters={
                "dataset": dataset,
                "chart_type": kind,
                "dimension": primary,
                "secondary_dimension": secondary,
                "metric": resolved_metric,
                "aggregation": resolved_aggregation,
                "days": days,
                "start_date": start_date,
                "end_date": end_date,
                "unit_id": unit_id,
                "filter_dimension": filter_dimension,
                "filter_value": filter_value,
                "top_n": limit,
                "title": resolved_title,
            },
            summary=summary,
        )

    @staticmethod
    def _default_title(
        source: _ChartSource,
        kind: str,
        primary: str,
        primary_label: str,
        secondary_label: str,
        value_label: str,
    ) -> str:
        """Build a readable Spanish title without stacking repeated 'por' clauses."""
        subject = source.label
        dimension = primary_label.lower()
        # When the source label already names the dimension, repeating it reads badly
        # ("Componentes de aceite por componente").
        redundant = dimension.rstrip("s") in subject.lower()
        by_dimension = "" if redundant else f" por {dimension}"
        if kind == "pareto":
            return f"Pareto de {subject.lower()}{by_dimension or f' por {dimension}'}"
        if kind == "heatmap":
            return f"{subject}: {dimension} × {secondary_label.lower()}"
        if kind == "stacked_bar":
            return f"{subject} por {dimension} y {secondary_label.lower()}"
        if kind == "pie":
            return f"Distribución de {subject.lower()}{by_dimension}"
        if kind in {"line", "area"}:
            return f"Evolución de {subject.lower()} por {dimension}"
        if kind == "treemap":
            return f"Composición de {subject.lower()}{by_dimension}"
        if kind == "histogram":
            return f"{value_label} de {subject.lower()}: distribución"
        if kind == "box":
            return f"{value_label} de {subject.lower()}{by_dimension}: dispersión"
        if kind == "scatter":
            return f"{value_label} vs {secondary_label.lower()} de {subject.lower()}"
        if value_label != METRIC_LABELS["count"]:
            return f"{value_label} de {subject.lower()}{by_dimension}"
        return f"{subject}{by_dimension}"

    @staticmethod
    def _window_subtitle(window: dict[str, Any]) -> str:
        """Human-readable period so the chart states its own coverage."""
        start = str(window.get("data_min") or window.get("start_date") or "")[:10]
        end = str(window.get("data_max") or window.get("end_date") or "")[:10]
        if not start or not end:
            return ""
        if window.get("mode") == "relative" and window.get("days"):
            return f"Últimos {window['days']} días de datos · {start} a {end}"
        return f"Periodo {start} a {end}"

    @staticmethod
    def _describe(
        source: _ChartSource,
        kind: str,
        summary: dict[str, Any],
        subtitle: str,
    ) -> str:
        """Caption naming the source, period and leading categories of the figure."""
        names = {
            "bar": "Barras",
            "line": "Serie temporal",
            "pie": "Distribución",
            "pareto": "Pareto",
            "heatmap": "Mapa de calor",
            "stacked_bar": "Barras apiladas",
        }
        parts = [
            f"{names.get(kind, kind)} de {source.label.lower()} "
            f"por {str(summary['dimension_label']).lower()}"
            + (
                f" y {DIMENSION_LABELS.get(summary['secondary_dimension'], summary['secondary_dimension'])}".lower()
                if summary.get("secondary_dimension")
                else ""
            )
        ]
        if subtitle:
            parts.append(subtitle)
        parts.append(f"{summary['records_analyzed']} registros analizados")
        top = summary.get("top") or {}
        if top:
            leaders = ", ".join(f"{label} ({value})" for label, value in list(top.items())[:3])
            parts.append(f"mayores: {leaders}")
        return " · ".join(parts) + "."
