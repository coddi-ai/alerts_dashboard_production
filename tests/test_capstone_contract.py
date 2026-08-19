import json

import pandas as pd

from dashboard.components.alerts_charts import (
    FEATURE_NAMES_ES,
    PARETO_BAR_COLOR,
    create_alerts_per_unit_chart,
    create_alerts_per_week_chart,
    create_system_signal_treemap,
    create_context_kpis_cards_golden,
    create_sensor_trends_chart_golden,
)
from dashboard.callbacks.alerts_callbacks import _select_telemetry_alert_data
from dashboard.components.alerts_report import (
    prepare_alert_rows,
    translate_alert_component,
    translate_alert_system,
)
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


def test_component_labels_are_consistent_for_mixed_source_casing():
    assert translate_alert_component("engine") == "Motor"
    assert translate_alert_component("Engine") == "Motor"
    assert translate_alert_component("lubrication") == "Lubricación"
    assert translate_alert_component("Lubrication") == "Lubricación"


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
    system_chart = create_system_signal_treemap(alerts)

    assert translate_alert_system("motor") == "Motor"
    # Pareto chart: units on X, a single (non-system) bar color, and a
    # cumulative-percentage line that reaches 100% at the last point.
    assert list(unit_chart.data[0].x) == ["CA-42"]
    assert unit_chart.data[0].marker.color == PARETO_BAR_COLOR
    assert unit_chart.data[1].y[-1] == 100
    assert {trace.name for trace in week_chart.data} == {"Motor"}
    # System/signal treemap: translated Sistema is the sole level-1 node,
    # colored via the shared system palette, and every node (including its
    # signal leaf) carries the system in customdata for click-to-filter.
    assert list(system_chart.data[0].labels) == ["Motor", "Sin señal registrada"]
    assert list(system_chart.data[0].parents) == ["", "Motor"]
    assert list(system_chart.data[0].marker.colors) == ["#355c7d", "#355c7d"]
    assert list(system_chart.data[0].customdata) == ["Motor", "Motor"]


def test_capstone_single_system_treemap_groups_by_familia():
    # Capstone alerts are all "motor" (a single system), so the treemap
    # should switch to Familia -> Señal/Variable using the real
    # config/features/capstone.yaml functional_group mapping instead of
    # collapsing everything under one "Motor" system tile.
    alerts = pd.DataFrame(
        [
            {"UnitId": "CA-1", "sistema": "motor", "Timestamp": "2026-07-10T12:00:00", "Trigger_Var": "coolant_temp_c"},
            {"UnitId": "CA-2", "sistema": "motor", "Timestamp": "2026-07-10T12:05:00", "Trigger_Var": "coolant_pressure_psi"},
            {"UnitId": "CA-3", "sistema": "motor", "Timestamp": "2026-07-10T12:10:00", "Trigger_Var": "egt_01_c"},
            # 'egt_lb_c' has no standalone feature entry - it only appears
            # inside egt_bank_diff's `derived` formula - so this also proves
            # the derived-formula token fallback resolves to the same
            # functional_group ('egt') as its sibling source_column.
            {"UnitId": "CA-4", "sistema": "motor", "Timestamp": "2026-07-10T12:15:00", "Trigger_Var": "egt_lb_c"},
        ]
    )

    system_chart = create_system_signal_treemap(alerts, client="CAPSTONE")

    root_labels = set(system_chart.data[0].parents) | set(system_chart.data[0].labels)
    assert "Refrigerante" in root_labels  # coolant
    assert "Gases de escape (EGT)" in root_labels  # egt
    # No raw functional_group identifier (e.g. "coolant", "egt") should leak.
    assert "coolant" not in root_labels
    assert "egt" not in root_labels
    # Every node still carries the (single, constant) owning system in
    # customdata, so click-to-filter keeps working unchanged.
    assert set(system_chart.data[0].customdata) == {"Motor"}


def test_capstone_treemap_falls_back_to_sistema_without_client_or_mapping():
    alerts = pd.DataFrame(
        [{"UnitId": "CA-1", "sistema": "motor", "Timestamp": "2026-07-10T12:00:00", "Trigger_Var": "coolant_temp_c"}]
    )

    # No client passed at all.
    no_client_chart = create_system_signal_treemap(alerts)
    assert list(no_client_chart.data[0].labels) == ["Motor", "Temperatura del refrigerante"]

    # Client with no matching config/features/{client}.yaml.
    unknown_client_chart = create_system_signal_treemap(alerts, client="UNKNOWN_CLIENT")
    assert list(unknown_client_chart.data[0].labels) == ["Motor", "Temperatura del refrigerante"]


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
