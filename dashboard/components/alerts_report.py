"""Presentation view models for the Alerts report.

The alert pipeline already materializes the alert, trigger, AI and evidence
fields. This module only normalizes those fields for a consistent report UI;
it does not create a new severity score or diagnosis.
"""

import ast
from typing import Any, Iterable, Optional

import pandas as pd

from dashboard.components.alerts_charts import FEATURE_NAMES_ES
from dashboard.components.alerts_tables import parse_ia_message_sections


SYSTEM_TRANSLATION = {
    "Direccion": "Dirección",
    "Dirección": "Dirección",
    "Tren de Fuerza": "Tren de fuerza",
    "Motor": "Motor",
    "motor": "Motor",
    "Frenos": "Frenos",
}

SOURCE_TRANSLATION = {
    "Telemetria": "Telemetría",
    "Telemetría": "Telemetría",
    "Tribologia": "Tribología",
    "Tribología": "Tribología",
    "Mixto": "Mixto",
}

COMPONENT_TRANSLATION = {
    "engine": "Motor",
    "post_engine": "Posterior al motor",
    "rifle": "Conducto principal de aceite",
    "crankcase": "Cárter",
    "lubrication": "Lubricación",
}


def translate_alert_system(value: Any) -> str:
    return SYSTEM_TRANSLATION.get(str(value), str(value or "Sin sistema"))


def translate_alert_source(value: Any) -> str:
    return SOURCE_TRANSLATION.get(str(value), str(value or "Sin fuente"))


def translate_alert_component(value: Any) -> str:
    key = str(value or "").strip()
    return COMPONENT_TRANSLATION.get(key, key or "Sin componente")


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
        frame["Timestamp"] = pd.to_datetime(frame["Timestamp"], errors="coerce")
    frame["system_display"] = frame.get("sistema", "").map(translate_alert_system)
    frame["source_display"] = frame.get("Trigger_type", "").map(translate_alert_source)
    frame["component_display"] = frame.get("componente", "").map(translate_alert_component)
    frame["signal_display"] = frame.get("Trigger_Var", "").map(_signal_labels)
    sections = frame.get("mensaje_ia", pd.Series("", index=frame.index)).map(_message_sections)
    frame["diagnosis_display"] = sections.map(lambda item: item.get("diagnostico") or "Sin diagnóstico IA disponible")
    frame["cause_display"] = sections.map(lambda item: item.get("causa_probable") or "Sin causa probable registrada")
    frame["action_display"] = sections.map(lambda item: item.get("acciones") or "Sin acción recomendada registrada")
    frame["evidence_display"] = frame.apply(_evidence_label, axis=1)
    frame["date_display"] = frame["Timestamp"].dt.strftime("%d/%m/%Y %H:%M") if "Timestamp" in frame.columns else "-"
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
        frame = frame[frame["Timestamp"] >= pd.to_datetime(start_date)]
    if end_date and "Timestamp" in frame.columns:
        frame = frame[frame["Timestamp"] < pd.to_datetime(end_date) + pd.Timedelta(days=1)]
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
        "mixed": int((frame["source_display"] == "Mixto").sum()),
        "latest": frame["Timestamp"].max(),
    }
