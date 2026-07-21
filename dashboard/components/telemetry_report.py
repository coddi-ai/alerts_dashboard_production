"""Presentation view models for the telemetry reportability views.

The telemetry pipeline already produces the health, deviation, event, trend and
AI datasets needed by the dashboard.  This module only joins and orders those
results for display; it does not recalculate health scores or diagnostics.
"""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Optional

import pandas as pd
import yaml

from src.data.loaders import (
    load_telemetry_ai_comments,
    load_telemetry_deviation_results,
    load_telemetry_events,
    load_telemetry_limits,
    load_telemetry_manifest,
    load_telemetry_system_health,
    load_telemetry_trends,
    load_telemetry_unit_health,
)
from dashboard.components.telemetry_charts import load_signal_registry, translate_signal, translate_system, translate_trend


@dataclass(frozen=True)
class TelemetrySnapshot:
    """Latest materialized telemetry results for one client/evaluation."""

    client: str
    cache_key: str
    manifest: Dict[str, Any]
    unit_health: pd.DataFrame
    system_health: pd.DataFrame
    deviation: pd.DataFrame
    events: pd.DataFrame
    trends: pd.DataFrame
    limits: pd.DataFrame
    unit_comments: pd.DataFrame
    system_comments: pd.DataFrame
    signal_comments: pd.DataFrame
    signal_registry: Dict[str, str]
    signal_metadata: Dict[str, Dict[str, Any]]
    equipment_models: Dict[str, str]


def _snapshot_copy(df: pd.DataFrame) -> pd.DataFrame:
    """Return a defensive copy while preserving empty frames."""
    return df.copy(deep=True) if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _load_signal_metadata(client: str) -> Dict[str, Dict[str, Any]]:
    path = Path(f"data/telemetry/config/{client.lower()}/signal_registry.yaml")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return {
            item.get("name"): item
            for item in payload.get("signals", [])
            if item.get("name")
        }
    except (OSError, yaml.YAMLError):
        return {}


def _load_equipment_models(client: str) -> Dict[str, str]:
    path = Path(f"data/telemetry/config/{client.lower()}/equipment_registry.yaml")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        return {
            item.get("name"): item.get("model", "N/D")
            for item in payload.get("equipments", [])
            if item.get("name")
        }
    except (OSError, yaml.YAMLError):
        return {}


def _manifest_cache_key(manifest: Dict[str, Any]) -> str:
    """Use the materialized execution identity to invalidate the snapshot."""
    if not manifest:
        return "missing"
    return "|".join(
        str(manifest.get(key, ""))
        for key in ("evaluation_year", "evaluation_week", "execution_timestamp", "baseline_version")
    )


@lru_cache(maxsize=8)
def _load_snapshot_cached(client: str, cache_key: str) -> TelemetrySnapshot:
    manifest = load_telemetry_manifest(client)
    return TelemetrySnapshot(
        client=client,
        cache_key=cache_key,
        manifest=manifest,
        unit_health=_snapshot_copy(load_telemetry_unit_health(client)),
        system_health=_snapshot_copy(load_telemetry_system_health(client)),
        deviation=_snapshot_copy(load_telemetry_deviation_results(client)),
        events=_snapshot_copy(load_telemetry_events(client)),
        trends=_snapshot_copy(load_telemetry_trends(client)),
        limits=_snapshot_copy(load_telemetry_limits(client)),
        unit_comments=_snapshot_copy(load_telemetry_ai_comments(client, "unit")),
        system_comments=_snapshot_copy(load_telemetry_ai_comments(client, "system")),
        signal_comments=_snapshot_copy(load_telemetry_ai_comments(client, "signal")),
        signal_registry=load_signal_registry(client),
        signal_metadata=_load_signal_metadata(client),
        equipment_models=_load_equipment_models(client),
    )


def load_telemetry_snapshot(client: str) -> TelemetrySnapshot:
    """Load the current materialized snapshot, cached by manifest identity."""
    normalized = (client or "").lower()
    manifest = load_telemetry_manifest(normalized)
    return _load_snapshot_cached(normalized, _manifest_cache_key(manifest))


def _latest_per_signal(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "signal" not in df.columns:
        return df.copy()
    result = df.copy()
    if {"year", "week"}.issubset(result.columns):
        result = result.sort_values(["year", "week"], ascending=False)
        result = result.drop_duplicates(subset=[c for c in ("unit", "system", "signal") if c in result.columns])
    return result


def filter_fleet_snapshot(
    snapshot: TelemetrySnapshot,
    model: Optional[str] = None,
    statuses: Optional[Iterable[str]] = None,
    systems: Optional[Iterable[str]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply presentation filters consistently to unit and system tables."""
    units = snapshot.unit_health.copy()
    systems_df = snapshot.system_health.copy()
    allowed_statuses = set(statuses or [])
    allowed_systems = set(systems or [])

    if model and model != "ALL":
        selected_units = [u for u, m in snapshot.equipment_models.items() if m == model]
        units = units[units.get("unit", pd.Series(dtype=str)).isin(selected_units)]
    if allowed_statuses and "overall_status" in units.columns:
        units = units[units["overall_status"].isin(allowed_statuses)]
    if allowed_systems and "system" in systems_df.columns:
        systems_df = systems_df[systems_df["system"].map(translate_system).isin(allowed_systems)]
    if "unit" in units.columns and "unit" in systems_df.columns:
        systems_df = systems_df[systems_df["unit"].isin(units["unit"].tolist())]
    return units, systems_df


def _text(row: Any, *fields: str) -> Optional[str]:
    if row is None:
        return None
    for field in fields:
        try:
            value = row.get(field, "")
        except AttributeError:
            value = ""
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value)
    return None


def client_facing_text(value: Any, signal_registry: Optional[Dict[str, str]] = None) -> str:
    """Hide internal score/confidence numbers from materialized IA text."""
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value)
    if not text.strip():
        return ""
    text = re.sub(
        r"\b(?:un|una)\s+puntaje\s+de\s+prioridad\s*(?:de|del|:)?\s*\d+(?:[.,]\d+)?",
        "una prioridad asignada", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bpuntaje\s+de\s+prioridad\s*(?:de|del|:)?\s*\d+(?:[.,]\d+)?",
        "prioridad asignada", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:puntaje\s+de\s+riesgo|puntaje\s+riesgo|risk\s+score)"
        r"\s*(?:de|del|:)?\s*\d+(?:[.,]\d+)?(?:\s*(?:/|sobre|de)\s*\d+(?:[.,]\d+)?)?",
        "nivel de riesgo", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\bscores?\s+de\s+riesgo\b[^.;]*?\d+(?:[.,]\d+)?(?:\s*(?:/|sobre|de)\s*\d+(?:[.,]\d+)?)?",
        "niveles de riesgo", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:riesgo|risk)\s+(?:constante\s+|alto\s+|elevado\s+|crítico\s+)?"
        r"(?:de|del|en)\s*\d+(?:[.,]\d+)?(?:\s*(?:/|sobre|de)\s*\d+(?:[.,]\d+)?)?",
        "riesgo elevado", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:confianza|confidence)\s*(?:(?:del|de)\s*)?\d+(?:[.,]\d+)?"
        r"(?:\s*(?:/|sobre)\s*\d+(?:[.,]\d+)?|\s*%)?"
        r"(?:\s*(?:y|a)\s*\d+(?:[.,]\d+)?\s*%)?",
        "evidencia disponible", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:criticidad|criticality)(?:\s+es|\s+de|\s*:)?\s*\d+",
        "criticidad definida por el análisis", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\briesgos?\s+(?:de\s+)?\d+(?:[.,]\d+)?(?:\s+y\s+\d+(?:[.,]\d+)?)+(?:\s+respectivamente)?",
        "niveles de riesgo", text, flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(?:oscila(?:ndo)?|varía)\s+entre\s+\d+(?:[.,]\d+)?\s*%?\s*(?:y|a)\s*\d+(?:[.,]\d+)?\s*%?",
        "se mantiene en un rango", text, flags=re.IGNORECASE,
    )
    text = re.sub(r"\s+([,.;])", r"\1", text)
    text = re.sub(r"\.{2,}", ".", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    text = re.sub(r"\b(?:confianza|confidence)\b", "consistencia de la evidencia", text, flags=re.IGNORECASE)
    # Algunos comentarios materializados conservan el nombre legible en inglés
    # aunque la tabla ya utilice la traducción del registro de señales.
    english_signal_aliases = {
        "Transmission Slip": "Deslizamiento de la transmisión",
    }
    for english_name, display_name in english_signal_aliases.items():
        text = re.sub(rf"\b{re.escape(english_name)}\b", display_name, text, flags=re.IGNORECASE)
    for raw, label in sorted((signal_registry or {}).items(), key=lambda item: len(str(item[0])), reverse=True):
        if raw and label and raw != label:
            text = re.sub(rf"\b{re.escape(str(raw))}\b", str(label), text)
    for raw_system, label in {
        "Engine": "Motor", "Transmission": "Transmisión", "Brakes": "Frenos", "Steering": "Dirección",
    }.items():
        text = re.sub(rf"\b{raw_system}\b", label, text)
    # Al traducir una referencia con formato "nombre (alias)" ambos lados
    # pueden quedar iguales; conservar una sola mención mejora la lectura.
    for label in set((signal_registry or {}).values()) | set(english_signal_aliases.values()):
        if label:
            text = text.replace(f"{label} ({label})", str(label))
    return text


def _comment_text(row: Any, signal_registry: Optional[Dict[str, str]], *fields: str) -> Optional[str]:
    value = _text(row, *fields)
    cleaned = client_facing_text(value, signal_registry)
    return cleaned or None


def _comment_row(df: pd.DataFrame, key: str, value: Any, **filters: Any) -> Optional[pd.Series]:
    if df.empty or key not in df.columns:
        return None
    rows = df[df[key] == value]
    for filter_key, filter_value in filters.items():
        if filter_key in rows.columns:
            rows = rows[rows[filter_key] == filter_value]
    return rows.iloc[0] if not rows.empty else None


def build_fleet_priority_rows(
    snapshot: TelemetrySnapshot,
    unit_health: Optional[pd.DataFrame] = None,
    system_health: Optional[pd.DataFrame] = None,
) -> list[dict]:
    """Build the executive priority table from existing health results."""
    units = (unit_health if unit_health is not None else snapshot.unit_health).copy()
    systems = (system_health if system_health is not None else snapshot.system_health).copy()
    if units.empty:
        return []

    systems = systems.copy()
    if not systems.empty and "system_score" in systems.columns:
        systems = systems.sort_values("system_score", ascending=False)
    rows = []
    deviation = _latest_per_signal(snapshot.deviation)
    for _, unit_row in units.sort_values("priority_score", ascending=False, na_position="last").iterrows():
        unit = unit_row.get("unit", "")
        unit_systems = systems[systems.get("unit", pd.Series(dtype=str)) == unit] if not systems.empty else pd.DataFrame()
        top_system = unit_systems.iloc[0] if not unit_systems.empty else None
        unit_dev = deviation[deviation.get("unit", pd.Series(dtype=str)) == unit] if not deviation.empty else pd.DataFrame()
        top_signal = None
        if top_system is not None and _text(top_system, "top_signal"):
            top_signal = _text(top_system, "top_signal")
        elif not unit_dev.empty and "risk_score" in unit_dev.columns:
            top_signal = unit_dev.sort_values("risk_score", ascending=False).iloc[0].get("signal")
        comment = _comment_row(snapshot.unit_comments, "unit", unit)
        rows.append({
            "unit": unit,
            "model": snapshot.equipment_models.get(unit, "N/D"),
            "overall_status": unit_row.get("overall_status", "InsufficientData"),
            "priority_score": round(float(unit_row.get("priority_score", 0) or 0), 1),
            "systems_in_alert": int((unit_row.get("n_anormal_systems", 0) or 0) + (unit_row.get("n_alerta_systems", 0) or 0)),
            "top_system": translate_system(top_system.get("system", "-")) if top_system is not None else "-",
            "top_system_raw": top_system.get("system", "") if top_system is not None else "",
            "top_system_status": top_system.get("system_status", "-") if top_system is not None else "-",
            "top_system_score": round(float(top_system.get("system_score", 0) or 0), 1) if top_system is not None else 0,
            "top_system_confidence": round(float(top_system.get("confidence", 0) or 0), 1) if top_system is not None else 0,
            "top_signal": top_signal or "-",
            "top_signal_display": snapshot.signal_registry.get(top_signal, translate_signal(top_signal or "-")),
            "urgency": _text(comment, "urgency") or "-",
            "description": _comment_text(comment, snapshot.signal_registry, "description", "comment") or client_facing_text(_text(unit_row, "executive_summary"), snapshot.signal_registry) or "Operando dentro de parámetros normales.",
            "explaining": _comment_text(comment, snapshot.signal_registry, "explaining"),
            "recommended_action": _comment_text(comment, snapshot.signal_registry, "recommended_action"),
        })
    return rows


def build_system_rows(snapshot: TelemetrySnapshot, unit: str) -> list[dict]:
    """Build system rows with existing score, confidence and signal evidence."""
    if snapshot.system_health.empty or "unit" not in snapshot.system_health.columns:
        return []
    systems = snapshot.system_health[snapshot.system_health["unit"] == unit].copy()
    if systems.empty:
        return []
    deviation = _latest_per_signal(snapshot.deviation)
    rows = []
    for _, row in systems.sort_values("system_score", ascending=False, na_position="last").iterrows():
        raw_system = row.get("system", "")
        system_dev = deviation[(deviation.get("unit", pd.Series(dtype=str)) == unit) & (deviation.get("system", pd.Series(dtype=str)) == raw_system)] if not deviation.empty else pd.DataFrame()
        alert_count = int(system_dev.get("status", pd.Series(dtype=str)).isin(["Alerta", "Anormal"]).sum()) if not system_dev.empty else 0
        comment = _comment_row(snapshot.system_comments, "system", raw_system, unit=unit)
        rows.append({
            "system": translate_system(raw_system),
            "system_raw": raw_system,
            "system_status": row.get("system_status", "InsufficientData"),
            "system_score": round(float(row.get("system_score", 0) or 0), 1),
            "confidence": round(float(row.get("confidence", 0) or 0), 1),
            "signals_in_alert": alert_count,
            "top_signal": _text(row, "top_signal") or "-",
            "top_signal_display": snapshot.signal_registry.get(_text(row, "top_signal"), translate_signal(_text(row, "top_signal") or "-")),
            "n_techniques_triggered": row.get("n_techniques_triggered", 0),
            "description": _comment_text(comment, snapshot.signal_registry, "description", "comment") or client_facing_text(_text(row, "explanation"), snapshot.signal_registry),
            "explaining": _comment_text(comment, snapshot.signal_registry, "explaining"),
            "recommended_action": _comment_text(comment, snapshot.signal_registry, "recommended_action"),
        })
    return rows


def build_signal_rows(snapshot: TelemetrySnapshot, unit: str, system: str) -> list[dict]:
    """Build signal rows with existing deviation, event and trend metrics."""
    if snapshot.deviation.empty:
        return []
    raw_system = next((key for key, value in {
        "Engine": "Motor", "Transmission": "Transmisión", "Brakes": "Frenos", "Steering": "Dirección"
    }.items() if value == system), system)
    dev = snapshot.deviation[(snapshot.deviation.get("unit", pd.Series(dtype=str)) == unit) & (snapshot.deviation.get("system", pd.Series(dtype=str)) == raw_system)].copy()
    dev = _latest_per_signal(dev)
    if dev.empty:
        return []
    events = snapshot.events.copy()
    feature_col = "feature" if "feature" in events.columns else "signal"
    trends = snapshot.trends.copy()
    rows = []
    for _, row in dev.sort_values("risk_score", ascending=False, na_position="last").iterrows():
        signal = row.get("signal", "")
        event_rows = events[(events.get("unit", pd.Series(dtype=str)) == unit) & (events.get(feature_col, pd.Series(dtype=str)) == signal)] if not events.empty else pd.DataFrame()
        trend_rows = trends[(trends.get("unit", pd.Series(dtype=str)) == unit) & (trends.get("signal", pd.Series(dtype=str)) == signal)] if not trends.empty else pd.DataFrame()
        if not trend_rows.empty and {"is_significant", "is_good_fit"}.issubset(trend_rows.columns):
            good_trends = trend_rows[(trend_rows["is_significant"] == True) & (trend_rows["is_good_fit"] == True)]
        else:
            good_trends = pd.DataFrame()
        best_trend = good_trends.sort_values("r2", ascending=False).iloc[0] if not good_trends.empty else None
        comment = _comment_row(snapshot.signal_comments, "signal", signal, unit=unit)
        rows.append({
            "signal": snapshot.signal_registry.get(signal, translate_signal(signal)),
            "signal_raw": signal,
            "status": row.get("status", "InsufficientData"),
            "risk_score": round(float(row.get("risk_score", 0) or 0), 1),
            "confidence_score": round(float(row.get("confidence_score", 0) or 0), 1),
            "abnormal_pct": round(float(row.get("abnormal_pct", 0) or 0), 2),
            "abnormal_pct_display": f"{float(row.get('abnormal_pct', 0) or 0):.2f}%",
            "total_minutes_evaluated": row.get("total_minutes_evaluated", 0),
            "total_events": int(event_rows["event_id"].nunique()) if not event_rows.empty and "event_id" in event_rows.columns else len(event_rows),
            "warnings": int((event_rows.get("event_type_weighted", pd.Series(dtype=str)) == "warning").sum()) if not event_rows.empty else 0,
            "longest_episode": int(event_rows.get("duration_minutes", pd.Series(dtype=float)).max()) if not event_rows.empty and event_rows.get("duration_minutes", pd.Series(dtype=float)).notna().any() else 0,
            "trend_detected": "Sí" if best_trend is not None else "No",
            "trend_direction": translate_trend(best_trend.get("trend_interpretation", "-")) if best_trend is not None else "-",
            "trend_formula": f"{float(best_trend.get('slope_per_day', 0)):+.2f}/día (R²={float(best_trend.get('r2', 0)):.2f})" if best_trend is not None else "-",
            "description": _comment_text(comment, snapshot.signal_registry, "description", "comment") or "Sin comentario IA disponible.",
            "explaining": _comment_text(comment, snapshot.signal_registry, "explaining"),
            "unit_label": snapshot.signal_metadata.get(signal, {}).get("unit", ""),
        })
    return rows


def format_urgency(value: Any) -> str:
    return {
        "routine": "Rutina",
        "monitor": "Monitorear",
        "schedule_inspection": "Programar inspección",
        "immediate": "Acción inmediata",
    }.get(str(value), str(value or "-"))
