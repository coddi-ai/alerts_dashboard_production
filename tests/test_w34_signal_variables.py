"""W34-11 — Ajustar Variables en Serie de Tiempo.

Covers two guarantees:

1. `SIGNAL_LABELS` (src/charts/signals.py) is a single, immutable source of
   truth. It used to be a plain dict mutated at import time by
   `dashboard/components/alerts_charts.py` (`FEATURE_NAMES_ES.update(...)`),
   so the catalogue's actual contents depended on import order. That mutation
   site is gone; these tests make sure it cannot come back unnoticed.
2. `select_plottable_signals` (alerts_charts.py) — the rule that decides which
   telemetry signals get their own panel in the Alertas > Detalle sensor
   trends chart — only allows signals that are both catalogued and not shown
   elsewhere (KPI cards) or explicitly omitted from the catalogue.
"""

import pytest

from dashboard.components.alerts_charts import (
    FEATURE_NAMES_ES,
    KPI_ONLY_SIGNALS,
    OMITTED_FEATURES,
    select_plottable_signals,
)
from src.charts.signals import OMITTED_SIGNALS, SIGNAL_LABELS


# ---------------------------------------------------------------------------
# 1. Catalogue identity and immutability
# ---------------------------------------------------------------------------

def test_feature_names_es_is_signal_labels_not_a_copy():
    """The alias is a tested contract (see test_campbell_ai_grounding.py) —
    re-asserted here because W34-11 is exactly the change that could break it."""
    assert FEATURE_NAMES_ES is SIGNAL_LABELS


def test_signal_labels_rejects_mutation():
    with pytest.raises(TypeError):
        SIGNAL_LABELS["NuevaSenal"] = "Nueva etiqueta"


def test_signal_labels_rejects_update():
    with pytest.raises(AttributeError):
        SIGNAL_LABELS.update({"NuevaSenal": "Nueva etiqueta"})


def test_feature_names_es_rejects_mutation_too():
    """Same object as SIGNAL_LABELS, so the same guarantee must hold through
    either name — this is the exact call site the old bug used."""
    with pytest.raises(TypeError):
        FEATURE_NAMES_ES["NuevaSenal"] = "Nueva etiqueta"


def test_capstone_codes_are_permanently_catalogued_not_injected():
    """These used to only exist after alerts_charts.py ran its `.update()` at
    import time. They must now be intrinsic to the catalogue itself."""
    expected = {
        "engine_speed_rpm": "Velocidad del motor",
        "engine_load_pct": "Carga del motor",
        "oil_level_pct": "Nivel de aceite",
        "TCOutTemp": "Temperatura de salida del convertidor de torque",
        "egt_05_c": "Temperatura de escape cilindro 05",
    }
    for code, label in expected.items():
        assert SIGNAL_LABELS.get(code) == label


def test_catalogue_survives_reimport_of_every_known_importer():
    """Import-order independence: re-importing every module that used to (or
    still does) touch this catalogue must not change its contents."""
    import importlib

    import dashboard.components.alerts_charts as alerts_charts
    import dashboard.components.telemetry_charts as telemetry_charts
    import dashboard.components.predictive_config as predictive_config

    before = dict(SIGNAL_LABELS)
    importlib.reload(alerts_charts)
    importlib.reload(telemetry_charts)
    importlib.reload(predictive_config)
    after = dict(SIGNAL_LABELS)

    assert before == after
    assert len(after) == len(before)


# ---------------------------------------------------------------------------
# 2. select_plottable_signals — known / unknown / omitted / KPI-only
# ---------------------------------------------------------------------------

def test_known_signal_is_plottable():
    plottable, uncatalogued = select_plottable_signals(["EngCoolTemp"])
    assert plottable == ["EngCoolTemp"]
    assert uncatalogued == []


def test_unknown_signal_is_excluded_and_reported():
    """A `_Value` column with no catalogue entry never gets a panel — but it
    is surfaced as 'uncatalogued' so the gap is discoverable, not silent."""
    plottable, uncatalogued = select_plottable_signals(["TotallyUnknownCode"])
    assert plottable == []
    assert uncatalogued == ["TotallyUnknownCode"]


def test_mixed_known_and_unknown_signals():
    plottable, uncatalogued = select_plottable_signals(
        ["EngCoolTemp", "TotallyUnknownCode", "oil_level_pct"]
    )
    assert plottable == ["EngCoolTemp", "oil_level_pct"]
    assert uncatalogued == ["TotallyUnknownCode"]


def test_omitted_signal_never_gets_a_panel_and_is_not_flagged_uncatalogued():
    """GroundSpd/EngLoad are a deliberate policy exclusion (OMITTED_SIGNALS),
    not a cataloguing gap — they must not show up in `uncatalogued` either,
    or every render would log a spurious warning for a known, intentional
    omission."""
    for code in OMITTED_SIGNALS:
        plottable, uncatalogued = select_plottable_signals([code])
        assert plottable == []
        assert uncatalogued == []


def test_kpi_only_signal_is_excluded_even_though_catalogued():
    """EngSpd has a real catalogue label ('Velocidad del motor') but must
    stay out of the chart because it already has its own KPI card — the
    exact case a plain 'is it catalogued?' check would get wrong."""
    assert "EngSpd" in SIGNAL_LABELS  # precondition: it IS catalogued
    plottable, uncatalogued = select_plottable_signals(["EngSpd"])
    assert plottable == []
    assert uncatalogued == []  # excluded by policy, not "uncatalogued"


def test_kpi_only_signals_constant_matches_documented_two():
    assert set(KPI_ONLY_SIGNALS) == {"Payload", "EngSpd"}


def test_catalogued_variable_absent_from_source_produces_no_panel():
    """A variable can be perfectly catalogued and still absent from a given
    alert's data — select_plottable_signals only ever sees what the caller
    passes in (columns actually present), so it naturally emits nothing for
    a signal the caller never included."""
    plottable, uncatalogued = select_plottable_signals([])
    assert plottable == []
    assert uncatalogued == []


def test_plottable_order_matches_input_order():
    """Order is the caller's (column order in the source), not alphabetical —
    changing this would silently reorder chart panels."""
    plottable, _ = select_plottable_signals(["TCOutTemp", "EngCoolTemp", "AirFltr"])
    assert plottable == ["TCOutTemp", "EngCoolTemp", "AirFltr"]


def test_omitted_features_derives_from_omitted_signals_single_source():
    assert OMITTED_FEATURES == list(OMITTED_SIGNALS)
