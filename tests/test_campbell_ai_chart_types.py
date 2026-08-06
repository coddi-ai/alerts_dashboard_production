"""Tests for the chart types recovered from the previous dashboard.

The earlier iteration offered radar charts, histograms, treemaps and alert
timeseries; the ported grammar had shrunk to six aggregate shapes. These tests pin
the recovered vocabulary, the row-level charts that plot raw values rather than an
aggregate, and the curated shapes that only the named registry can build.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.campbell_ai.chart_registry import CHART_DEFINITIONS, DashboardChartRegistry
from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import CampbellDataError
from src.campbell_ai.models import VisualizationArtifact
from src.campbell_ai.visualization import (
    CHART_TYPES,
    ROW_LEVEL_TYPES,
    DashboardVisualizationService,
)
from src.charts import ALL_CHART_KINDS, CHART_KINDS, REGISTRY_ONLY_KINDS


def _oil_repository(tmp_path) -> DashboardDataRepository:
    oil = tmp_path / "oil" / "golden" / "cda"
    oil.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "unitId": unit,
                "componentNameNormalized": component,
                "componentName": component,
                "report_status": status,
                "sampleDate": "2026-07-01",
                "severity_score": severity,
                "oilHourRange": "LT_1000",
                "Hierro": iron,
                "Cobre": 4.0,
                "Silicio": 3.0,
            }
            for unit, component, status, severity, iron in (
                ("T_15", "motor", "Anormal", 26, 65.0),
                ("T_9", "motor", "Normal", 2, 10.0),
                ("T_11", "rueda", "Alerta", 9, 20.0),
                ("T_12", "rueda", "Normal", 1, 5.0),
            )
        ]
    ).to_parquet(oil / "classified.parquet", index=False)
    pd.DataFrame(
        [
            {
                "client": "CDA",
                "machine": "camion",
                "component": "motor",
                "essay": essay,
                "oilHourRange": "LT_1000",
                "threshold_normal": normal,
                "threshold_alert": alert,
                "threshold_critic": critic,
            }
            for essay, normal, alert, critic in (
                ("Hierro", 40.0, 57.0, 66.0),
                ("Cobre", 6.0, 8.0, 17.0),
                ("Silicio", 4.0, 6.0, 8.0),
            )
        ]
    ).to_parquet(oil / "stewart_limits.parquet", index=False)
    return DashboardDataRepository(tmp_path)


def _telemetry_repository(tmp_path) -> DashboardDataRepository:
    telemetry = tmp_path / "telemetry" / "golden" / "cda"
    telemetry.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "unit_id": unit,
                "component": component,
                "evaluation_week": 15,
                "evaluation_year": 2026,
                "component_status": status,
                "component_score": score,
            }
            for unit, component, status, score in (
                ("T_18", "Motor", "Alerta", 2.0),
                ("T_18", "Direccion", "Anormal", 1.0),
                ("T_9", "Motor", "Normal", 4.0),
                ("T_9", "Direccion", "Normal", 4.0),
            )
        ]
    ).to_parquet(telemetry / "classified.parquet", index=False)
    pd.DataFrame(
        [
            {
                "unit_id": "T_18",
                "evaluation_week": 15,
                "evaluation_year": 2026,
                "overall_status": "Alerta",
                "priority_score": 121.0,
                "machine_score": 2.0,
                "components_anormal": 1,
                "components_alerta": 2,
            }
        ]
    ).to_parquet(telemetry / "machine_status.parquet", index=False)
    return DashboardDataRepository(tmp_path)


# ------------------------------------------------------------------ vocabulary


def test_chart_vocabulary_is_declared_once():
    """Three files used to hardcode the list; a new kind must need one edit."""
    assert CHART_TYPES == set(CHART_KINDS)
    assert set(ALL_CHART_KINDS) == set(CHART_KINDS) | set(REGISTRY_ONLY_KINDS)
    # Curated shapes must not be reachable through the free grammar.
    assert not set(REGISTRY_ONLY_KINDS) & CHART_TYPES


def test_recovered_chart_types_are_available():
    for kind in ("histogram", "treemap", "scatter", "box", "area", "horizontal_bar"):
        assert kind in CHART_TYPES, kind
    for kind in ("radar", "gauge"):
        assert kind in ALL_CHART_KINDS, kind


def test_artifact_rejects_a_chart_type_outside_the_vocabulary():
    with pytest.raises(ValueError, match="chart_type no soportado"):
        VisualizationArtifact(
            title="t",
            description="d",
            dataset="alerts",
            chart_type="sunburst",
            figure={"data": [], "layout": {}},
        )


# ------------------------------------------------------------- aggregate shapes


def _alert_repository(tmp_path) -> DashboardDataRepository:
    alerts = tmp_path / "alerts" / "golden" / "cda"
    alerts.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "UnitId": unit,
                "Timestamp": stamp,
                "sistema": "Motor",
                "subsistema": subsystem,
                "Trigger_type": trigger,
            }
            for unit, stamp, subsystem, trigger in (
                ("T_9", "2026-05-01T10:00:00", "Aire", "Telemetria"),
                ("T_9", "2026-05-02T10:00:00", "Aire", "Telemetria"),
                ("T_15", "2026-06-01T10:00:00", "Refrigeracion", "Mixto"),
                ("T_18", "2026-07-01T10:00:00", "Refrigeracion", "Telemetria"),
            )
        ]
    ).to_csv(alerts / "consolidated_alerts.csv", index=False)
    return DashboardDataRepository(tmp_path)


def test_treemap_area_and_horizontal_bar_build_from_alerts(tmp_path):
    service = DashboardVisualizationService(_alert_repository(tmp_path))

    treemap = service.create_chart(
        client="cda", dataset="alerts", chart_type="treemap", dimension="trigger", days=365
    )
    area = service.create_chart(
        client="cda", dataset="alerts", chart_type="area", dimension="month", days=365
    )
    horizontal = service.create_chart(
        client="cda",
        dataset="alerts",
        chart_type="horizontal_bar",
        dimension="subsystem",
        days=365,
    )

    assert treemap.figure["data"][0]["type"] == "treemap"
    assert area.figure["data"][0]["fill"] == "tozeroy"
    bar = horizontal.figure["data"][0]
    assert bar["orientation"] == "h"
    # A horizontal ranking must read top-down, not bottom-up.
    assert horizontal.figure["layout"]["yaxis"]["autorange"] == "reversed"


def test_area_and_line_require_a_time_dimension(tmp_path):
    service = DashboardVisualizationService(_alert_repository(tmp_path))

    with pytest.raises(CampbellDataError, match="dimensión temporal"):
        service.create_chart(
            client="cda", dataset="alerts", chart_type="area", dimension="unit"
        )


# ------------------------------------------------------------ row-level shapes


def test_histogram_bins_the_metric_and_reports_its_spread(tmp_path):
    service = DashboardVisualizationService(_oil_repository(tmp_path))

    artifact = service.create_chart(
        client="cda",
        dataset="oil_components",
        chart_type="histogram",
        dimension="",
        metric="severity_score",
        aggregation="mean",
    )

    assert artifact.figure["data"][0]["type"] == "histogram"
    # The summary describes the distribution, not a ranking.
    assert artifact.summary["top"] == {"min": 1.0, "max": 26.0, "mean": 9.5, "median": 5.5}
    # No aggregation happened, so the label must not claim one.
    assert "Promedio" not in artifact.summary["value_label"]


def test_histogram_rejects_a_grouping_dimension_and_count(tmp_path):
    """Silently ignoring `dimension` would mislead; count has nothing to bin."""
    service = DashboardVisualizationService(_oil_repository(tmp_path))

    with pytest.raises(CampbellDataError, match="no usa 'dimension'"):
        service.create_chart(
            client="cda",
            dataset="oil_components",
            chart_type="histogram",
            dimension="component",
            metric="severity_score",
            aggregation="mean",
        )
    with pytest.raises(CampbellDataError, match="requiere una métrica numérica"):
        service.create_chart(
            client="cda", dataset="oil_components", chart_type="histogram", dimension=""
        )


def test_box_compares_distributions_per_category(tmp_path):
    service = DashboardVisualizationService(_oil_repository(tmp_path))

    artifact = service.create_chart(
        client="cda",
        dataset="oil_components",
        chart_type="box",
        dimension="component",
        metric="severity_score",
        aggregation="mean",
    )

    traces = artifact.figure["data"]
    assert {trace["type"] for trace in traces} == {"box"}
    assert {trace["name"] for trace in traces} == {"motor", "rueda"}
    assert artifact.summary["categories"] == 2


def test_scatter_uses_the_secondary_slot_as_a_second_metric(tmp_path):
    service = DashboardVisualizationService(_telemetry_repository(tmp_path))

    artifact = service.create_chart(
        client="cda",
        dataset="telemetry_machine_status",
        chart_type="scatter",
        dimension="unit",
        metric="priority_score",
        secondary_dimension="machine_score",
        aggregation="max",
    )

    trace = artifact.figure["data"][0]
    assert trace["type"] == "scatter"
    assert trace["mode"] == "markers+text"
    assert list(trace["x"]) == [121.0]
    assert list(trace["y"]) == [2.0]
    assert artifact.summary["top"] == {"T_18": [121.0, 2.0]}


def test_scatter_requires_a_second_metric(tmp_path):
    service = DashboardVisualizationService(_telemetry_repository(tmp_path))

    with pytest.raises(CampbellDataError, match="segunda métrica"):
        service.create_chart(
            client="cda",
            dataset="telemetry_machine_status",
            chart_type="scatter",
            dimension="unit",
            metric="priority_score",
            aggregation="max",
        )


def test_row_level_types_are_declared_so_labels_stay_honest():
    assert ROW_LEVEL_TYPES == {"histogram", "box", "scatter"}


# ------------------------------------------------------------- named registry


def test_oil_radar_normalizes_essays_against_their_alert_threshold(tmp_path):
    """Iron reads in the tens and zinc in the thousands, so raw axes are unreadable."""
    registry = DashboardChartRegistry(_oil_repository(tmp_path))

    artifact = registry.render("cda", "oil_essay_radar", {"unit_id": "T_15"})

    assert artifact.chart_type == "radar"
    traces = artifact.figure["data"]
    assert traces[0]["type"] == "scatterpolar"
    # A reference ring at 1.0 marks the limit itself.
    assert traces[1]["name"] == "Límite de alerta"
    assert set(traces[1]["r"]) == {1.0}
    # Raw values and thresholds stay in the summary so the agent cites measurements.
    assert artifact.summary["essays"]["Hierro"] == {
        "value": 65.0,
        "threshold_alert": 57.0,
        "threshold_critic": 66.0,
    }
    assert artifact.summary["above_alert_limit"] == ["Hierro"]
    assert "Hierro 65.0 (límite 57.0)" in artifact.description


def test_oil_radar_needs_a_unit_and_enough_essays(tmp_path):
    registry = DashboardChartRegistry(_oil_repository(tmp_path))

    with pytest.raises(CampbellDataError, match="requiere unit_id"):
        registry.render("cda", "oil_essay_radar")
    with pytest.raises(CampbellDataError, match="Sin muestras de aceite"):
        registry.render("cda", "oil_essay_radar", {"unit_id": "T_99"})
    # 'rueda' has samples but no thresholds in the fixture.
    with pytest.raises(CampbellDataError, match="límites de referencia"):
        registry.render("cda", "oil_essay_radar", {"unit_id": "T_11", "component": "rueda"})


def test_component_heatmap_crosses_units_and_components(tmp_path):
    registry = DashboardChartRegistry(_telemetry_repository(tmp_path))

    artifact = registry.render("cda", "telemetry_component_heatmap")

    assert artifact.chart_type == "heatmap"
    assert artifact.figure["data"][0]["type"] == "heatmap"
    assert artifact.summary["units"] == 2
    assert artifact.summary["components"] == 2
    assert "menor indica peor" in artifact.summary["note"]


def test_gauge_reports_one_indicator_with_its_bands(tmp_path):
    registry = DashboardChartRegistry(_telemetry_repository(tmp_path))

    artifact = registry.render("cda", "unit_health_gauge", {"unit_id": "T_18"})

    assert artifact.chart_type == "gauge"
    trace = artifact.figure["data"][0]
    assert trace["type"] == "indicator"
    assert trace["value"] == 121.0
    # Bands must cover the whole scale, including a value above 100.
    steps = trace["gauge"]["steps"]
    assert len(steps) == 3
    assert steps[-1]["range"][1] >= 121.0
    assert "prioridad 121.0" in artifact.description


def test_gauge_requires_a_unit(tmp_path):
    registry = DashboardChartRegistry(_telemetry_repository(tmp_path))

    with pytest.raises(CampbellDataError, match="requiere unit_id"):
        registry.render("cda", "unit_health_gauge")


def test_alert_trend_and_treemap_mirror_the_alerts_tab(tmp_path):
    registry = DashboardChartRegistry(_alert_repository(tmp_path))

    trend = registry.render("cda", "alert_trend", {"days": 365})
    treemap = registry.render("cda", "alert_trigger_treemap", {"days": 365})

    assert trend.chart_type == "line"
    assert list(trend.summary["by_month"]) == ["2026-05", "2026-06", "2026-07"]
    assert trend.summary["by_month"]["2026-05"] == 2
    assert treemap.chart_type == "treemap"
    assert treemap.summary["by_trigger_type"] == {"Telemetria": 3, "Mixto": 1}
    assert "por disparador" in treemap.description


def test_no_named_chart_uses_call_instructions_as_its_caption():
    """The catalogue text may say "requires unit_id"; a figure caption must not."""
    for definition in CHART_DEFINITIONS:
        assert definition.chart_type in ALL_CHART_KINDS, definition.chart_id
        caption = definition.caption or definition.description
        assert caption.strip(), definition.chart_id
        assert "requiere" not in caption.lower(), definition.chart_id
        assert "admite" not in caption.lower(), definition.chart_id


def test_registry_covers_the_shapes_the_previous_dashboard_offered():
    """Radar, histogram, treemap, heatmap, gauge and timeseries were all missing."""
    kinds = {definition.chart_type for definition in CHART_DEFINITIONS}
    assert {"radar", "histogram", "treemap", "heatmap", "gauge", "line", "pie"} <= kinds
