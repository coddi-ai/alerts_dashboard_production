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
    build_stacked_bar,
    build_status_donut,
)


# Parameters a caller may supply, with their coercion. Anything else is rejected.
ALLOWED_PARAMETERS: dict[str, type] = {"unit_id": str, "top_n": int, "days": int}


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
            summary={"chart_id": definition.chart_id, **summary},
        )

    @staticmethod
    def _describe(definition: ChartDefinition, summary: dict[str, Any]) -> str:
        parts = [definition.description]
        if summary.get("period"):
            parts.append(str(summary["period"]))
        by_status = summary.get("by_status")
        if isinstance(by_status, dict) and by_status:
            parts.append(
                "distribución: "
                + ", ".join(f"{label} ({value})" for label, value in by_status.items())
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
)

_DEFINITION_MAP = {definition.chart_id: definition for definition in CHART_DEFINITIONS}
