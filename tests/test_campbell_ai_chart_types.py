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


def _oil_four_limit_repository(tmp_path) -> DashboardDataRepository:
    """Oil samples plus the four-limit contract the group radar reads.

    Wear metals carry no lower limit (LIC/LIM null, as in production) while the
    physico-chemical group does, so one fixture exercises both ring layouts.
    """
    oil = tmp_path / "oil" / "golden" / "cda"
    oil.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "unitId": "T_15",
                "machineName": "camion",
                "componentName": "motor",
                "componentNameNormalized": "motor",
                "report_status": "Alerta",
                "sampleDate": "2026-07-01",
                "oilHourRange": "LT_1000",
                "Hierro": 65.0,
                "Cobre": 4.0,
                "Aluminio": 2.0,
                "Silicio": 3.0,
                "Viscocidad": 14.0,
            }
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
                "LIC": lic,
                "LIM": lim,
                "LSM": lsm,
                "LSC": lsc,
                "min_value": 0.0,
                "GroupElement": group,
                "sample_count": 100,
                "calculation_date": "2026-08-05T11:07:45",
            }
            for essay, lic, lim, lsm, lsc, group in (
                ("Hierro", None, None, 57.0, 66.0, "Desgaste"),
                ("Cobre", None, None, 8.0, 17.0, "Desgaste"),
                ("Aluminio", None, None, 3.0, 4.0, "Desgaste"),
                ("Silicio", None, None, 6.0, 8.0, "Contaminante"),
                ("Viscocidad", 12.0, 13.0, 16.0, 18.0, "Fisico Quimico"),
            )
        ]
    ).to_parquet(oil / "stewart_limits_four.parquet", index=False)
    return DashboardDataRepository(tmp_path)



def _oil_history_repository(tmp_path) -> DashboardDataRepository:
    """Three samples of one component, with four-limit thresholds for part of the essays."""
    oil = tmp_path / "oil" / "golden" / "cda"
    oil.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "unitId": "T_15",
                "machineName": "camion",
                "componentName": "motor",
                "componentNameNormalized": "motor",
                "report_status": "Alerta",
                "sampleDate": date,
                "oilHourRange": "LT_1000",
                "Hierro": iron,
                "Índice PQ": iron / 2,
                "Silicio": 3.0,
                "Aluminio": 2.0,
                "Calcio": 1800.0,
                "Zinc": 1200.0,
                "Fósforo": 1100.0,
                # Sin umbral por contrato: la serie se dibuja igual.
                "Combustible": 0.0,
            }
            for date, iron in (("2026-05-01", 30.0), ("2026-06-01", 45.0), ("2026-07-01", 65.0))
        ]
    ).to_parquet(oil / "classified.parquet", index=False)
    pd.DataFrame(
        [
            {
                "client": "CDA", "machine": "camion", "component": "motor", "essay": essay,
                "oilHourRange": "LT_1000", "LIC": None, "LIM": None, "LSM": lsm, "LSC": lsc,
                "min_value": 0.0, "GroupElement": group, "sample_count": 50,
                "calculation_date": "2026-08-05T11:07:45",
            }
            for essay, lsm, lsc, group in (
                ("Hierro", 57.0, 66.0, "Desgaste"),
                ("Silicio", 6.0, 8.0, "Contaminante"),
                ("Calcio", 2000.0, 2400.0, "Aditivo"),
                ("Zinc", 1400.0, 1600.0, "Aditivo"),
                ("Fósforo", 1300.0, 1500.0, "Aditivo"),
            )
        ]
    ).to_parquet(oil / "stewart_limits_four.parquet", index=False)
    return DashboardDataRepository(tmp_path)


def _alert_context_repository(tmp_path) -> DashboardDataRepository:
    """One alert with its trigger and companions, each with the limits it really has."""
    detail = tmp_path / "telemetry" / "golden" / "cda"
    detail.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "AlertID": alert, "Alert_Index": 0, "Alert_TimeStart": start,
                "Trigger": "EngCoolTemp", "TimeStart": moment, "Unit": "T_18",
                "EngCoolTemp_Value": 100.0 + offset,
                "EngCoolTemp_Upper_Limit": 105.0,
                "EngOilPres_Value": 320.0 - offset,
                "EngOilPres_Lower_Limit": 310.0,
                "RAftrclrTemp_Value": 80.0,
                "RAftrclrTemp_Upper_Limit": 102.0,
            }
            for alert, start, moment, offset in (
                ("3", "2026-06-01", "2026-06-01T10:00:00", 1.0),
                ("7", "2026-07-01", "2026-07-01T10:00:00", 2.0),
                ("7", "2026-07-01", "2026-07-01T10:05:00", 4.0),
            )
        ]
    ).to_csv(detail / "alerts_detail_wide_with_gps.csv", index=False)
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


def test_group_radar_pins_each_threshold_to_a_fixed_radius(tmp_path):
    """Rings must be circles, which is why the scale is 0-100 and not a ratio.

    Normalizing by one threshold cannot do this: on production data LSC/LSM spans 1.0 to
    8.5, so the outer ring would come out as a jagged shape instead of a reference.
    """
    registry = DashboardChartRegistry(_oil_four_limit_repository(tmp_path))

    artifact = registry.render(
        "cda", "oil_essay_group_radar", {"unit_id": "T_15", "component": "motor"}
    )

    assert artifact.chart_type == "radar"
    traces = artifact.figure["data"]
    assert traces[0]["type"] == "scatterpolar"
    # Wear metals have no lower limit, so only the two upper rings are drawn.
    rings = {trace["name"]: set(trace["r"]) for trace in traces if "Límite" in trace["name"] or "L" == trace["name"][:1]}
    assert rings["LSC (Superior Condenatorio)"] == {80}
    assert rings["LSM (Superior Marginal)"] == {60}
    assert "LIC (Inferior Condenatorio)" not in rings

    # Raw measurements and the five-tier status stay in the summary, so the agent quotes
    # the measured number and never the normalized radius.
    hierro = artifact.summary["essays"]["Hierro"]
    assert hierro["value"] == 65.0
    assert hierro["status"] == "Superior Marginal"
    assert hierro["LIC"] is None


def test_group_radar_splits_by_element_group(tmp_path):
    """Wear, contaminant and additive answer different questions and never share axes."""
    registry = DashboardChartRegistry(_oil_four_limit_repository(tmp_path))

    artifact = registry.render(
        "cda", "oil_essay_group_radar", {"unit_id": "T_15", "component": "motor"}
    )

    # Only wear reaches three essays in the fixture; the rest are reported as skipped
    # rather than rendered as an unreadable two-axis radar.
    assert artifact.summary["groups_rendered"] == ["Desgaste"]
    assert artifact.summary["groups_skipped_few_essays"] == {
        "Contaminante": 1,
        "Fisico Quimico": 1,
    }
    assert artifact.summary["dashboard_section"] == "Monitoreo > Aceite > Detalle"


def test_group_radar_needs_a_unit_and_real_limits(tmp_path):
    registry = DashboardChartRegistry(_oil_four_limit_repository(tmp_path))

    with pytest.raises(CampbellDataError, match="requiere unit_id"):
        registry.render("cda", "oil_essay_group_radar")
    with pytest.raises(CampbellDataError, match="Sin muestras de aceite"):
        registry.render("cda", "oil_essay_group_radar", {"unit_id": "T_99"})


def test_component_heatmap_crosses_units_and_components(tmp_path):
    registry = DashboardChartRegistry(_telemetry_repository(tmp_path))

    artifact = registry.render("cda", "telemetry_component_heatmap")

    assert artifact.chart_type == "heatmap"
    assert artifact.figure["data"][0]["type"] == "heatmap"
    assert artifact.summary["units"] == 2
    assert artifact.summary["components"] == 2
    assert "menor indica peor" in artifact.summary["note"]


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


def test_registry_covers_the_shapes_the_dashboard_offers():
    """The shapes that survived the retirement of the score-based charts.

    `gauge` and `histogram` left with `unit_health_gauge` and `oil_severity_histogram`: both
    plotted internal scores, which the product decided not to surface. Asserting their
    absence keeps a future re-add deliberate instead of accidental.
    """
    kinds = {definition.chart_type for definition in CHART_DEFINITIONS}
    assert {"radar", "treemap", "heatmap", "line", "pie", "bar", "stacked_bar"} <= kinds
    assert "gauge" not in kinds
    assert "histogram" not in kinds


def test_every_chart_declares_context_and_a_dashboard_destination():
    """`use_when` is what the agent reads to choose; the route is what the user follows.

    A chart missing either is invisible to the picker or a dead end for the reader, so this
    fails at definition time rather than in a conversation.
    """
    for definition in CHART_DEFINITIONS:
        assert definition.use_when, f"{definition.chart_id} sin use_when"
        assert definition.dashboard_route.startswith("/"), definition.chart_id
        assert definition.dashboard_section, f"{definition.chart_id} sin seccion"


# ------------------------------------------------- historial de aceite y contexto de alerta


def test_history_panels_pair_the_essays_that_are_read_together(tmp_path):
    """The pairs are diagnostic, not the element groups.

    Iron with the particle index, silicon with aluminium: splitting those by GroupElement
    would separate exactly the variables that only mean something side by side.
    """
    registry = DashboardChartRegistry(_oil_history_repository(tmp_path))

    artifact = registry.render(
        "cda", "oil_history_panels", {"unit_id": "T_15", "component": "motor"}
    )

    panels = artifact.summary["panels"]
    assert panels["Hierro & PQ"] == ["Hierro", "Índice PQ"]
    assert panels["Silicio & Aluminio"] == ["Silicio", "Aluminio"]
    # Additive panels are derived from the spreadsheet, split so the lines stay readable.
    assert "Aditivos: Calcio, Zinc & Fósforo" in panels
    assert artifact.summary["samples"] == 3
    assert artifact.summary["dashboard_section"] == "Monitoreo > Aceite > Detalle"


def test_history_panels_keep_a_series_that_has_no_limit(tmp_path):
    """`Combustible` carries no threshold by contract; the series is still the answer.

    Dropping the panel would read as missing data when what is missing is the limit.
    """
    registry = DashboardChartRegistry(_oil_history_repository(tmp_path))

    artifact = registry.render("cda", "oil_history_panels", {"unit_id": "T_15"})

    assert artifact.summary["panels"]["Combustible & Agua"] == ["Combustible"]
    assert not any(key.startswith("Combustible") for key in artifact.summary["limits_drawn"])
    assert "Hierro.LSC" in artifact.summary["limits_drawn"]


def test_alert_context_plots_the_trigger_with_its_companions(tmp_path):
    """A trigger read alone is how one high value becomes the wrong work order."""
    registry = DashboardChartRegistry(_alert_context_repository(tmp_path))

    artifact = registry.render(
        "cda", "alert_context_signals", {"unit_id": "T_18", "alert_id": "7"}
    )

    assert artifact.summary["trigger"] == "EngCoolTemp"
    assert artifact.summary["trigger_label"] == "Temperatura del refrigerante del motor"
    # Trigger first, then companions in declared order of relevance.
    assert artifact.summary["signals_plotted"][0] == "EngCoolTemp"
    assert "EngOilPres" in artifact.summary["signals_plotted"]
    # Pressures alarm on the low side, temperatures on the high side.
    assert artifact.summary["limits"]["EngCoolTemp"] == {"superior": 105.0}
    assert artifact.summary["limits"]["EngOilPres"] == {"inferior": 310.0}


def test_alert_context_falls_back_to_the_newest_alert(tmp_path):
    """"¿Por qué se alertó este equipo?" must resolve without the user knowing an id."""
    registry = DashboardChartRegistry(_alert_context_repository(tmp_path))

    artifact = registry.render("cda", "alert_context_signals", {"unit_id": "T_18"})

    assert artifact.summary["alert_id"] == "7"
    with pytest.raises(CampbellDataError, match="requiere unit_id"):
        registry.render("cda", "alert_context_signals")
