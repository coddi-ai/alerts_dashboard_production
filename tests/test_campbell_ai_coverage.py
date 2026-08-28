"""Tests for per-client data coverage and the per-alert sensor chart.

Companies do not carry the same techniques: one has alerts, oil, telemetry,
maintenance and predictive models, another only oil. An agent that assumes the
richest client promises analyses that cannot run, so capability is resolved from the
datasets actually present and surfaced before the first question.

The sensor chart is the last visual missing from the previous dashboard. Its open
question was how the agent picks signals; the answer here is that the trigger is the
default and the tool reports what else has captured values.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.campbell_ai.chart_registry import DashboardChartRegistry
from src.campbell_ai.data import (
    ANALYSIS_CAPABILITIES,
    DATASET_MAP,
    DashboardDataRepository,
)
from src.campbell_ai.errors import CampbellDataError


# --------------------------------------------------------------- data coverage


def _oil_only_client(tmp_path) -> DashboardDataRepository:
    """A client with tribology only, like ENEX."""
    oil = tmp_path / "oil" / "golden" / "enex"
    oil.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "unitId": "T_1",
                "componentNameNormalized": "motor",
                "componentName": "motor",
                "report_status": "Normal",
                "sampleDate": "2026-07-01",
                "severity_score": 1,
            }
        ]
    ).to_parquet(oil / "classified.parquet", index=False)
    pd.DataFrame(
        [{"unit_id": "T_1", "overall_status": "Normal", "latest_sample_date": "2026-07-01"}]
    ).to_parquet(oil / "machine_status.parquet", index=False)
    pd.DataFrame(
        [
            {
                "client": "ENEX",
                "machine": "camion",
                "component": "motor",
                "essay": "Hierro",
                "oilHourRange": "LT_1000",
                "threshold_alert": 50.0,
                "threshold_critic": 60.0,
            }
        ]
    ).to_parquet(oil / "stewart_limits.parquet", index=False)
    return DashboardDataRepository(tmp_path)


def test_capabilities_state_what_is_possible_and_why_the_rest_is_not(tmp_path):
    repository = _oil_only_client(tmp_path)

    capabilities = repository.client_capabilities("enex")

    available = {item["key"] for item in capabilities["available"]}
    assert {"oil_fleet", "oil_components", "oil_limits"} <= available
    # No alerts, telemetry, maintenance or predictive data exists for this client.
    assert "alerts" not in available
    assert "telemetry_fleet" not in available

    reasons = {item["key"]: item["reason"] for item in capabilities["unavailable"]}
    assert "Faltan fuentes" in reasons["alerts"]
    # A blocked module is a different reason than a missing file.
    assert "módulo predictivo" in reasons["predictive_motor"]

    assert capabilities["techniques"] == {
        "alertas": False,
        "aceite": True,
        "telemetria": False,
        "mantenimiento": False,
        "predictivo": False,
    }


def test_capabilities_are_offered_to_the_agent_with_instructions(tmp_path):
    payload = json.loads(_oil_only_client(tmp_path).describe_capabilities("enex"))

    assert "available" in payload and "unavailable" in payload
    # The agent must be told not to substitute a missing technique with another.
    assert "no los sustituyas" in payload["note"]


def test_every_capability_declares_registered_datasets():
    """A capability pointing at an unregistered dataset can never become available."""
    for capability in ANALYSIS_CAPABILITIES:
        assert capability.requires, capability.key
        for key in capability.requires:
            assert key in DATASET_MAP, f"{capability.key} -> {key}"
        assert capability.tools, capability.key
        assert capability.label.strip(), capability.key


def test_capability_keys_are_unique():
    keys = [capability.key for capability in ANALYSIS_CAPABILITIES]
    assert len(keys) == len(set(keys))


def test_an_undeclared_client_with_no_data_reports_everything_unavailable(tmp_path):
    """The guarantee that survives assuming presence.

    A declared dataset is taken as present without touching disk, so a *declared* client with
    an empty data root now reports its declared coverage. What must still hold is the case
    that has no declaration to lean on: an unknown client falls back to checking the
    filesystem, finds nothing, and is offered nothing - rather than inheriting some other
    client's catalogue.
    """
    repository = DashboardDataRepository(tmp_path / "empty")

    capabilities = repository.client_capabilities("cliente_nuevo")

    assert capabilities["available"] == []
    assert len(capabilities["unavailable"]) == len(ANALYSIS_CAPABILITIES)
    assert not any(capabilities["techniques"].values())


# ------------------------------------------------------- per-alert sensor chart


def _alert_detail_client(tmp_path) -> DashboardDataRepository:
    """Wide per-sample detail, with a state-dependent limit as production has."""
    telemetry = tmp_path / "telemetry" / "golden" / "cda"
    telemetry.mkdir(parents=True)
    rows = []
    for index, (state, value, limit) in enumerate(
        [
            ("Operacional", 90.0, 105.0),
            ("Operacional", 100.0, 105.0),
            # Idle lowers the ceiling, so 99 breaches it while 100 did not breach 105.
            ("Ralenti", 99.0, 95.0),
            ("Ralenti", 80.0, 95.0),
        ]
    ):
        rows.append(
            {
                "AlertID": 7,
                "Unit": "T_18",
                "Trigger": "EngCoolTemp",
                "TimeStart": f"2026-07-09T1{index}:00:00",
                "State": state,
                "EngCoolTemp_Value": value,
                "EngCoolTemp_Upper_Limit": limit,
                "TCOutTemp_Value": 70.0 + index,
                "TCOutTemp_Upper_Limit": 95.0,
                # Present as a column but never captured: must not become a panel.
                "DiffTemp_Value": None,
                "DiffTemp_Upper_Limit": 80.0,
                "GroundSpd_Value": 10.0 + index,
            }
        )
    pd.DataFrame(rows).to_csv(
        telemetry / "alerts_detail_wide_with_gps.csv", index=False
    )
    return DashboardDataRepository(tmp_path)


def test_alert_detail_compares_each_sample_against_its_own_limit(tmp_path):
    """The threshold moves with machine state; using its maximum hid real breaches."""
    repository = _alert_detail_client(tmp_path)

    payload = json.loads(repository.query_alert_detail("cda", alert_id="7", unit_id="T_18"))
    record = next(
        item for item in payload["records"] if item["trigger"] == "EngCoolTemp"
    )

    assert record["peak_value"] == 100.0
    assert record["state_at_peak"] == "Operacional"
    assert record["upper_limit_at_peak"] == 105.0
    assert record["upper_limit_values"] == [95.0, 105.0]
    # The 99.0 idle sample breaches its 95.0 ceiling even though the peak did not
    # breach 105.0; comparing against the maximum reported zero.
    assert record["samples_above_limit"] == 1
    assert record["worst_above_value"] == 99.0
    assert record["max_above_exceedance"] == 4.0
    assert "estado de maquina" in payload["note"]


def test_signal_listing_separates_captured_values_from_limits(tmp_path):
    repository = _alert_detail_client(tmp_path)

    payload = json.loads(
        repository.query_alert_signals("cda", alert_id="7", unit_id="T_18")
    )

    assert payload["trigger"] == "EngCoolTemp"
    # A column with limits but no readings cannot be plotted.
    assert "DiffTemp" not in payload["signals_available"]
    assert {"EngCoolTemp", "TCOutTemp"} <= set(payload["signals_available"])
    assert "contexto de operacion" in payload["note"]


def test_sensor_series_defaults_to_the_triggering_signal(tmp_path):
    """The trigger is what caused the alert; plotting every sampled sensor is noise."""
    repository = _alert_detail_client(tmp_path)

    payload = repository.alert_signal_series("cda", alert_id="7", unit_id="T_18")

    assert payload["signals_selected"] == ["EngCoolTemp"]
    panel = payload["panels"][0]
    assert panel["values"] == [90.0, 100.0, 99.0, 80.0]
    assert panel["upper"] == [105.0, 105.0, 95.0, 95.0]
    assert panel["lower"] is None
    assert len(panel["times"]) == 4


def test_sensor_series_accepts_extra_signals_and_reports_unknown_ones(tmp_path):
    repository = _alert_detail_client(tmp_path)

    payload = repository.alert_signal_series(
        "cda", alert_id="7", unit_id="T_18", signals=("EngCoolTemp", "TCOutTemp")
    )

    assert payload["signals_selected"] == ["EngCoolTemp", "TCOutTemp"]
    assert len(payload["panels"]) == 2


def test_signal_names_resolve_regardless_of_case(tmp_path):
    """A transcription slip aborted the whole chart and the agent gave up."""
    repository = _alert_detail_client(tmp_path)

    for written in ("engcooltemp", "ENGCOOLTEMP", " EngCoolTemp "):
        payload = repository.alert_signal_series(
            "cda", alert_id="7", unit_id="T_18", signals=(written,)
        )
        # The canonical code is reported back, not the user's spelling.
        assert payload["signals_selected"] == ["EngCoolTemp"], written
        assert payload["signals_unknown"] == []


def test_requesting_only_unknown_signals_fails_instead_of_plotting_another(tmp_path):
    """Substituting the trigger would make the answer describe the wrong series."""
    repository = _alert_detail_client(tmp_path)

    with pytest.raises(CampbellDataError, match="Ninguna de las senales"):
        repository.alert_signal_series(
            "cda", alert_id="7", unit_id="T_18", signals=("DiffTemp",)
        )


def test_sensor_series_falls_back_to_the_latest_alert_of_a_unit(tmp_path):
    repository = _alert_detail_client(tmp_path)

    payload = repository.alert_signal_series("cda", unit_id="T_18")

    assert payload["alert_id"] == 7
    assert payload["trigger"] == "EngCoolTemp"


def test_sensor_chart_renders_one_panel_per_signal_with_its_band(tmp_path):
    registry = DashboardChartRegistry(_alert_detail_client(tmp_path))

    artifact = registry.render(
        "cda",
        "alert_sensor_trend",
        {"unit_id": "T_18", "alert_id": "7", "signal": "EngCoolTemp,TCOutTemp"},
    )

    assert artifact.chart_type == "line"
    layout = artifact.figure["layout"]
    # Two stacked panels share the x axis.
    assert "yaxis2" in layout
    titles = [
        annotation["text"]
        for annotation in layout.get("annotations", [])
        if annotation.get("text")
    ]
    assert any("refrigerante" in title.lower() for title in titles)
    assert artifact.summary["signals_plotted"] == ["EngCoolTemp", "TCOutTemp"]
    assert "estado de máquina" in artifact.summary["note"]


def test_sensor_chart_is_not_offered_to_a_client_without_the_detail_source(tmp_path):
    registry = DashboardChartRegistry(_oil_only_client(tmp_path))

    assert "alert_sensor_trend" not in {
        item["chart_id"] for item in registry.list_charts("enex")
    }
    with pytest.raises(CampbellDataError):
        registry.render("enex", "alert_sensor_trend", {"unit_id": "T_1"})
