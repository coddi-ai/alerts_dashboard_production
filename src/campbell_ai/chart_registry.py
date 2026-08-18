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
    build_gauge,
    build_heatmap,
    build_histogram,
    build_radar,
    build_stacked_bar,
    build_status_donut,
    build_time_series,
    build_treemap,
)
from src.campbell_ai.oil_limits import (
    OIL_GROUP_ORDER,
    build_four_limit_radar,
    build_oil_time_series_grid,
    classify_four_limit,
    four_limit_for_essay,
    normalize_four_limit,
    oil_element_groups,
)
from src.campbell_ai.signals import (
    build_state_signal_panels,
    build_alert_context_panels,
    companions_for,
    signal_display_label,
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
    # The kind of question this chart answers, in the user's words rather than the dataset's.
    # `description` says what the figure *is*; this says when to reach for it. Surfaced by
    # `list_charts`, which is what the agent reads before choosing, so a chart with a good
    # `use_when` gets picked for the questions it serves instead of losing to a generic
    # ad-hoc bar chart.
    use_when: str = ""
    # Where the same information lives in full inside the dashboard. The answer cites it so a
    # user who wants more than one figure gets a destination instead of "mira el dashboard".
    # Must match a real route in dashboard/services_registry.py::NAV_PATHS.
    dashboard_route: str = ""
    dashboard_section: str = ""


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

    def _oil_essay_group_radar(self, client: str, params: dict[str, Any]):
        """Oil essays of one component, split by element group, against LSM/LSC.

        Reproduces the dashboard's own oil radar (Monitoreo > Aceite > Detalle) rather than
        inventing a second look for the same information, so a user who sees this in the chat
        and then opens the dashboard recognises it.

        Two things it does that the retired `oil_essay_radar` could not:

        - **It reads the four-limit contract** (LIC/LIM/LSM/LSC), which is what the dashboard
          classifies against. The old one used the legacy three-threshold file, so it could
          not speak the marginal/condenatorio vocabulary the rest of the product uses.
        - **It splits by element group.** Iron and silicon on one axis set say nothing:
          wear metals, contaminants and additives are read separately because they answer
          different questions (is it wearing / is dirt getting in / is the oil spent).

        The 0-100 normalization puts every threshold at a fixed radius (LIC 20, LIM 40,
        LSM 60, LSC 80) so the rings are circles. Normalizing by a single threshold instead
        cannot work here: measured across CDA, LSC/LSM ranges from 1.0 to 8.5, so the outer
        ring would be a jagged shape rather than a reference.
        """
        unit_id = str(params.get("unit_id") or "").strip()
        if not unit_id:
            raise CampbellDataError(
                'oil_essay_group_radar requiere unit_id (por ejemplo unit_id="T_15")'
            )
        requested_component = str(params.get("component") or "").strip()

        samples = self.repository.load("oil_classified", client)
        unit_col = self._column(samples, ("unitId", "unit_id", "UnitId"))
        component_col = self._column(samples, ("componentName",))
        date_col = self._column(samples, ("sampleDate", "reportDate"))
        scoped = self.repository._filter_unit(samples, unit_col, unit_id)
        if requested_component:
            scoped = self.repository._filter_contains(
                scoped, component_col, requested_component
            )
        if scoped.empty:
            raise CampbellDataError(
                f"Sin muestras de aceite para {unit_id}"
                + (f" y componente {requested_component}" if requested_component else "")
            )

        scoped = scoped.assign(
            __date=pd.to_datetime(scoped[date_col], errors="coerce")
        ).sort_values("__date")
        latest = scoped.iloc[-1]
        component = str(latest[component_col])

        limits = self.repository.four_limit_thresholds(
            client,
            machine=str(latest.get("machineName") or ""),
            component=str(latest.get("componentNameNormalized") or component),
        )
        if not limits:
            raise CampbellDataError(
                f"No hay límites de cuatro niveles para el componente {component}"
            )

        hour_range = str(latest.get("oilHourRange") or "UNKNOWN")
        groups = oil_element_groups()
        status = str(latest.get("report_status") or "Normal")

        rendered: list[str] = []
        skipped: dict[str, int] = {}
        figures: dict[str, go.Figure] = {}
        detail: dict[str, Any] = {}

        for group in OIL_GROUP_ORDER:
            axes, values, raw, statuses = [], [], [], []
            has_lower = False
            for essay in sorted(e for e, g in groups.items() if g == group):
                if essay not in latest.index or pd.isna(latest[essay]):
                    continue
                thresholds = four_limit_for_essay(limits, essay, hour_range)
                if thresholds is None:
                    continue
                lic, lim = thresholds.get("LIC"), thresholds.get("LIM")
                lsm, lsc = thresholds.get("LSM", 0), thresholds.get("LSC", 0)
                has_lower = has_lower or (lic is not None and lim is not None)
                measured = float(latest[essay])
                axes.append(essay)
                raw.append(round(measured, 3))
                values.append(normalize_four_limit(measured, lic, lim, lsm, lsc))
                statuses.append(classify_four_limit(measured, lic, lim, lsm, lsc))
                detail[essay] = {
                    "group": group,
                    "value": round(measured, 3),
                    "LIC": lic,
                    "LIM": lim,
                    "LSM": lsm,
                    "LSC": lsc,
                    "status": statuses[-1],
                }
            # Two axes make a line, not a radar; saying so beats rendering something
            # unreadable and letting the agent describe it as evidence.
            if len(axes) < 3:
                if axes:
                    skipped[group] = len(axes)
                continue
            figures[group] = build_four_limit_radar(
                axes, values, raw, statuses, group, has_lower, status
            )
            rendered.append(group)

        if not figures:
            raise CampbellDataError(
                f"Ningún grupo de elementos alcanza 3 ensayos con límite para {component}"
            )

        primary = next(g for g in OIL_GROUP_ORDER if g in figures)
        figure = figures[primary]
        sample_date = latest["__date"]
        return figure, {
            "unit_id": unit_id,
            "component": component,
            "group": primary,
            "groups_rendered": rendered,
            "groups_skipped_few_essays": skipped,
            "sample_date": (
                str(sample_date.date()) if pd.notna(sample_date) else None
            ),
            "report_status": status,
            "oil_hour_range": hour_range,
            "essays": detail,
        }

    def _oil_history_panels(self, client: str, params: dict[str, Any]):
        """Oil history of one component as paired panels, with limits.

        The radar answers "how is this sample"; this answers "how did it get here", which is
        the question that follows it almost every time. Same pairs the dashboard uses, so a
        user who asks in the chat and then opens Monitoreo > Aceite sees the same panels.
        """
        unit_id = str(params.get("unit_id") or "").strip()
        if not unit_id:
            raise CampbellDataError(
                'oil_history_panels requiere unit_id (por ejemplo unit_id="T_15")'
            )
        requested_component = str(params.get("component") or "").strip()

        samples = self.repository.load("oil_classified", client)
        unit_col = self._column(samples, ("unitId", "unit_id", "UnitId"))
        component_col = self._column(samples, ("componentName",))
        date_col = self._column(samples, ("sampleDate", "reportDate"))
        scoped = self.repository._filter_unit(samples, unit_col, unit_id)
        if requested_component:
            scoped = self.repository._filter_contains(
                scoped, component_col, requested_component
            )
        if scoped.empty:
            raise CampbellDataError(
                f"Sin muestras de aceite para {unit_id}"
                + (f" y componente {requested_component}" if requested_component else "")
            )

        # Without an explicit component the newest sample decides, so the panels describe one
        # component rather than silently interleaving several histories on the same axes.
        scoped = scoped.assign(sampleDate=pd.to_datetime(scoped[date_col], errors="coerce"))
        component = str(scoped.sort_values("sampleDate").iloc[-1][component_col])
        history = scoped[scoped[component_col].astype(str) == component].sort_values(
            "sampleDate"
        )

        days = self._clamp(params.get("days"), 0, 0, 3650)
        if days:
            cutoff = history["sampleDate"].max() - pd.Timedelta(days=days)
            windowed = history[history["sampleDate"] >= cutoff]
            if len(windowed) >= 2:
                history = windowed

        latest = history.iloc[-1]
        limits = self.repository.four_limit_thresholds(
            client,
            machine=str(latest.get("machineName") or ""),
            component=str(latest.get("componentNameNormalized") or component),
        )
        figure, detail = build_oil_time_series_grid(
            history,
            limits,
            str(latest.get("oilHourRange") or "UNKNOWN"),
            oil_element_groups(),
            title=f"Historial de aceite · {unit_id} · {component}",
        )
        if not detail["panels"]:
            raise CampbellDataError(
                f"Sin ensayos con historial para {unit_id} y componente {component}"
            )
        return figure, {
            "unit_id": unit_id,
            "component": component,
            "samples": int(len(history)),
            "period": (
                f"{history['sampleDate'].min().date()} a {history['sampleDate'].max().date()}"
                if history["sampleDate"].notna().any()
                else ""
            ),
            "panels": {name: essays for name, essays in detail["panels"].items() if essays},
            "limits_drawn": detail["limits"],
            "report_status": str(latest.get("report_status") or ""),
        }

    def _alert_context_signals(self, client: str, params: dict[str, Any]):
        """The signal that fired an alert plus the ones that explain it, sharing a time axis.

        `alert_sensor_trend` plots one signal. Reading a trigger alone is how a single high
        value becomes the wrong work order: coolant temperature means one thing next to a
        falling oil pressure and another next to a normal one. The companions come from
        `TRIGGER_COMPANION_SIGNALS`, which encodes that pairing.
        """
        unit_id = str(params.get("unit_id") or "").strip()
        if not unit_id:
            raise CampbellDataError(
                'alert_context_signals requiere unit_id (por ejemplo unit_id="T_18")'
            )

        frame = self.repository.load("alerts_detail", client)
        unit_col = self._column(frame, ("Unit", "UnitId", "unit_id"))
        scoped = self.repository._filter_unit(frame, unit_col, unit_id)
        if scoped.empty:
            raise CampbellDataError(f"Sin detalle de alertas para {unit_id}")

        alert_id = str(params.get("alert_id") or "").strip()
        if alert_id:
            scoped = scoped[scoped["AlertID"].astype(str) == alert_id]
            if scoped.empty:
                raise CampbellDataError(
                    f"La alerta {alert_id} no existe para {unit_id}"
                )
        else:
            # Newest alert of the unit, so "¿por qué se alertó este equipo?" resolves without
            # the user having to know an id.
            scoped = scoped.assign(
                __start=pd.to_datetime(scoped["Alert_TimeStart"], errors="coerce")
            )
            alert_id = str(scoped.sort_values("__start").iloc[-1]["AlertID"])
            scoped = scoped[scoped["AlertID"].astype(str) == alert_id]

        trigger = str(params.get("signal") or scoped.iloc[0].get("Trigger") or "").strip()
        if not trigger:
            raise CampbellDataError(
                f"La alerta {alert_id} no declara señal disparadora"
            )

        scoped = scoped.assign(
            __time=pd.to_datetime(scoped["TimeStart"], errors="coerce")
        ).sort_values("__time")

        # Pedidas todas las del diccionario. Antes se filtraba por existencia de columna, que
        # no es lo mismo que tener lecturas: una columna presente y vacia producia un panel en
        # blanco. El builder descarta las que no tienen valores y devuelve cuales fueron.
        wanted = companions_for(trigger)
        figure, detail = build_alert_context_panels(scoped, wanted, trigger, alert_id, unit_id)
        present = detail["signals_plotted"]
        return figure, {
            "unit_id": unit_id,
            "alert_id": alert_id,
            "trigger": trigger,
            "trigger_label": signal_display_label(trigger),
            "signals_plotted": present,
            "companions_missing": [s for s in wanted if s not in present],
            # Pedidas por el diccionario pero sin una sola lectura en esta alerta. Es un hecho
            # sobre el equipo, no un fallo: el agente puede decirlo en vez de omitirlo.
            "signals_without_values": detail["signals_without_values"],
            "alert_time": detail["alert_time"],
            "limits": detail["limits"],
            # Which limits move inside the window instead of holding one value. It changes how
            # the chart is read: a crossing against a moving threshold is not the same claim as
            # one against a fixed number, and the agent has to be able to say which it saw.
            "limits_vary": detail["limits_vary"],
            # The operating state behind the line colour, and how the window splits between
            # states. A reading taken almost entirely at idle deserves a different sentence
            # from the same reading under load, and this is the number that decides it.
            "state_column": detail["state_column"],
            "state_share_pct": detail["state_share_pct"],
            "samples": int(len(scoped)),
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
        trigger = payload.get("trigger") or ""
        panels = [
            {
                **panel,
                "label": signal_display_label(panel["signal"]),
                # La señal que gatillo la alerta se dibuja en su propia familia de color, para
                # que se distinga del resto sin tener que leer el titulo del panel.
                "highlight": panel["signal"] == trigger,
            }
            for panel in payload["panels"]
        ]
        if not panels:
            raise CampbellDataError(
                "Ninguna de las señales solicitadas tiene valores capturados en esta "
                f"alerta. Disponibles: {', '.join(payload['signals_available'])}"
            )
        window = payload["window"]
        figure = build_state_signal_panels(
            panels,
            title=(
                f"Señales de la alerta {payload['alert_id']} · {payload['unit_id']}"
            ),
            subtitle=f"{str(window['start'])[:16]} a {str(window['end'])[:16]}",
            alert_time=payload.get("alert_time") or None,
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
            {**panel, "label": signal_display_label(panel["signal"])}
            for panel in payload["panels"]
        ]
        window = payload["window"]
        figure = build_state_signal_panels(
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
            # Señales que se grafican sin umbral porque no hay uno reproducible para ellas.
            # El agente tiene que poder decirlo: una serie sin límite no es una serie dentro
            # de rango.
            "signals_without_limits": payload.get("signals_without_limits", []),
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
                    # What the agent reads to choose. Without these two it can only match on
                    # the title, which is why a good chart used to lose to a generic bar.
                    "use_when": definition.use_when,
                    "dashboard_section": definition.dashboard_section,
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
            summary={
                "chart_id": definition.chart_id,
                # Travels with the artifact so the agent composing the answer can point the
                # user at the dashboard section holding the full view. A chart in the chat
                # answers one question; the section answers the next three.
                "dashboard_section": definition.dashboard_section,
                "dashboard_route": definition.dashboard_route,
                **summary,
            },
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
        chart_id="oil_history_panels",
        caption="Historial de ensayos de aceite del componente, por pares de lectura",
        title="Historial de aceite por panel",
        domain="aceite",
        description=(
            "Series temporales de los ensayos de un componente, agrupadas en los pares que se "
            "leen juntos (hierro con PQ, silicio con aluminio, sodio con potasio), con los "
            "limites de cada ensayo. Reproduce la grilla del dashboard."
        ),
        datasets=("oil_classified",),
        parameters=("unit_id", "component", "days"),
        builder=DashboardChartRegistry._oil_history_panels,
        chart_type="line",
        tags=("aceite", "historial", "tendencia"),
        use_when=(
            "El usuario pregunta como viene evolucionando el aceite de un componente, si un "
            "elemento viene subiendo, desde cuando, o pide el historial o la tendencia de las "
            "muestras. Responde 'como llego hasta aca', que es la pregunta que sigue al radar."
        ),
        dashboard_route="/monitoring/oil",
        dashboard_section="Monitoreo > Aceite > Detalle",
    ),
    ChartDefinition(
        chart_id="alert_context_signals",
        caption="Senal que gatillo la alerta junto a las que la explican",
        title="Contexto de una alerta",
        domain="alertas",
        description=(
            "La senal disparadora de una alerta y sus senales acompanantes, en paneles con eje "
            "de tiempo compartido y el limite de cada una."
        ),
        datasets=("alerts_detail",),
        parameters=("unit_id", "alert_id", "signal"),
        builder=DashboardChartRegistry._alert_context_signals,
        chart_type="line",
        tags=("alertas", "evidencia", "senales"),
        use_when=(
            "El usuario pregunta por que se gatillo una alerta, que la explica, si fue real o "
            "un sensor, o pide el contexto de una alerta. Preferilo sobre alert_sensor_trend "
            "cuando la pregunta sea de diagnostico y no solo de ver una senal: agrega las "
            "senales que permiten confirmar o descartar la causa."
        ),
        dashboard_route="/monitoring/alerts",
        dashboard_section="Monitoreo > Alertas > Detalle",
    ),
    ChartDefinition(
        chart_id="oil_essay_group_radar",
        caption="Ensayos de aceite del componente contra sus limites de cuatro niveles",
        title="Condicion tribologica por grupo de elementos",
        domain="aceite",
        description=(
            "Radar de los ensayos de una muestra contra LSM y LSC, separado por grupo de "
            "elementos (desgaste, contaminante, aditivo). Reproduce el radar del dashboard."
        ),
        datasets=("oil_classified",),
        parameters=("unit_id", "component"),
        builder=DashboardChartRegistry._oil_essay_group_radar,
        chart_type="radar",
        tags=("aceite", "componentes", "limites"),
        use_when=(
            "El usuario pregunta por la condicion tribologica de un componente: que elementos "
            "estan fuera de limite, si el desgaste viene de contaminacion o del aditivo, o pide "
            "'el radar' de una muestra de aceite. Separa desgaste, contaminante y aditivo, que "
            "es como se lee un informe de aceite."
        ),
        dashboard_route="/monitoring/oil",
        dashboard_section="Monitoreo > Aceite > Detalle",
    ),
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
        use_when=(
            "El usuario pregunta cómo está la flota en general por aceite, cuántos equipos hay en cada estado, o pide un panorama tribológico sin nombrar un equipo."
        ),
        dashboard_route="/monitoring/oil",
        dashboard_section="Monitoreo > Aceite",
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
        use_when=(
            "El usuario pregunta por el estado general de la flota según sensores, o cuántos equipos están anormales en la última semana evaluada."
        ),
        dashboard_route="/monitoring/telemetry",
        dashboard_section="Monitoreo > Telemetría",
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
        use_when=(
            "El usuario pregunta qué componentes están peor por telemetría, o dónde se concentran los problemas a nivel de componente."
        ),
        dashboard_route="/monitoring/telemetry",
        dashboard_section="Monitoreo > Telemetría",
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
        use_when=(
            "El usuario pregunta qué componentes están peor por análisis de aceite, o dónde se concentran las muestras anormales."
        ),
        dashboard_route="/monitoring/oil",
        dashboard_section="Monitoreo > Aceite",
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
        use_when=(
            "El usuario pregunta qué equipos tienen más alertas, cuáles son los más problemáticos, o pide priorizar por cantidad de alertas."
        ),
        dashboard_route="/monitoring/alerts",
        dashboard_section="Monitoreo > Alertas",
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
        use_when=(
            "El usuario pregunta qué equipos tienen mayor riesgo de falla de motor, o pide priorizar por riesgo predictivo en vez de por alertas ya ocurridas."
        ),
        dashboard_route="/predictive/motor",
        dashboard_section="Predictivo > Motor",
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
        use_when=(
            "El usuario pregunta si las alertas suben o bajan, cómo evolucionaron en el tiempo, o pide comparar meses."
        ),
        dashboard_route="/monitoring/alerts",
        dashboard_section="Monitoreo > Alertas",
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
        use_when=(
            "El usuario pregunta qué está gatillando las alertas, qué variable predomina, o pide la composición por tipo de disparador."
        ),
        dashboard_route="/monitoring/alerts",
        dashboard_section="Monitoreo > Alertas",
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
        use_when=(
            "El usuario quiere ver de una sola vez qué equipo y qué componente están comprometidos, o pide un cruce equipo por componente."
        ),
        dashboard_route="/monitoring/telemetry",
        dashboard_section="Monitoreo > Telemetría",
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
        use_when=(
            "El usuario pregunta por qué se gatilló una alerta concreta, qué pasó con la señal, o si el valor superó su límite. Es la evidencia de una alerta puntual."
        ),
        dashboard_route="/monitoring/alerts",
        dashboard_section="Monitoreo > Alertas > Detalle",
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
        use_when=(
            "El usuario pide la serie de una señal de un equipo sin referirse a una alerta, o quiere ver el comportamiento continuo de un sensor en un período."
        ),
        dashboard_route="/monitoring/telemetry",
        dashboard_section="Monitoreo > Telemetría > Detalle",
    ),
)

_DEFINITION_MAP = {definition.chart_id: definition for definition in CHART_DEFINITIONS}
