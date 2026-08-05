import json

import pandas as pd

from dashboard.components.alerts_charts import (
    FEATURE_NAMES_ES,
    create_alerts_per_unit_chart,
    create_alerts_per_week_chart,
    create_system_distribution_pie_chart,
    create_context_kpis_cards_golden,
    create_sensor_trends_chart_golden,
)
from dashboard.callbacks.alerts_callbacks import _select_telemetry_alert_data
from dashboard.components.alerts_report import prepare_alert_rows, translate_alert_system
from dashboard.components.alerts_tables import parse_ia_message_sections
from src.data.loaders import _load_alerts_data_cached, load_alerts_data


def test_capstone_canonical_signals_and_structured_ai_are_client_facing():
    message = json.dumps(
        {
            "diagnostic": "engine_speed_rpm supera el límite",
            "recommended_actions": ["Revisar coolant_pressure_psi"],
            "evidence": ["telemetry"],
        }
    )

    sections = parse_ia_message_sections(message)
    rows = prepare_alert_rows(
        pd.DataFrame(
            [
                {
                    "Timestamp": "2026-07-10T12:00:00-04:00",
                    "UnitId": "CA-42",
                    "sistema": "motor",
                    "componente": "engine",
                    "Trigger_type": "Telemetria",
                    "Trigger_Var": "engine_speed_rpm",
                    "mensaje_ia": message,
                    "has_telemetry": True,
                    "has_tribology": False,
                }
            ]
        )
    )

    assert FEATURE_NAMES_ES["engine_speed_rpm"] == "Velocidad del motor"
    assert "Velocidad del motor" in sections["diagnostico"]
    assert "Presión del refrigerante" in sections["acciones"]
    assert rows.loc[0, "component_display"] == "Motor"
    assert rows.loc[0, "signal_display"] == "Velocidad del motor"


def test_capstone_loader_uses_configured_data_root(tmp_path, monkeypatch):
    alerts_path = tmp_path / "alerts" / "golden" / "capstone" / "consolidated_alerts.csv"
    alerts_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "FusionID": "F-1",
                "Timestamp": "2026-07-10T12:00:00-04:00",
                "UnitId": "CA-42",
                "sistema": "motor",
                "subsistema": "engine",
                "componente": "engine",
                "Trigger_type": "Mixto",
                "TribologyID": 12.0,
            }
        ]
    ).to_csv(alerts_path, index=False)

    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    _load_alerts_data_cached.cache_clear()
    loaded = load_alerts_data("CAPSTONE")
    _load_alerts_data_cached.cache_clear()

    assert len(loaded) == 1
    assert loaded.loc[0, "TribologyID"] == "12"
    assert loaded.loc[0, "Timestamp"].tzinfo is None
    assert bool(loaded.loc[0, "has_telemetry"])
    assert bool(loaded.loc[0, "has_tribology"])


def test_capstone_telemetry_detail_matches_string_telemetry_or_fusion_id():
    telemetry_detail = pd.DataFrame(
        [
            {"AlertID": "CAP-fusion-1", "Unit": "CA-42", "value": 10},
            {"AlertID": "CAP-other", "Unit": "CA-43", "value": 20},
        ]
    )
    alert = pd.Series(
        {
            "TelemetryID": "CAP-telemetry-1",
            "FusionID": "CAP-fusion-1",
            "UnitId": "CA-42",
        }
    )

    selected, identifiers, unit_id = _select_telemetry_alert_data(telemetry_detail, alert)

    assert identifiers == ["CAP-telemetry-1", "CAP-fusion-1"]
    assert unit_id == "CA-42"
    assert selected["AlertID"].tolist() == ["CAP-fusion-1"]

    telemetry_keyed = pd.DataFrame([{"AlertID": "CAP-telemetry-1", "Unit": "CA-42"}])
    selected, _, _ = _select_telemetry_alert_data(telemetry_keyed, alert)
    assert selected["AlertID"].tolist() == ["CAP-telemetry-1"]


def test_capstone_context_kpis_use_canonical_engine_signals():
    context = create_context_kpis_cards_golden(
        pd.DataFrame(
            [
                {
                    "TimeStart": pd.Timestamp("2026-07-10 12:00:00"),
                    "engine_load_pct_Value": 42.5,
                    "engine_speed_rpm_Value": 1234.0,
                }
            ]
        ),
        pd.Timestamp("2026-07-10 12:00:00"),
        "engine_speed_rpm",
    )

    def component_text(component):
        if isinstance(component, (list, tuple)):
            return " ".join(component_text(child) for child in component)
        children = getattr(component, "children", None)
        if children is not None:
            return component_text(children)
        return str(component)

    rendered = component_text(context)

    assert "42%" in rendered
    assert "1234 RPM" in rendered


def test_capstone_system_labels_are_translated_in_alert_charts():
    alerts = pd.DataFrame(
        [
            {
                "UnitId": "CA-42",
                "sistema": "motor",
                "Timestamp": "2026-07-10T12:00:00",
            }
        ]
    )

    unit_chart = create_alerts_per_unit_chart(alerts)
    week_chart = create_alerts_per_week_chart(alerts)
    pie_chart = create_system_distribution_pie_chart(alerts)

    assert translate_alert_system("motor") == "Motor"
    assert {trace.name for trace in unit_chart.data} == {"Motor"}
    assert unit_chart.data[0].marker.color == "#355c7d"
    assert {trace.name for trace in week_chart.data} == {"Motor"}
    assert set(pie_chart.data[0].labels) == {"Motor"}
    assert list(pie_chart.data[0].marker.colors) == ["#355c7d"]


def test_capstone_state_markers_and_legend_use_semantic_colors():
    alert_time = pd.Timestamp("2026-07-10 12:00:00")
    alert_data = pd.DataFrame(
        [
            {
                "TimeStart": alert_time - pd.Timedelta(minutes=30),
                "crankcase_pressure_inh2o_Value": 2.0,
                "State": "Potencia",
            },
            {
                "TimeStart": alert_time - pd.Timedelta(minutes=15),
                "crankcase_pressure_inh2o_Value": 3.0,
                "State": "TRANSICION",
            },
            {
                "TimeStart": alert_time,
                "crankcase_pressure_inh2o_Value": 4.0,
                "State": "Desconocido",
            },
        ]
    )

    figure = create_sensor_trends_chart_golden(
        alert_data=alert_data,
        feature_names=["crankcase_pressure_inh2o"],
        unit_id="CA-42",
        alert_time=alert_time,
        feature_name_map=FEATURE_NAMES_ES,
        client="CAPSTONE",
    )

    sensor_trace = next(trace for trace in figure.data if trace.mode == "lines+markers")
    assert list(sensor_trace.marker.color) == ["#2ecc71", "#f39c12", "#95a5a6"]

    state_legend = {
        trace.name: trace.marker.color
        for trace in figure.data
        if trace.name in {"Potencia", "Transición"}
    }
    assert state_legend == {"Potencia": "#2ecc71", "Transición": "#f39c12"}
