"""Presentation view models for the Alerts report.

The alert pipeline already materializes the alert, trigger, AI and evidence
fields. This module only normalizes those fields for a consistent report UI;
it does not create a new severity score or diagnosis.
"""

import ast
from typing import Any, Iterable, Optional

import pandas as pd

from dashboard.components.alerts_charts import FEATURE_NAMES_ES, translate_system_label
from dashboard.components.labels import translate_component_label, source_style
from dashboard.components.alerts_tables import parse_ia_message_sections
from src.utils.date_utils import format_local, to_utc_naive
from src.utils.logger import get_logger

logger = get_logger(__name__)


def translate_alert_system(value: Any) -> str:
    return translate_system_label(value)


def translate_alert_source(value: Any) -> str:
    return source_style(value)[0]


def translate_alert_component(value: Any) -> str:
    return translate_component_label(value)


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "si", "sí"}
    return bool(value) if pd.notna(value) else False


def _signal_labels(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "Sin señal registrada"
    values = value
    if isinstance(value, str):
        try:
            values = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            values = [value]
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    labels = [FEATURE_NAMES_ES.get(str(item), str(item)) for item in values if str(item).strip()]
    return ", ".join(dict.fromkeys(labels)) or "Sin señal registrada"


def _message_sections(value: Any) -> dict:
    return parse_ia_message_sections("" if value is None or pd.isna(value) else str(value))


def _evidence_label(row: pd.Series) -> str:
    telemetry = _bool(row.get("has_telemetry"))
    tribology = _bool(row.get("has_tribology"))
    if telemetry and tribology:
        return "Telemetría + Tribología"
    if telemetry:
        return "Telemetría"
    if tribology:
        return "Tribología"
    return "Sin evidencia"


def prepare_alert_rows(alerts_df: pd.DataFrame) -> pd.DataFrame:
    """Return a display-ready frame while preserving original identifiers."""
    if alerts_df is None or alerts_df.empty:
        return pd.DataFrame()
    frame = alerts_df.copy()
    if "Timestamp" in frame.columns:
        # W34-06: normalize through the same single entry point the loaders
        # use, instead of a bare pd.to_datetime(errors="coerce"). That used to
        # leave a raw offset-aware string (e.g. Capstone's "-04:00" ISO
        # timestamps, when this function runs on data that hasn't gone
        # through load_alerts_data's own normalization yet) as a
        # timezone-AWARE Timestamp rather than the UTC-naive form every
        # comparison downstream expects. Idempotent on data that is already
        # UTC-naive — calling it twice does not shift the values again.
        frame["Timestamp"] = to_utc_naive(frame["Timestamp"])
    frame["system_display"] = frame.get("sistema", "").map(translate_alert_system)
    frame["source_display"] = frame.get("Trigger_type", "").map(translate_alert_source)
    frame["component_display"] = frame.get("componente", "").map(translate_alert_component)
    frame["signal_display"] = frame.get("Trigger_Var", "").map(_signal_labels)
    sections = frame.get("mensaje_ia", pd.Series("", index=frame.index)).map(_message_sections)
    frame["diagnosis_display"] = sections.map(lambda item: item.get("diagnostico") or "Sin diagnóstico IA disponible")
    frame["cause_display"] = sections.map(lambda item: item.get("causa_probable") or "Sin causa probable registrada")
    frame["action_display"] = sections.map(lambda item: item.get("acciones") or "Sin acción recomendada registrada")
    frame["evidence_display"] = frame.apply(_evidence_label, axis=1)
    # W34-06: local wall-clock time, not the internal UTC-naive value — this
    # is the instant every surface (table, header, chart, dropdown) must agree on.
    frame["date_display"] = format_local(frame["Timestamp"]) if "Timestamp" in frame.columns else "-"
    return frame


def filter_alert_rows(
    alerts_df: pd.DataFrame,
    unit: Optional[Iterable[str]] = None,
    system: Optional[Iterable[str]] = None,
    source: Optional[Iterable[str]] = None,
    evidence: Optional[Iterable[str]] = None,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
) -> pd.DataFrame:
    """Apply report filters to existing alert records."""
    frame = prepare_alert_rows(alerts_df)
    if frame.empty:
        return frame
    if unit:
        frame = frame[frame["UnitId"].isin(list(unit))]
    if system:
        frame = frame[frame["system_display"].isin(list(system))]
    if source:
        frame = frame[frame["source_display"].isin(list(source))]
    if evidence:
        frame = frame[frame["evidence_display"].isin(list(evidence))]
    if start_date and "Timestamp" in frame.columns:
        # W34-06 (quality-review follow-up): start_date/end_date are Chile
        # calendar days from the date-range picker; Timestamp is already
        # UTC-naive (prepare_alert_rows), so the boundary must go through the
        # same to_utc_naive conversion the rest of this tab uses, not a bare
        # pd.to_datetime — otherwise this filter reads the wrong real-world
        # day by the UTC/Chile offset, the exact defect W34-06 fixed elsewhere.
        # Chile's own DST transition lands on local midnight, so a boundary
        # date can itself be nonexistent/ambiguous — to_utc_naive returns NaT
        # for that instead of raising; treat it the same as "no lower bound"
        # rather than let a NaT comparison silently empty the whole result.
        start_utc = to_utc_naive(pd.Timestamp(start_date), source_tz="America/Santiago")
        if pd.isna(start_utc):
            logger.warning(f"Fecha desde cae en una transición de horario de verano, ignorando filtro: {start_date!r}")
        else:
            frame = frame[frame["Timestamp"] >= start_utc]
    if end_date and "Timestamp" in frame.columns:
        end_utc = to_utc_naive(pd.Timestamp(end_date), source_tz="America/Santiago")
        if pd.isna(end_utc):
            logger.warning(f"Fecha hasta cae en una transición de horario de verano, ignorando filtro: {end_date!r}")
        else:
            frame = frame[frame["Timestamp"] < end_utc + pd.Timedelta(days=1)]
    return frame.sort_values("Timestamp", ascending=False, na_position="last")


def alert_summary(alerts_df: pd.DataFrame) -> dict:
    frame = prepare_alert_rows(alerts_df)
    if frame.empty:
        return {"total": 0, "units": 0, "telemetry": 0, "tribology": 0, "mixed": 0, "latest": None}
    return {
        "total": int(len(frame)),
        "units": int(frame["UnitId"].nunique()),
        "telemetry": int(frame["has_telemetry"].map(_bool).sum()),
        "tribology": int(frame["has_tribology"].map(_bool).sum()),
        # W34-04: compare the raw Trigger_type value, not the translated
        # source_display label — a future label change (the "Mixto" text is
        # provisional) must not silently change what this KPI counts.
        "mixed": int((frame.get("Trigger_type", "") == "Mixto").sum()),
        "latest": frame["Timestamp"].max(),
    }
