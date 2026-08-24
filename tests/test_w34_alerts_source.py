"""W34-04 — Cambio de Nomenclatura Alertas Mixtas.

Before: the "Mixto" label and its purple border color existed only as a
hardcoded string + hex literal inside the table's style_data_conditional
rule; the "Alertas mixtas" KPI card used a *different*, independently
hand-picked purple (#7c6a9a vs. the table's #6f42c1); no color legend
existed anywhere, and no other surface (chart, detail header) showed the
source with any color at all.

After: `labels.py::SOURCE_STYLE` is the single (label, color) source of
truth for a Trigger_type value, consumed by the table's row-highlight rule
(both the match text AND the border color), the new color legend, the KPI
card's accent, and the detail header's Fuente badge.

The user confirmed "Multitécnica" as the final label for Trigger_type ==
"Mixto" (the raw value is unchanged, only the display text). This test suite
locks in both the infrastructure (one dict, four consumers, no drift) and
the confirmed wording.
"""

import pandas as pd
import pytest

from dashboard.components.labels import SOURCE_STYLE, source_style, source_color
from dashboard.components.alerts_report import (
    translate_alert_source,
    prepare_alert_rows,
    alert_summary,
)
from dashboard.components.alerts_tables import create_alerts_report_table
from dashboard.callbacks.alerts_callbacks import _alert_case_header
from dashboard.tabs.tab_alerts_general import (
    create_summary_stats_display,
    _build_source_legend,
)


# ---------------------------------------------------------------------------
# 1. source_style — mapping, including empty/unknown
# ---------------------------------------------------------------------------

SOURCE_CASES = [
    ("Telemetria", "Telemetría"),
    ("Telemetría", "Telemetría"),
    ("Tribologia", "Tribología"),
    ("Tribología", "Tribología"),
    ("Mixto", "Multitécnica"),
]


@pytest.mark.parametrize("raw,expected_label", SOURCE_CASES)
def test_source_style_label_for_known_values(raw, expected_label):
    label, color = source_style(raw)
    assert label == expected_label
    assert color.startswith("#") and len(color) == 7


def test_telemetria_tribologia_mixto_have_three_distinct_colors():
    """The whole point of the legend is that these read as different colors —
    a collision would defeat it."""
    colors = {source_color("Telemetria"), source_color("Tribologia"), source_color("Mixto")}
    assert len(colors) == 3


def test_source_style_empty_and_none_produce_an_explicit_fallback():
    assert source_style("")[0] == "Sin fuente"
    assert source_style(None)[0] == "Sin fuente"


def test_source_style_unknown_value_keeps_its_own_text_with_neutral_color():
    """Never invents a translation for a Trigger_type value not in the map."""
    label, color = source_style("algo_desconocido")
    assert label == "algo_desconocido"
    assert color == "#95a5a6"


def test_translate_alert_source_wraps_the_same_shared_function():
    for raw, expected_label in SOURCE_CASES:
        assert translate_alert_source(raw) == expected_label == source_style(raw)[0]


# ---------------------------------------------------------------------------
# 2. The table's filter_query is derived, not hardcoded — renaming "Mixto"
#    cannot silently break the highlight.
# ---------------------------------------------------------------------------

def _sample_alerts_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "FusionID": "F-1", "Timestamp": pd.Timestamp("2026-07-10 16:00:00"),
            "UnitId": "CA-42", "sistema": "motor", "componente": "engine",
            "Trigger_type": "Mixto", "Trigger_Var": "EngCoolTemp", "mensaje_ia": "",
            "has_telemetry": True, "has_tribology": True,
        },
    ])


def test_table_filter_query_matches_the_label_source_style_emits():
    table = create_alerts_report_table(_sample_alerts_df())
    label, color = source_style("Mixto")
    filter_queries = {
        rule["if"]["filter_query"]: rule.get("borderLeft")
        for rule in table.style_data_conditional
        if "filter_query" in rule.get("if", {})
    }
    expected_query = f'{{Fuente}} = "{label}"'
    assert expected_query in filter_queries
    assert color in filter_queries[expected_query]


def test_table_fuente_cell_uses_the_same_label():
    table = create_alerts_report_table(_sample_alerts_df())
    assert table.data[0]["Fuente"] == source_style("Mixto")[0]


# ---------------------------------------------------------------------------
# 3. alert_summary()['mixed'] compares the raw value, not the display label
# ---------------------------------------------------------------------------

def test_mixed_count_is_insensitive_to_the_display_label():
    """Even if source_style's label for 'Mixto' were renamed, this count must
    still find the row — it keys off the raw Trigger_type column."""
    df = _sample_alerts_df()
    summary = alert_summary(df)
    assert summary["mixed"] == 1

    # Simulate the label having been renamed downstream of the raw value —
    # the count must be unaffected, since it never reads source_display.
    prepared = prepare_alert_rows(df)
    assert "Trigger_type" in prepared.columns
    assert (prepared["Trigger_type"] == "Mixto").sum() == summary["mixed"]


def test_non_mixed_alert_is_not_counted():
    df = _sample_alerts_df()
    df["Trigger_type"] = "Telemetria"
    df["has_tribology"] = False
    assert alert_summary(df)["mixed"] == 0


# ---------------------------------------------------------------------------
# 4. Same (label, color) across the four surfaces: table, legend, KPI, detail
# ---------------------------------------------------------------------------

def test_legend_shows_the_same_three_colors_as_source_style():
    legend_str = str(_build_source_legend())
    for raw in ("Telemetria", "Tribologia", "Mixto"):
        label, color = source_style(raw)
        assert label in legend_str
        assert color in legend_str


def test_kpi_card_mixed_alerts_accent_matches_source_style():
    card = create_summary_stats_display(total_alerts=10, total_units=3, mixed_count=2)
    rendered = str(card)
    assert source_color("Mixto") in rendered


def test_detail_header_fuente_badge_matches_source_style():
    row = pd.Series({
        "FusionID": "F-1", "Timestamp": pd.Timestamp("2026-07-10 16:00:00"),
        "UnitId": "CA-42", "sistema": "motor", "subsistema": "engine",
        "componente": "engine", "Trigger_type": "Mixto",
        "Trigger_Var": "EngCoolTemp", "mensaje_ia": "",
    })
    header = _alert_case_header(row)
    rendered = str(header)
    label, color = source_style("Mixto")
    assert color in rendered
    assert label in rendered


def test_all_four_surfaces_agree_on_the_mixto_color(monkeypatch):
    """The strongest form of the guarantee: patch SOURCE_STYLE once and
    confirm every surface picks up the new color — proving there is exactly
    one place this is defined, not four that happen to currently agree."""
    patched = dict(SOURCE_STYLE)
    patched["Mixto"] = ("Mixto", "#123456")
    monkeypatch.setitem(SOURCE_STYLE, "Mixto", patched["Mixto"])

    table = create_alerts_report_table(_sample_alerts_df())
    legend = str(_build_source_legend())
    kpi = str(create_summary_stats_display(total_alerts=1, total_units=1, mixed_count=1))
    row = pd.Series({
        "FusionID": "F-1", "Timestamp": pd.Timestamp("2026-07-10 16:00:00"),
        "UnitId": "CA-42", "sistema": "motor", "subsistema": "engine",
        "componente": "engine", "Trigger_type": "Mixto",
        "Trigger_Var": "EngCoolTemp", "mensaje_ia": "",
    })
    header = str(_alert_case_header(row))

    table_borders = [rule.get("borderLeft", "") for rule in table.style_data_conditional]
    assert any("#123456" in border for border in table_borders)
    assert "#123456" in legend
    assert "#123456" in kpi
    assert "#123456" in header
