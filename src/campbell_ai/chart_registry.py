"""Curated catalogue of dashboard charts the agent can reproduce by name.

Plan section 14 asks for two high-level operations instead of letting the model
name Python functions:

- ``list_charts(client)``  — what this client is allowed to render;
- ``render(chart_id, ...)`` — produce a validated figure.

`visualization.py` already offers a general grammar (dataset × dimension × chart
type). This registry is the complement: named charts that mirror a specific
dashboard visual, so "muéstrame el estado de la flota" yields the same donut the
user sees in the Aceite tab rather than an ad-hoc pie.

`chart_id` and parameters are validated against explicit allowlists. No Python
name, expression or model-generated code is ever evaluated, and the company comes
from the authorized session, never from the chart definition.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd
import plotly.graph_objects as go

from src.campbell_ai.data import DashboardDataRepository, predictive_band, predictive_module_allows
from src.campbell_ai.errors import CampbellDataError
from src.campbell_ai.models import VisualizationArtifact
from src.charts.builders import (
    build_category_bar,
    build_signal_panels,
    build_gauge,
    build_heatmap,
    build_histogram,
    build_radar,
    build_stacked_bar,
    build_status_donut,
    build_time_series,
    build_treemap,
)
from src.charts.signals import signal_label
from src.charts.theme import STATUS_COLORS


# Parameters a caller may supply, with their coercion. Anything else is rejected.
ALLOWED_PARAMETERS: dict[str, type] = {
    "unit_id": str,
    "component": str,
    "domain": str,
    "alert_id": str,
    "signal": str,
    "top_n": int,
    "days": int,
    "start_date": str,
    "end_date": str,
}


@dataclass(frozen=True)
class ChartDefinition:
    chart_id: str
    title: str
    domain: str
    description: str
    datasets: tuple[str, ...]
    parameters: tuple[str, ...]
    builder: Callable[["DashboardChartRegistry", str, dict[str, Any]], tuple[go.Figure, dict[str, Any]]]
    chart_type: str = "bar"
    # Shown under the rendered figure. The description guides the agent's choice and
    # may mention required parameters, which would read as noise in a caption.
    caption: str = ""
    requires_predictive_module: bool = False
    tags: tuple[str, ...] = field(default=())


class DashboardChartRegistry:
    """Resolve, authorize and render named dashboard charts."""

    def __init__(self, repository: DashboardDataRepository):
        self.repository = repository

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _clamp(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            resolved = int(value)
        except (TypeError, ValueError):
            return default
        return max(minimum, min(resolved, maximum))

    def _column(self, frame: pd.DataFrame, candidates: tuple[str, ...]) -> str:
        column = DashboardDataRepository._resolve_column(frame, candidates)
        if not column:
            raise CampbellDataError(
                "La fuente no expone la columna requerida por este gráfico"
            )
        return column

    def _counts(self, frame: pd.DataFrame, column: str) -> dict[str, int]:
        return self.repository._distribution(frame, column, top=30)

    def _latest_telemetry(self, client: str, dataset: str) -> pd.DataFrame:
        """Newest evaluated week per unit (and component when present)."""
        frame = self.repository.load(dataset, client).copy()
        unit = self._column(frame, ("unit_id", "unitId", "UnitId"))
        keys = [unit]
        component = DashboardDataRepository._resolve_column(
            frame, ("component", "componentName")
        )
        if component:
            keys.append(component)
        order = [
            column
            for column in (
                DashboardDataRepository._resolve_column(frame, ("evaluation_year",)),
                DashboardDataRepository._resolve_column(frame, ("evaluation_week",)),
            )
            if column
        ]
        if not order:
            return frame
        for column in order:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.sort_values(order).groupby(keys, dropna=False).tail(1).copy()

    @staticmethod
    def _week_subtitle(frame: pd.DataFrame) -> str:
        for week_key, year_key in (("evaluation_week", "evaluation_year"),):
            if week_key in frame.columns:
                week = pd.to_numeric(frame[week_key], errors="coerce").max()
                year = (
                    pd.to_numeric(frame[year_key], errors="coerce").max()
                    if year_key in frame.columns
                    else None
                )
                if pd.notna(week):
                    label = f"Semana {int(week)}"
                    if year is not None and pd.notna(year):
                        label += f" de {int(year)}"
                    return label
        return ""

    # ---------------------------------------------------------------- builders

    def _oil_fleet_status(self, client: str, params: dict[str, Any]):
        frame = self.repository.load("oil_machine_status", client).copy()
        status = self._column(frame, ("overall_status", "report_status"))
        counts = self._counts(frame, status)
        date_column = DashboardDataRepository._resolve_column(
            frame, ("latest_sample_date",)
        )
        subtitle = ""
        if date_column:
            dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
            if not dates.empty:
                subtitle = (
                    f"Muestras entre {dates.min().date()} y {dates.max().date()}"
                )
        figure = build_status_donut(
            counts,
            title="Estado de la flota según análisis de aceite",
            total_label="equipos",
            subtitle=subtitle,
        )
        return figure, {"by_status": counts, "units": int(len(frame)), "period": subtitle}

    def _telemetry_fleet_status(self, client: str, params: dict[str, Any]):
        frame = self._latest_telemetry(client, "telemetry_machine_status")
        status = self._column(frame, ("overall_status", "component_status"))
        counts = self._counts(frame, status)
        subtitle = self._week_subtitle(frame)
        figure = build_status_donut(
            counts,
            title="Estado de la flota según telemetría",
            total_label="equipos",
            subtitle=subtitle,
        )
        return figure, {"by_status": counts, "units": int(len(frame)), "period": subtitle}

    def _telemetry_component_status(self, client: str, params: dict[str, Any]):
        frame = self._latest_telemetry(client, "telemetry_classified")
        component = self._column(frame, ("component", "componentName"))
        status = self._column(frame, ("component_status", "overall_status"))
        matrix = (
            frame.groupby([component, status], dropna=False).size().unstack(fill_value=0)
        )
        # Worst-first so the components needing attention sit at the top.
        weights = {"Anormal": 100, "Alerta": 10}
        burden = sum(
            matrix.get(label, 0) * weight for label, weight in weights.items()
        )
        matrix = matrix.loc[
            burden.sort_values(ascending=False).index
            if hasattr(burden, "sort_values")
            else matrix.index
        ]
        figure = build_stacked_bar(
            matrix,
            title="Condición de componentes por telemetría",
            dimension_label="Componente",
            secondary_label="Estado",
            value_label="Equipos",
            subtitle=self._week_subtitle(frame),
        )
        return figure, {
            "components": int(matrix.shape[0]),
            "by_status": self._counts(frame, status),
        }

    def _oil_component_status(self, client: str, params: dict[str, Any]):
        frame = self.repository.load("oil_classified", client).copy()
        unit = self._column(frame, ("unitId", "unit_id", "UnitId"))
        component = self._column(frame, ("componentNameNormalized", "componentName"))
        status = self._column(frame, ("report_status", "overall_status"))
        date_column = self._column(frame, ("sampleDate", "reportDate"))
        frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
        frame = (
            frame.sort_values(date_column)
            .groupby([unit, component], dropna=False)
            .tail(1)
            .copy()
        )
        matrix = (
            frame.groupby([component, status], dropna=False).size().unstack(fill_value=0)
        )
        weights = {"Anormal": 100, "Alerta": 10}
        burden = sum(matrix.get(label, 0) * weight for label, weight in weights.items())
        if hasattr(burden, "sort_values"):
            matrix = matrix.loc[burden.sort_values(ascending=False).index]
        figure = build_stacked_bar(
            matrix,
            title="Condición de componentes por análisis de aceite",
            dimension_label="Componente",
            secondary_label="Estado",
            value_label="Equipos",
            subtitle="Muestra más reciente por equipo y componente",
        )
        return figure, {
            "components": int(matrix.shape[0]),
            "by_status": self._counts(frame, status),
        }

    def _alert_ranking(self, client: str, params: dict[str, Any]):
        days = self._clamp(params.get("days"), 60, 1, 3650)
        top_n = self._clamp(params.get("top_n"), 15, 3, 30)
        raw = json.loads(self.repository.query_alerts(client, days=days, limit=1))
        counts = raw.get("by_unit") or {}
        if not counts:
            raise CampbellDataError("No hay alertas en la ventana solicitada")
        items = list(counts.items())[:top_n]
        window = raw.get("window", {})
        subtitle = ""
        if window.get("data_min") and window.get("data_max"):
            subtitle = (
                f"Últimos {days} días de datos · "
                f"{str(window['data_min'])[:10]} a {str(window['data_max'])[:10]}"
            )
        figure = build_category_bar(
            [str(label) for label, _ in items],
            [float(value) for _, value in items],
            title="Equipos con más alertas",
            dimension_label="Equipo",
            value_label="Alertas",
            subtitle=subtitle,
        )
        return figure, {"total": raw.get("total"), "top": dict(items), "window": window}

    def _predictive_ranking(self, client: str, params: dict[str, Any]):
        top_n = self._clamp(params.get("top_n"), 15, 3, 30)
        raw = json.loads(
            self.repository.query_predictive_risk(client, domain="motor", limit=top_n)
        )
        if not raw.get("ranking_available", False) or not raw.get("records"):
            raise CampbellDataError(
                "El modelo predictivo de motor no tiene ranking calculado para este cliente"
            )
        records = raw["records"]
        figure = build_category_bar(
            [str(item["unit_id"]) for item in records],
            [float(item["ranking"]) for item in records],
            title="Ranking de riesgo predictivo de motor",
            dimension_label="Equipo",
            value_label="Ranking de riesgo",
            subtitle="Mayor ranking = mayor prioridad · "
            + str(raw.get("bands", {}).get("definicion", "")),
            horizontal=True,
        )
        return figure, {
            "bands": raw.get("bands"),
            "top": {
                str(item["unit_id"]): {
                    "ranking": item["ranking"],
                    "band": predictive_band(float(item["ranking"])),
                }
                for item in records[:5]
            },
        }

    # ------------------------------------------------------- migrated dashboard views

    def _alert_trend(self, client: str, params: dict[str, Any]):
        """Alerts over time, mirroring the alerts tab's monthly trend."""
        days = self._clamp(params.get("days"), 365, 30, 3650)
        raw = json.loads(self.repository.query_alerts(client, days=days, limit=1))
        by_month = raw.get("by_month") or {}
        if not by_month:
            raise CampbellDataError("No hay alertas con fecha en la ventana solicitada")
        labels = sorted(by_month)
        values = [float(by_month[label]) for label in labels]
        window = raw.get("window", {})
        subtitle = ""
        if window.get("data_min") and window.get("data_max"):
            subtitle = f"{str(window['data_min'])[:10]} a {str(window['data_max'])[:10]}"
        figure = build_time_series(
            labels,
            values,
            title="Evolución mensual de alertas",
            dimension_label="Mes",
            value_label="Alertas",
            subtitle=subtitle,
        )
        return figure, {
            "total": raw.get("total"),
            "by_month": {label: int(by_month[label]) for label in labels},
            "days": days,
            "window": window,
        }

    def _alert_trigger_treemap(self, client: str, params: dict[str, Any]):
        """Share of each trigger type, mirroring the alerts tab treemap."""
        days = self._clamp(params.get("days"), 365, 7, 3650)
        raw = json.loads(self.repository.query_alerts(client, days=days, limit=1))
        counts = raw.get("by_trigger_type") or {}
        if not counts:
            raise CampbellDataError("La fuente no expone tipos de disparador")
        labels = list(counts)
        window = raw.get("window", {})
        figure = build_treemap(
            labels,
            [float(counts[label]) for label in labels],
            title="Composición de alertas por tipo de disparador",
            dimension_label="Tipo de disparador",
            value_label="Alertas",
            subtitle=f"Últimos {days} días de datos",
        )
        # The window travels in the summary too: an answer that writes "últimos 60
        # días" must be able to trace that number to a tool result.
        return figure, {
            "total": raw.get("total"),
            "by_trigger_type": counts,
            "days": days,
            "window": window,
        }

    def _telemetry_component_heatmap(self, client: str, params: dict[str, Any]):
        """Unit × component condition, mirroring the telemetry fleet heatmap."""
        frame = self._latest_telemetry(client, "telemetry_classified")
        unit = self._column(frame, ("unit_id", "unitId", "UnitId"))
        component = self._column(frame, ("component", "componentName"))
        score = self._column(frame, ("component_score",))
        matrix = (
            frame.pivot_table(
                index=unit, columns=component, values=score, aggfunc="min"
            )
            .fillna(0)
            .sort_index()
        )
        if matrix.empty:
            raise CampbellDataError("Sin datos de componentes por equipo")
        figure = build_heatmap(
            matrix,
            title="Condición de componentes por equipo (telemetría)",
            dimension_label="Equipo",
            secondary_label="Componente",
            value_label="Puntaje del componente",
            subtitle=self._week_subtitle(frame),
        )
        status = self._column(frame, ("component_status", "overall_status"))
        return figure, {
            "units": int(matrix.shape[0]),
            "components": int(matrix.shape[1]),
            "by_status": self._counts(frame, status),
            "note": "Un puntaje menor indica peor condición del componente.",
        }

    def _oil_essay_radar(self, client: str, params: dict[str, Any]):
        """Oil essays of one component against their thresholds.

        Essays live on incomparable scales (iron in the tens, zinc in the thousands),
        so each axis is the ratio of the measurement to its alert threshold. A ring at
        1.0 is the limit itself, which makes one glance enough. The summary keeps the
        raw values and thresholds so the agent cites measured numbers, not ratios.
        """
        unit_id = str(params.get("unit_id") or "").strip()
        if not unit_id:
            raise CampbellDataError(
                "oil_essay_radar requiere unit_id (por ejemplo unit_id=\"T_15\")"
            )
        component = str(params.get("component") or "").strip()

        samples = self.repository.load("oil_classified", client).copy()
        unit_col = self._column(samples, ("unitId", "unit_id", "UnitId"))
        component_col = self._column(samples, ("componentNameNormalized", "componentName"))
        date_col = self._column(samples, ("sampleDate", "reportDate"))
        samples[date_col] = pd.to_datetime(samples[date_col], errors="coerce")
        samples = self.repository._filter_unit(samples, unit_col, unit_id)
        if component:
            samples = self.repository._filter_contains(samples, component_col, component)
        if samples.empty:
            raise CampbellDataError(
                f"Sin muestras de aceite para {unit_id}"
                + (f" y componente {component}" if component else "")
            )
        # Without an explicit component, the newest sample is an arbitrary pick that
        # can silently answer about a different component than the user asked about.
        # Choose the one in the worst condition and record why.
        status_col = DashboardDataRepository._resolve_column(
            samples, ("report_status", "overall_status")
        )
        severity_col = DashboardDataRepository._resolve_column(samples, ("severity_score",))
        if component:
            selection = "componente solicitado"
            latest = samples.sort_values(date_col).iloc[-1]
        else:
            severity = {"Anormal": 0, "Alerta": 1, "Normal": 2}
            candidates = (
                samples.sort_values(date_col)
                .groupby(component_col, dropna=False)
                .tail(1)
                .copy()
            )
            order: list[str] = []
            if status_col:
                candidates["__severity"] = candidates[status_col].map(
                    lambda value: severity.get(str(value), 3)
                )
                order.append("__severity")
            if severity_col:
                candidates["__score"] = -pd.to_numeric(
                    candidates[severity_col], errors="coerce"
                ).fillna(0)
                order.append("__score")
            if order:
                candidates = candidates.sort_values(order)
                selection = "componente en peor condición"
            else:
                candidates = candidates.sort_values(date_col, ascending=False)
                selection = "muestra más reciente"
            latest = candidates.iloc[0]
        resolved_component = str(latest[component_col])

        limits = self.repository.load("oil_limits", client)
        scoped = limits[
            limits["component"].astype(str).str.casefold() == resolved_component.casefold()
        ]
        if scoped.empty:
            raise CampbellDataError(
                f"No hay límites de referencia para el componente {resolved_component}"
            )
        hour_range = str(latest.get("oilHourRange") or "")
        if hour_range and (scoped["oilHourRange"].astype(str) == hour_range).any():
            scoped = scoped[scoped["oilHourRange"].astype(str) == hour_range]

        axes: list[str] = []
        ratios: list[float] = []
        detail: dict[str, Any] = {}
        for _, row in scoped.iterrows():
            essay = str(row["essay"])
            if essay not in samples.columns:
                continue
            measured = pd.to_numeric(latest.get(essay), errors="coerce")
            threshold = pd.to_numeric(row.get("threshold_alert"), errors="coerce")
            if pd.isna(measured) or pd.isna(threshold) or float(threshold) <= 0:
                continue
            axes.append(essay)
            ratios.append(round(float(measured) / float(threshold), 3))
            detail[essay] = {
                "value": round(float(measured), 3),
                "threshold_alert": round(float(threshold), 3),
                "threshold_critic": (
                    round(float(row["threshold_critic"]), 3)
                    if pd.notna(row.get("threshold_critic"))
                    else None
                ),
            }
        if len(axes) < 3:
            raise CampbellDataError(
                "Se necesitan al menos 3 ensayos con límite para construir el radar"
            )

        status = str(latest.get("report_status") or "")
        figure = build_radar(
            [
                {
                    "label": f"{unit_id} · {resolved_component}",
                    "values": ratios,
                    "status": status,
                },
                {
                    "label": "Límite de alerta",
                    "values": [1.0] * len(axes),
                    "fill": False,
                },
            ],
            axes,
            title=f"Ensayos de aceite vs límite · {unit_id} · {resolved_component}",
            value_label="Proporción respecto al límite de alerta",
            subtitle=(
                f"Muestra del {latest[date_col].date()}"
                if pd.notna(latest[date_col])
                else ""
            ),
        )
        return figure, {
            "unit_id": unit_id,
            "component": resolved_component,
            "component_selected_by": selection,
            "components_available": sorted(
                {str(value) for value in samples[component_col].dropna().unique()}
            ),
            "status": status,
            "essays": detail,
            "above_alert_limit": [
                essay for essay, ratio in zip(axes, ratios) if ratio >= 1
            ],
            "note": (
                "Cada eje es el valor medido dividido por su límite de alerta; 1.0 es el "
                "límite. Los valores absolutos están en 'essays'. La figura corresponde "
                f"al componente '{resolved_component}': descríbelo con ese nombre, no "
                "con el que hayas asumido."
            ),
        }

    def _predictive_risk_radar(self, client: str, params: dict[str, Any]):
        """Failure-mode profile of one unit against the fleet, as in the predictive tab."""
        unit_id = str(params.get("unit_id") or "").strip()
        if not unit_id:
            raise CampbellDataError(
                "predictive_risk_radar requiere unit_id (por ejemplo unit_id=\"T_15\")"
            )
        domain = str(params.get("domain") or "motor").strip().lower()
        payload = json.loads(
            self.repository.query_predictive_risk(client, domain=domain, limit=30)
        )
        if not payload.get("ranking_available") or not payload.get("records"):
            raise CampbellDataError(
                f"El modelo predictivo de {domain} no tiene ranking calculado"
            )
        records = payload["records"]
        target = next(
            (
                item
                for item in records
                if self.repository._normalize_unit(item["unit_id"])
                == self.repository._normalize_unit(unit_id)
            ),
            None,
        )
        if target is None:
            raise CampbellDataError(
                f"{unit_id} no aparece en el modelo predictivo de {domain}"
            )
        axes = list(target.get("top_risks") or {})
        if len(axes) < 3:
            raise CampbellDataError("El equipo no tiene suficientes modos de riesgo")

        fleet_median: list[float] = []
        for axis in axes:
            values = [
                float(item["top_risks"][axis])
                for item in records
                if axis in (item.get("top_risks") or {})
            ]
            fleet_median.append(
                round(float(pd.Series(values).median()), 1) if values else 0.0
            )
        figure = build_radar(
            [
                {
                    "label": str(target["unit_id"]),
                    "values": [float(target["top_risks"][axis]) for axis in axes],
                    "status": str(target.get("band") or ""),
                },
                {"label": "Mediana de la flota", "values": fleet_median, "fill": False},
            ],
            axes,
            title=f"Modos de riesgo predictivo · {target['unit_id']} · {domain}",
            value_label="Riesgo del modelo",
            subtitle=f"Banda {target.get('band')} · ranking {target.get('ranking')}",
        )
        return figure, {
            "unit_id": target["unit_id"],
            "domain": payload.get("domain"),
            "ranking": target.get("ranking"),
            "band": target.get("band"),
            "top_risks": target.get("top_risks"),
            "fleet_median": dict(zip(axes, fleet_median)),
            "note": payload.get("note"),
        }

    def _oil_severity_histogram(self, client: str, params: dict[str, Any]):
        """Spread of component severity, to see whether risk is concentrated."""
        frame = self.repository.load("oil_classified", client).copy()
        unit_col = self._column(frame, ("unitId", "unit_id", "UnitId"))
        component_col = self._column(frame, ("componentNameNormalized", "componentName"))
        date_col = self._column(frame, ("sampleDate", "reportDate"))
        severity = self._column(frame, ("severity_score",))
        frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
        frame = (
            frame.sort_values(date_col)
            .groupby([unit_col, component_col], dropna=False)
            .tail(1)
        )
        values = pd.to_numeric(frame[severity], errors="coerce").dropna()
        if values.empty:
            raise CampbellDataError("Sin puntajes de severidad disponibles")
        figure = build_histogram(
            [float(value) for value in values],
            title="Distribución de severidad por componente (aceite)",
            value_label="Puntaje de severidad",
            bins=15,
            subtitle="Muestra más reciente por equipo y componente",
        )
        return figure, {
            "components_evaluated": int(len(values)),
            "min": round(float(values.min()), 3),
            "max": round(float(values.max()), 3),
            "mean": round(float(values.mean()), 3),
            "median": round(float(values.median()), 3),
        }

    def _unit_health_gauge(self, client: str, params: dict[str, Any]):
        """One unit's telemetry priority against its bands, as a single indicator."""
        unit_id = str(params.get("unit_id") or "").strip()
        if not unit_id:
            raise CampbellDataError(
                "unit_health_gauge requiere unit_id (por ejemplo unit_id=\"T_18\")"
            )
        payload = json.loads(
            self.repository.query_telemetry_health(client, unit_id=unit_id, limit=1)
        )
        records = payload.get("records") or []
        if not records:
            raise CampbellDataError(f"Sin evaluación de telemetría para {unit_id}")
        record = records[0]
        score = record.get("priority_score")
        if score is None:
            raise CampbellDataError("La fuente no expone priority_score para este equipo")
        maximum = max(100.0, float(score) * 1.2)
        figure = build_gauge(
            float(score),
            title=f"Prioridad de telemetría · {unit_id}",
            value_label="Puntaje de prioridad",
            maximum=maximum,
            bands=[
                (0, maximum * 0.35, STATUS_COLORS["Normal"]),
                (maximum * 0.35, maximum * 0.75, STATUS_COLORS["Alerta"]),
                (maximum * 0.75, maximum, STATUS_COLORS["Anormal"]),
            ],
            subtitle=str(payload.get("evaluation", {}).get("latest_week") or "")
            and f"Semana {payload['evaluation']['latest_week']}",
        )
        return figure, {
            "unit_id": unit_id,
            "priority_score": score,
            "overall_status": record.get("overall_status"),
            "components_anormal": record.get("components_anormal"),
            "components_alerta": record.get("components_alerta"),
            "scale_max": round(maximum, 1),
            "note": "Un puntaje de prioridad mayor implica mayor urgencia de atención.",
        }

    def _alert_sensor_trend(self, client: str, params: dict[str, Any]):
        """Per-signal series of one alert against its limits, one panel per signal."""
        requested = str(params.get("signal") or "").strip()
        signals = tuple(
            item.strip()
            for item in requested.replace(";", ",").split(",")
            if item.strip()
        )
        payload = self.repository.alert_signal_series(
            client,
            alert_id=str(params.get("alert_id") or ""),
            unit_id=str(params.get("unit_id") or ""),
            signals=signals,
        )
        panels = [
            {**panel, "label": signal_label(panel["signal"]) or panel["signal"]}
            for panel in payload["panels"]
        ]
        if not panels:
            raise CampbellDataError(
                "Ninguna de las señales solicitadas tiene valores capturados en esta "
                f"alerta. Disponibles: {', '.join(payload['signals_available'])}"
            )
        window = payload["window"]
        figure = build_signal_panels(
            panels,
            title=(
                f"Señales de la alerta {payload['alert_id']} · {payload['unit_id']}"
            ),
            subtitle=f"{str(window['start'])[:16]} a {str(window['end'])[:16]}",
        )
        return figure, {
            "alert_id": payload["alert_id"],
            "unit_id": payload["unit_id"],
            "trigger": payload["trigger"],
            "samples": payload["samples"],
            "window": window,
            "signals_plotted": payload["signals_selected"],
            "signals_available": payload["signals_available"],
            "signals_unknown": payload["signals_unknown"],
            "note": (
                "Cada panel tiene su propia escala porque las señales no son "
                "comparables. La banda sombreada es el rango permitido y el umbral "
                "puede variar con el estado de máquina."
            ),
        }

    def _telemetry_signal_trend(self, client: str, params: dict[str, Any]):
        """Continuous telemetry series for a unit over a date window, any signal(s).

        Complements alert_sensor_trend: that one is scoped to a single alert's own
        sampling window, this reads the raw continuous source directly so the
        agent can plot signals unrelated to any specific alert (issue: "telemetry
        charts should be able to include variables other than the one alerted").
        """
        payload = json.loads(
            self.repository.query_telemetry_series(
                client,
                unit_id=str(params.get("unit_id") or ""),
                signals=str(params.get("signal") or ""),
                days=int(params.get("days") or 30),
                start_date=str(params.get("start_date") or ""),
                end_date=str(params.get("end_date") or ""),
            )
        )
        panels = [
            {**panel, "label": signal_label(panel["signal"]) or panel["signal"]}
            for panel in payload["panels"]
        ]
        window = payload["window"]
        figure = build_signal_panels(
            panels,
            title=f"Telemetría de {payload['unit_id']}",
            subtitle=f"{str(window['start'])[:10]} a {str(window['end'])[:10]}",
        )
        return figure, {
            "unit_id": payload["unit_id"],
            "samples": payload["samples"],
            "window": window,
            "signals_plotted": payload["signals_selected"],
            "signals_available": payload["signals_available"],
            "signals_unknown": payload["signals_unknown"],
            "note": (
                "Serie continua de telemetría cruda, independiente de cualquier "
                "alerta específica. No hay banda de límites porque esta fuente no "
                "los publica; para el límite vigente durante una alerta usa "
                "alert_sensor_trend."
            ),
        }

    # ---------------------------------------------------------------- catalogue

    def definitions(self) -> tuple[ChartDefinition, ...]:
        return CHART_DEFINITIONS

    def list_charts(self, client: str) -> list[dict[str, Any]]:
        """Charts this client can render, with their datasets already validated."""
        validation = self.repository.validate_client(client)
        datasets = validation["datasets"]
        predictive_allowed = predictive_module_allows(client)
        available: list[dict[str, Any]] = []
        for definition in CHART_DEFINITIONS:
            if definition.requires_predictive_module and not predictive_allowed:
                continue
            missing = [
                key
                for key in definition.datasets
                if not datasets.get(key, {}).get("valid")
            ]
            if missing:
                continue
            available.append(
                {
                    "chart_id": definition.chart_id,
                    "title": definition.title,
                    "domain": definition.domain,
                    "description": definition.description,
                    "parameters": list(definition.parameters),
                }
            )
        return available

    def render(
        self, client: str, chart_id: str, parameters: dict[str, Any] | None = None
    ) -> VisualizationArtifact:
        """Render a named chart after validating its id, access and parameters."""
        resolved_id = str(chart_id or "").strip().lower()
        definition = _DEFINITION_MAP.get(resolved_id)
        if definition is None:
            raise CampbellDataError(
                f"chart_id no reconocido: {resolved_id or '(vacio)'}. "
                f"Disponibles: {', '.join(sorted(_DEFINITION_MAP))}"
            )
        if definition.requires_predictive_module and not predictive_module_allows(client):
            raise CampbellDataError(
                "El modulo predictivo no esta habilitado para el cliente activo"
            )

        supplied = parameters or {}
        unexpected = set(supplied) - set(definition.parameters)
        if unexpected:
            raise CampbellDataError(
                f"Parámetros no permitidos para {resolved_id}: {', '.join(sorted(unexpected))}"
            )
        cleaned: dict[str, Any] = {}
        for name, value in supplied.items():
            if value in (None, ""):
                continue
            expected = ALLOWED_PARAMETERS.get(name)
            if expected is None:
                raise CampbellDataError(f"Parámetro no soportado: {name}")
            cleaned[name] = value

        figure, summary = definition.builder(self, client, cleaned)
        return VisualizationArtifact(
            chart_id=f"{definition.chart_id}",
            title=str(figure.layout.title.text or definition.title).split("<br>")[0],
            description=self._describe(definition, summary),
            dataset=definition.datasets[0],
            chart_type=definition.chart_type,
            figure=json.loads(figure.to_json()),
            parameters={"chart_id": definition.chart_id, **cleaned},
            summary={"chart_id": definition.chart_id, **summary},
        )

    @staticmethod
    def _describe(definition: ChartDefinition, summary: dict[str, Any]) -> str:
        """Caption naming the source, period and the figure's leading facts."""
        parts = [definition.caption or definition.description]
        if summary.get("period"):
            parts.append(str(summary["period"]))

        by_status = summary.get("by_status")
        if isinstance(by_status, dict) and by_status:
            parts.append(
                "distribución: "
                + ", ".join(f"{label} ({value})" for label, value in by_status.items())
            )

        triggers = summary.get("by_trigger_type")
        if isinstance(triggers, dict) and triggers:
            parts.append(
                "por disparador: "
                + ", ".join(f"{label} ({value})" for label, value in list(triggers.items())[:4])
            )

        months = summary.get("by_month")
        if isinstance(months, dict) and months:
            peak = max(months.items(), key=lambda item: item[1])
            parts.append(
                f"{len(months)} meses con datos, máximo {peak[1]} en {peak[0]}"
            )

        # State which component the figure actually shows, so a caption cannot drift
        # from the requested one.
        if summary.get("component"):
            component_note = str(summary["component"])
            if summary.get("component_selected_by") == "componente en peor condición":
                component_note += " (el de peor condición)"
            parts.append(f"componente {component_note}")

        # Oil radar: name the essays that reached or passed their alert threshold.
        breached = summary.get("above_alert_limit")
        if isinstance(breached, list):
            essays = summary.get("essays") or {}
            if breached:
                rendered = ", ".join(
                    f"{essay} {essays.get(essay, {}).get('value')} "
                    f"(límite {essays.get(essay, {}).get('threshold_alert')})"
                    for essay in breached[:4]
                )
                parts.append(f"sobre el límite de alerta: {rendered}")
            else:
                parts.append("ningún ensayo alcanza su límite de alerta")

        if summary.get("ranking") is not None:
            parts.append(
                f"ranking {summary['ranking']} en banda {summary.get('band')}"
            )
        if summary.get("priority_score") is not None:
            parts.append(
                f"prioridad {summary['priority_score']}, estado "
                f"{summary.get('overall_status')}"
            )
        if summary.get("median") is not None:
            parts.append(
                f"mediana {summary['median']}, rango {summary.get('min')}–{summary.get('max')}"
            )
        if summary.get("units") and summary.get("components"):
            parts.append(
                f"{summary['units']} equipos × {summary['components']} componentes"
            )

        top = summary.get("top")
        if isinstance(top, dict) and top:
            rendered = []
            for label, value in list(top.items())[:3]:
                if isinstance(value, dict):
                    rendered.append(f"{label} ({value.get('ranking')}, {value.get('band')})")
                else:
                    rendered.append(f"{label} ({value})")
            parts.append("mayores: " + ", ".join(rendered))
        return " · ".join(part for part in parts if part) + "."


CHART_DEFINITIONS: tuple[ChartDefinition, ...] = (
    ChartDefinition(
        chart_id="oil_fleet_status",
        title="Estado de la flota según análisis de aceite",
        domain="aceite",
        description="Donut del estado global por equipo según su muestra de aceite más reciente",
        datasets=("oil_machine_status",),
        parameters=(),
        builder=DashboardChartRegistry._oil_fleet_status,
        chart_type="pie",
        tags=("flota", "estado", "aceite"),
    ),
    ChartDefinition(
        chart_id="telemetry_fleet_status",
        title="Estado de la flota según telemetría",
        domain="telemetria",
        description="Donut del estado global por equipo en la última semana evaluada",
        datasets=("telemetry_machine_status",),
        parameters=(),
        builder=DashboardChartRegistry._telemetry_fleet_status,
        chart_type="pie",
        tags=("flota", "estado", "telemetria"),
    ),
    ChartDefinition(
        chart_id="telemetry_component_status",
        title="Condición de componentes por telemetría",
        domain="telemetria",
        description="Barras apiladas de componentes por estado, ordenadas por carga anormal",
        datasets=("telemetry_classified",),
        parameters=(),
        builder=DashboardChartRegistry._telemetry_component_status,
        chart_type="stacked_bar",
        tags=("componentes", "telemetria"),
    ),
    ChartDefinition(
        chart_id="oil_component_status",
        title="Condición de componentes por análisis de aceite",
        domain="aceite",
        description="Barras apiladas de componentes por estado en su muestra más reciente",
        datasets=("oil_classified",),
        parameters=(),
        builder=DashboardChartRegistry._oil_component_status,
        chart_type="stacked_bar",
        tags=("componentes", "aceite"),
    ),
    ChartDefinition(
        chart_id="alert_ranking",
        caption="Ranking de equipos por cantidad de alertas",
        title="Equipos con más alertas",
        domain="alertas",
        description="Ranking de equipos por cantidad de alertas en la ventana solicitada",
        datasets=("alerts",),
        parameters=("days", "top_n"),
        builder=DashboardChartRegistry._alert_ranking,
        chart_type="bar",
        tags=("ranking", "alertas"),
    ),
    ChartDefinition(
        chart_id="predictive_motor_ranking",
        caption="Ranking de riesgo predictivo de motor por equipo",
        title="Ranking de riesgo predictivo de motor",
        domain="predictivo",
        description="Ranking de riesgo por equipo con sus bandas de salud",
        datasets=("predictive_motor",),
        parameters=("top_n",),
        builder=DashboardChartRegistry._predictive_ranking,
        chart_type="bar",
        requires_predictive_module=True,
        tags=("ranking", "predictivo"),
    ),
    ChartDefinition(
        chart_id="alert_trend",
        title="Evolución mensual de alertas",
        domain="alertas",
        description="Serie temporal de alertas por mes en la ventana solicitada",
        datasets=("alerts",),
        parameters=("days",),
        builder=DashboardChartRegistry._alert_trend,
        chart_type="line",
        tags=("tendencia", "alertas"),
    ),
    ChartDefinition(
        chart_id="alert_trigger_treemap",
        title="Composición de alertas por tipo de disparador",
        domain="alertas",
        description="Treemap con la participación de cada tipo de disparador",
        datasets=("alerts",),
        parameters=("days",),
        builder=DashboardChartRegistry._alert_trigger_treemap,
        chart_type="treemap",
        tags=("composicion", "alertas"),
    ),
    ChartDefinition(
        chart_id="telemetry_component_heatmap",
        title="Condición de componentes por equipo (telemetría)",
        domain="telemetria",
        description="Mapa de calor equipo × componente con el puntaje de cada componente",
        datasets=("telemetry_classified",),
        parameters=(),
        builder=DashboardChartRegistry._telemetry_component_heatmap,
        chart_type="heatmap",
        tags=("heatmap", "telemetria", "componentes"),
    ),
    ChartDefinition(
        chart_id="oil_essay_radar",
        caption="Ensayos de la muestra más reciente comparados con su límite de alerta",
        title="Ensayos de aceite vs límites de un componente",
        domain="aceite",
        description=(
            "Radar de los ensayos de la muestra más reciente comparados con su límite "
            "de alerta; requiere unit_id y opcionalmente component"
        ),
        datasets=("oil_classified", "oil_limits"),
        parameters=("unit_id", "component"),
        builder=DashboardChartRegistry._oil_essay_radar,
        chart_type="radar",
        tags=("radar", "aceite", "ensayos"),
    ),
    ChartDefinition(
        chart_id="predictive_risk_radar",
        caption="Modos de riesgo del modelo frente a la mediana de la flota",
        title="Modos de riesgo predictivo de un equipo",
        domain="predictivo",
        description=(
            "Radar de los modos de falla del modelo comparados con la mediana de la "
            "flota; requiere unit_id y admite domain motor o transmision"
        ),
        datasets=("predictive_motor",),
        parameters=("unit_id", "domain"),
        builder=DashboardChartRegistry._predictive_risk_radar,
        chart_type="radar",
        requires_predictive_module=True,
        tags=("radar", "predictivo"),
    ),
    ChartDefinition(
        chart_id="oil_severity_histogram",
        title="Distribución de severidad por componente (aceite)",
        domain="aceite",
        description="Histograma del puntaje de severidad de la muestra más reciente",
        datasets=("oil_classified",),
        parameters=(),
        builder=DashboardChartRegistry._oil_severity_histogram,
        chart_type="histogram",
        tags=("distribucion", "aceite"),
    ),
    ChartDefinition(
        chart_id="unit_health_gauge",
        caption="Puntaje de prioridad del equipo dentro de sus bandas",
        title="Prioridad de telemetría de un equipo",
        domain="telemetria",
        description=(
            "Indicador del puntaje de prioridad de un equipo con sus bandas; "
            "requiere unit_id"
        ),
        datasets=("telemetry_machine_status",),
        parameters=("unit_id",),
        builder=DashboardChartRegistry._unit_health_gauge,
        chart_type="gauge",
        tags=("indicador", "telemetria"),
    ),
    ChartDefinition(
        chart_id="alert_sensor_trend",
        caption="Series de las señales de la alerta contra su rango permitido",
        title="Señales de una alerta contra sus límites",
        domain="alertas",
        description=(
            "Serie temporal por señal de una alerta, con su banda de límites. Por "
            "defecto grafica la señal disparadora; unit_id es necesario y alert_id "
            "opcional (sin él usa la alerta más reciente del equipo). Con signal puedes "
            "pedir varias separadas por coma"
        ),
        datasets=("alerts_detail",),
        parameters=("unit_id", "alert_id", "signal"),
        builder=DashboardChartRegistry._alert_sensor_trend,
        chart_type="line",
        tags=("alertas", "senales", "evidencia"),
    ),
    ChartDefinition(
        chart_id="telemetry_signal_trend",
        caption="Serie continua de telemetría cruda para un equipo, cualquier señal",
        title="Telemetría de un equipo en el tiempo",
        domain="telemetria",
        description=(
            "Serie temporal de una o varias señales de telemetría cruda para un "
            "equipo, en cualquier ventana de fechas — no requiere que la señal haya "
            "disparado una alerta. unit_id es obligatorio; signal admite varias "
            "separadas por coma (por defecto grafica una señal disponible); days o "
            "start_date/end_date acotan el periodo (máximo 90 días)"
        ),
        # The raw weekly source this reads (telemetry/silver/.../Telemetry_Wide_With_States)
        # is a partitioned directory, not a single file, so it is not in the DATASETS
        # registry validate_client checks. telemetry_classified is a same-pipeline proxy
        # for "this client has telemetry data" gating list_charts, not what this chart reads.
        datasets=("telemetry_classified",),
        parameters=("unit_id", "signal", "days", "start_date", "end_date"),
        builder=DashboardChartRegistry._telemetry_signal_trend,
        chart_type="line",
        tags=("telemetria", "senales", "tendencia"),
    ),
)

_DEFINITION_MAP = {definition.chart_id: definition for definition in CHART_DEFINITIONS}
