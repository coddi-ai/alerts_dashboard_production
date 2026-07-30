import json

import pandas as pd

from dashboard.components.alerts_charts import FEATURE_NAMES_ES
from dashboard.components.alerts_report import prepare_alert_rows
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
