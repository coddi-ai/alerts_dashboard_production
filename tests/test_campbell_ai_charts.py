"""Tests for the shared chart layer and the named-chart registry.

Plan section 14 asks for one theme and pure builders shared by the dashboard tabs
and Campbell AI, plus a registry the agent addresses by `chart_id` instead of by
naming Python functions. These tests pin the theme convergence and the registry's
authorization and validation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.campbell_ai.chart_registry import (
    CHART_DEFINITIONS,
    DashboardChartRegistry,
)
from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import CampbellDataError
from src.charts.builders import (
    build_pareto,
    build_stacked_bar,
    build_status_donut,
    sort_statuses,
)
from src.charts.theme import BRAND_ACCENT, BRAND_TITLE, STATUS_COLORS


def test_dashboard_and_campbell_share_one_status_language():
    """A divergent palette was the exact inconsistency plan section 14.2 warns about."""
    from dashboard.components.charts import STATUS_COLORS as dashboard_colors

    assert dashboard_colors is STATUS_COLORS
    for status in ("Normal", "Alerta", "Anormal", "InsufficientData"):
        assert status in dashboard_colors


def test_status_order_puts_the_worst_condition_first():
    assert sort_statuses(["Normal", "Anormal", "Alerta"]) == [
        "Anormal",
        "Alerta",
        "Normal",
    ]
    # Unknown labels are kept, not dropped.
    assert sort_statuses(["Normal", "Otro"]) == ["Normal", "Otro"]


def test_status_donut_uses_status_colors_and_shows_the_total():
    figure = build_status_donut(
        {"Normal": 8, "Alerta": 2, "Anormal": 1}, title="Estado", total_label="equipos"
    )

    trace = figure.to_dict()["data"][0]
    assert trace["type"] == "pie"
    assert list(trace["labels"]) == ["Anormal", "Alerta", "Normal"]
    assert set(trace["marker"]["colors"]) <= set(STATUS_COLORS.values())
    annotations = figure.to_dict()["layout"]["annotations"]
    assert "11" in annotations[0]["text"]
    assert figure.to_dict()["layout"]["font"]["color"] == BRAND_TITLE


def test_pareto_labels_its_two_axes_independently():
    """A blanket update_yaxes used to label the cumulative axis with the bar metric."""
    figure = build_pareto(
        ["T_9", "T_15"],
        [9, 1],
        title="Pareto",
        dimension_label="Equipo",
        value_label="Alertas",
    )

    layout = figure.to_dict()["layout"]
    assert layout["yaxis"]["title"]["text"] == "Alertas"
    assert layout["yaxis2"]["title"]["text"] == "% acumulado"
    assert layout["xaxis"]["title"]["text"] == "Equipo"
    assert figure.to_dict()["data"][0]["marker"]["color"] == BRAND_ACCENT
    assert figure.to_dict()["data"][1]["y"][-1] == pytest.approx(100.0)


def test_stacked_bar_orders_status_series_by_severity():
    matrix = pd.DataFrame(
        {"Normal": [2, 3], "Anormal": [1, 0], "Alerta": [1, 1]},
        index=["Motor", "Frenos"],
    )

    figure = build_stacked_bar(
        matrix,
        title="Componentes",
        dimension_label="Componente",
        secondary_label="Estado",
        value_label="Equipos",
    )

    assert [trace["name"] for trace in figure.to_dict()["data"]] == [
        "Anormal",
        "Alerta",
        "Normal",
    ]
    assert figure.to_dict()["layout"]["barmode"] == "stack"


def _registry(tmp_path) -> DashboardChartRegistry:
    oil = tmp_path / "oil" / "golden" / "cda"
    oil.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "unit_id": "T_9",
                "overall_status": "Normal",
                "latest_sample_date": "2026-07-01",
                "priority_score": 10,
            },
            {
                "unit_id": "T_15",
                "overall_status": "Anormal",
                "latest_sample_date": "2026-07-05",
                "priority_score": 90,
            },
        ]
    ).to_parquet(oil / "machine_status.parquet", index=False)
    alerts = tmp_path / "alerts" / "golden" / "cda"
    alerts.mkdir(parents=True)
    pd.DataFrame(
        [
            {"UnitId": "T_9", "Timestamp": "2026-07-01T10:00:00", "sistema": "Motor"},
            {"UnitId": "T_9", "Timestamp": "2026-07-02T10:00:00", "sistema": "Motor"},
            {"UnitId": "T_9", "Timestamp": "2026-07-02T11:00:00", "sistema": "Motor"},
            {"UnitId": "T_15", "Timestamp": "2026-07-03T10:00:00", "sistema": "Frenos"},
            {"UnitId": "T_15", "Timestamp": "2026-07-03T11:00:00", "sistema": "Frenos"},
            {"UnitId": "T_18", "Timestamp": "2026-07-04T10:00:00", "sistema": "Motor"},
            {"UnitId": "T_20", "Timestamp": "2026-07-05T10:00:00", "sistema": "Motor"},
        ]
    ).to_csv(alerts / "consolidated_alerts.csv", index=False)
    return DashboardChartRegistry(DashboardDataRepository(tmp_path))


def test_the_catalogue_is_limited_by_what_each_client_declares(tmp_path, monkeypatch):
    """Coverage per client now comes from the declared schema, not from a disk walk.

    Validation assumes a declared dataset is present, so the catalogue is filtered by what the
    declaration says a client *has* - which is the structural fact it was always trying to
    express. A client that genuinely lacks a technique still cannot be offered its charts.

    The transient case - a declared file that failed to sync - is deliberately no longer caught
    here: it surfaces as an exception when the chart is rendered. That is the trade this design
    accepted in exchange for opening a session without touching the filesystem.
    """
    import src.campbell_ai.schema as schema_module

    registry = _registry(tmp_path)

    # Declared coverage differs per client, and the catalogue follows it.
    monkeypatch.setattr(
        schema_module,
        "_LOADED",
        {
            "cda": {
                "alerts": {"format": "csv", "columns": ["UnitId", "Timestamp"]},
                "oil_machine_status": {"format": "parquet", "columns": ["unit_id", "overall_status"]},
            },
            "enex": {
                "alerts": {"format": "csv", "columns": ["UnitId", "Timestamp"]},
            },
        },
    )
    cda = {item["chart_id"] for item in registry.list_charts("cda")}
    enex = {item["chart_id"] for item in registry.list_charts("enex")}

    assert "oil_fleet_status" in cda, "cda declara la fuente de aceite"
    assert "oil_fleet_status" not in enex, "enex no la declara y no se le puede ofrecer"
    # Ninguno declara telemetria ni predictivo.
    assert "telemetry_fleet_status" not in cda | enex
    assert "predictive_motor_ranking" not in cda | enex

    # Un cliente que la declaracion no conoce cae al camino que si mira el disco - y ahi no
    # hay nada, asi que no se le ofrece nada.
    assert registry.list_charts("cliente_nuevo") == []


def test_registry_renders_a_named_chart_with_a_grounded_description(tmp_path):
    registry = _registry(tmp_path)

    artifact = registry.render("cda", "oil_fleet_status")

    assert artifact.chart_id == "oil_fleet_status"
    assert artifact.chart_type == "pie"
    assert artifact.summary["by_status"] == {"Anormal": 1, "Normal": 1}
    assert "Anormal" in artifact.description
    assert artifact.figure["data"][0]["type"] == "pie"


def test_registry_applies_declared_parameters(tmp_path):
    registry = _registry(tmp_path)

    artifact = registry.render("cda", "alert_ranking", {"days": 365, "top_n": 3})

    top = artifact.summary["top"]
    # T_18 and T_20 tie at one alert, so only the ranked head is deterministic.
    assert list(top)[:2] == ["T_9", "T_15"]
    assert list(top.values())[:2] == [3, 2]
    assert len(top) == 3
    assert artifact.summary["total"] == 7


def test_registry_clamps_parameters_to_a_usable_range(tmp_path):
    """A one-bar ranking or a nonsense window is bounded, not passed through."""
    registry = _registry(tmp_path)

    tiny = registry.render("cda", "alert_ranking", {"days": 365, "top_n": 1})
    huge = registry.render("cda", "alert_ranking", {"days": 365, "top_n": 5000})
    garbage = registry.render("cda", "alert_ranking", {"top_n": "; drop table"})

    assert len(tiny.summary["top"]) == 3
    assert len(huge.summary["top"]) == 4
    assert len(garbage.summary["top"]) == 4


def test_registry_rejects_unknown_ids_and_undeclared_parameters(tmp_path):
    registry = _registry(tmp_path)

    with pytest.raises(CampbellDataError, match="chart_id no reconocido"):
        registry.render("cda", "drop_tables")
    # An id is never turned into a Python attribute or expression.
    with pytest.raises(CampbellDataError, match="chart_id no reconocido"):
        registry.render("cda", "_oil_fleet_status")
    with pytest.raises(CampbellDataError, match="no permitidos"):
        registry.render("cda", "oil_fleet_status", {"unit_id": "T_9"})
    with pytest.raises(CampbellDataError, match="no permitidos"):
        registry.render("cda", "alert_ranking", {"query": "select 1"})


def test_registry_honours_the_predictive_module_allowlist(tmp_path, monkeypatch):
    from src.campbell_ai import chart_registry

    monkeypatch.setattr(
        chart_registry, "predictive_module_allows", lambda client: False
    )
    registry = _registry(tmp_path)

    with pytest.raises(CampbellDataError, match="modulo predictivo"):
        registry.render("cda", "predictive_motor_ranking")
    assert "predictive_motor_ranking" not in {
        item["chart_id"] for item in registry.list_charts("cda")
    }


def test_every_definition_declares_a_supported_chart_type():
    # The registry also builds curated shapes (radar, gauge) the free grammar cannot.
    from src.charts import ALL_CHART_KINDS

    supported = set(ALL_CHART_KINDS)
    identifiers = [definition.chart_id for definition in CHART_DEFINITIONS]

    assert len(identifiers) == len(set(identifiers))
    for definition in CHART_DEFINITIONS:
        assert definition.chart_type in supported, definition.chart_id
        assert definition.datasets, definition.chart_id
        assert definition.description.strip(), definition.chart_id
