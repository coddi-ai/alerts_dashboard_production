"""Unit tests for the telemetry reportability view models."""

import pandas as pd

from dashboard.components.telemetry_report import (
    TelemetrySnapshot,
    build_fleet_priority_rows,
    build_signal_rows,
    build_system_rows,
    client_facing_manifest,
    client_facing_text,
    filter_fleet_snapshot,
)
from dashboard.components.telemetry_charts import build_signal_timeseries_card, translate_signal, translate_trend


def test_client_labels_are_translated_without_changing_technical_names():
    assert translate_signal("EngCoolTemp") == "Temperatura del refrigerante del motor"
    assert translate_trend("worsening") == "En deterioro"


def test_client_facing_manifest_hides_pipeline_baseline_metadata():
    manifest = client_facing_manifest({
        "evaluation_week": 30,
        "evaluation_year": 2026,
        "execution_timestamp": "2026-07-20T04:50:39Z",
        "baseline_version": "computed",
    })
    assert manifest == {
        "evaluation_week": 30,
        "evaluation_year": 2026,
        "execution_timestamp": "2026-07-20T04:50:39Z",
    }
    assert "baseline_version" not in manifest


def test_client_facing_text_hides_internal_scores_and_translates_signal_aliases():
    text = client_facing_text(
        "La señal de Transmission Slip (TrnSlip) presenta un puntaje de riesgo de 100/100 y una confianza del 100%.",
        {"TrnSlip": "Deslizamiento de la transmisión"},
    )
    assert "100" not in text
    assert "confianza" not in text.lower()
    assert "puntaje de riesgo" not in text.lower()
    assert text == "La señal de Deslizamiento de la transmisión presenta un nivel de riesgo y una evidencia disponible."


def make_snapshot() -> TelemetrySnapshot:
    return TelemetrySnapshot(
        client="cda",
        cache_key="test",
        manifest={"evaluation_week": 26, "evaluation_year": 2026},
        unit_health=pd.DataFrame([
            {"unit": "T_01", "overall_status": "Anormal", "priority_score": 90, "n_anormal_systems": 1, "n_alerta_systems": 0},
            {"unit": "T_02", "overall_status": "InsufficientData", "priority_score": 0, "n_anormal_systems": 0, "n_alerta_systems": 0},
        ]),
        system_health=pd.DataFrame([
            {"unit": "T_01", "system": "Engine", "system_status": "Anormal", "system_score": 82, "confidence": 91, "top_signal": "EngCoolTemp", "n_techniques_triggered": 2},
        ]),
        deviation=pd.DataFrame([
            {"unit": "T_01", "system": "Engine", "signal": "EngCoolTemp", "status": "Anormal", "risk_score": 82, "confidence_score": 91, "abnormal_pct": 12.5, "total_minutes_evaluated": 100},
        ]),
        events=pd.DataFrame([
            {"unit": "T_01", "feature": "EngCoolTemp", "event_id": "e1", "event_type_weighted": "warning", "duration_minutes": 15},
        ]),
        trends=pd.DataFrame([
            {"unit": "T_01", "signal": "EngCoolTemp", "is_significant": True, "is_good_fit": True, "r2": .8, "slope_per_day": 1.2, "trend_interpretation": "worsening"},
        ]),
        limits=pd.DataFrame(),
        unit_comments=pd.DataFrame([
            {"unit": "T_01", "description": "Temperatura elevada", "explaining": "Persistencia", "urgency": "immediate", "recommended_action": "Inspeccionar"},
        ]),
        system_comments=pd.DataFrame([
            {"unit": "T_01", "system": "Engine", "description": "Motor afectado", "recommended_action": "Revisar refrigeración"},
        ]),
        signal_comments=pd.DataFrame([
            {"unit": "T_01", "signal": "EngCoolTemp", "description": "Temperatura elevada", "explaining": "Persistencia"},
        ]),
        signal_registry={"EngCoolTemp": "Temperatura refrigerante"},
        signal_metadata={"EngCoolTemp": {"unit": "°C"}},
        equipment_models={"T_01": "789C", "T_02": "789D"},
    )


def test_filters_keep_unit_and_system_frames_aligned():
    snapshot = make_snapshot()
    units, systems = filter_fleet_snapshot(snapshot, model="789C", statuses=["Anormal"])
    assert units["unit"].tolist() == ["T_01"]
    assert systems["unit"].tolist() == ["T_01"]


def test_priority_rows_use_existing_scores_and_actions():
    rows = build_fleet_priority_rows(make_snapshot())
    assert rows[0]["unit"] == "T_01"
    assert rows[0]["top_system"] == "Motor"
    assert rows[0]["top_signal_display"] == "Temperatura refrigerante"
    assert rows[0]["recommended_action"] == "Inspeccionar"


def test_detail_joins_feature_alias_and_significant_trend():
    snapshot = make_snapshot()
    systems = build_system_rows(snapshot, "T_01")
    signals = build_signal_rows(snapshot, "T_01", "Motor")
    assert systems[0]["signals_in_alert"] == 1
    assert signals[0]["total_events"] == 1
    assert signals[0]["trend_detected"] == "Sí"
    assert signals[0]["unit_label"] == "°C"


def test_signal_status_stays_aligned_with_current_ai_evaluation():
    snapshot = make_snapshot()
    system_health = snapshot.system_health.copy()
    system_health.loc[0, "evaluation_timestamp"] = "2026-07-22T02:19:57Z"
    signal_comments = snapshot.signal_comments.copy()
    signal_comments.loc[0, "status"] = "Alerta"
    signal_comments.loc[0, "evaluation_timestamp"] = "2026-07-22T02:20:21Z"
    snapshot = TelemetrySnapshot(**{
        **snapshot.__dict__,
        "system_health": system_health,
        "signal_comments": signal_comments,
    })

    systems = build_system_rows(snapshot, "T_01")
    signals = build_signal_rows(snapshot, "T_01", "Motor")
    assert systems[0]["signals_in_alert"] == 1
    assert signals[0]["status"] == "Alerta"


def test_stale_signal_comment_does_not_override_deviation_status():
    snapshot = make_snapshot()
    system_health = snapshot.system_health.copy()
    system_health.loc[0, "evaluation_timestamp"] = "2026-07-22T02:19:57Z"
    signal_comments = snapshot.signal_comments.copy()
    signal_comments.loc[0, "status"] = "Alerta"
    signal_comments.loc[0, "evaluation_timestamp"] = "2026-07-22T01:00:00Z"
    snapshot = TelemetrySnapshot(**{
        **snapshot.__dict__,
        "system_health": system_health,
        "signal_comments": signal_comments,
    })

    systems = build_system_rows(snapshot, "T_01")
    signals = build_signal_rows(snapshot, "T_01", "Motor")
    assert systems[0]["signals_in_alert"] == 1
    assert signals[0]["status"] == "Anormal"


def test_empty_frames_are_safe():
    snapshot = make_snapshot()
    snapshot = TelemetrySnapshot(**{**snapshot.__dict__, "unit_health": pd.DataFrame(), "system_health": pd.DataFrame()})
    assert build_fleet_priority_rows(snapshot) == []
    assert build_system_rows(snapshot, "T_01") == []


def test_signal_chart_highlights_events_and_starts_at_longest_episode():
    """Episodes fall inside the plotted samples, as the pipeline produces them.

    Markers annotate real samples, so an episode outside the series can have a
    background band but no marker; keeping the fixture coherent is what makes the
    'opens at the longest episode' contract meaningful.
    """
    raw = pd.DataFrame({
        "Fecha": pd.date_range("2026-06-01", periods=8, freq="h"),
        "EngCoolTemp": [10, 11, 12, 13, 14, 15, 16, 17],
    })
    events = pd.DataFrame([
        {
            "unit": "T_01", "feature": "EngCoolTemp",
            "start_time": "2026-06-01 01:00:00", "end_time": "2026-06-01 03:00:00",
            "duration_minutes": 120, "event_type_binary": "anomaly", "event_type_weighted": "warning",
        },
        {
            "unit": "T_01", "feature": "EngCoolTemp",
            "start_time": "2026-06-01 05:00:00", "end_time": "2026-06-01 05:30:00",
            "duration_minutes": 30, "event_type_binary": "spike", "event_type_weighted": "warning",
        },
    ])
    figure = build_signal_timeseries_card("EngCoolTemp", raw, pd.DataFrame(), pd.DataFrame(), "T_01", events)
    names = [trace.name for trace in figure.data]
    assert any("Anomalía" in str(name) for name in names)
    assert any("Evento" in str(name) for name in names)
    # The view opens on the longest episode, not on the most recent samples.
    assert figure.layout.xaxis.range[0] == pd.Timestamp("2026-06-01 01:00:00")
    assert len(figure.layout.shapes) == 2


def test_signal_chart_falls_back_to_recent_window_without_episodes():
    """With no events there is no episode to centre on."""
    raw = pd.DataFrame({
        "Fecha": pd.date_range("2026-06-01", periods=8, freq="h"),
        "EngCoolTemp": range(8),
    })

    figure = build_signal_timeseries_card(
        "EngCoolTemp", raw, pd.DataFrame(), pd.DataFrame(), "T_01", pd.DataFrame()
    )

    assert figure.layout.xaxis.range[0] == pd.Timestamp("2026-06-01 00:00:00")
    assert not figure.layout.shapes
