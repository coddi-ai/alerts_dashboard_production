"""W34-01 — Unificar Componentes, and shared-catalogue checks for W34-12.

W34-01: Alertas already had one component-label function
(`translate_component_label`); General's `overview-component-filter` built
its own label with a bare `.title()` on the raw, uppercased-for-dedup value
instead of calling it — "post_engine"/"POST_ENGINE" read "Posterior al motor"
in Alertas but "Post_Engine" in General. Both now go through the same
function; the raw value used for joins/filters is untouched.

W34-12 (bottom of this file) — Unificar Nomenclatura de Nombres de
Variables: `predictive_config.py::TELEMETRY_LABELS` used to spell out its
own label for every signal code, independently of
`src/charts/signals.py::SIGNAL_LABELS` (shared by Alertas y Telemetría). A
systematic diff found ~20 codes that only disagreed in *style* (unified by
reading straight from SIGNAL_LABELS) and 5 that named genuinely *different*
things — escalated, then resolved by the user's explicit domain decisions
and unified the same way; see documentation/general/W34_HANDOFF.md.
"""

import pytest

from dashboard.components.labels import translate_component_label
from dashboard.components.alerts_report import translate_alert_component
from dashboard.callbacks.overview_general_callbacks import build_component_filter_options
from dashboard.components.predictive_config import TELEMETRY_LABELS
from src.charts.signals import SIGNAL_LABELS


# ---------------------------------------------------------------------------
# 1. translate_component_label — same label regardless of casing/source
# ---------------------------------------------------------------------------

KNOWN_ALIASES = [
    ("engine", "Motor"),
    ("Engine", "Motor"),
    ("ENGINE", "Motor"),
    ("motor", "Motor"),
    ("post_engine", "Posterior al motor"),
    ("POST_ENGINE", "Posterior al motor"),
    ("posterior_al_motor", "Posterior al motor"),
    ("rifle", "Conducto principal de aceite"),
    ("RIFLE", "Conducto principal de aceite"),
    ("crankcase", "Cárter"),
    ("CRANKCASE", "Cárter"),
    ("carter", "Cárter"),
    ("cárter", "Cárter"),
    ("lubrication", "Lubricación"),
    ("Lubrication", "Lubricación"),
    ("lubricacion", "Lubricación"),
]


@pytest.mark.parametrize("raw,expected", KNOWN_ALIASES)
def test_known_alias_maps_to_the_same_label_regardless_of_casing(raw, expected):
    assert translate_component_label(raw) == expected


def test_alias_with_spaces_or_hyphens_normalizes_like_underscores():
    assert translate_component_label("post engine") == "Posterior al motor"
    assert translate_component_label("post-engine") == "Posterior al motor"
    assert translate_component_label("POST ENGINE") == "Posterior al motor"


def test_empty_or_none_component_has_an_explicit_label():
    assert translate_component_label("") == "Sin componente"
    assert translate_component_label(None) == "Sin componente"
    assert translate_component_label("   ") == "Sin componente"


def test_uncatalogued_component_gets_a_readable_fallback_not_raw_text():
    """A component not yet in the map must not echo raw
    SCREAMING_SNAKE_CASE (which is what General's dropdown produced before
    W34-01 for anything routed through .upper() first)."""
    assert translate_component_label("UNKNOWN_THING") == "Unknown Thing"
    assert translate_component_label("some-new-part") == "Some New Part"


def test_alerts_alias_wraps_the_same_shared_function():
    """translate_alert_component (Alertas) and translate_component_label
    (General) must be the exact same rule, not two maintained copies."""
    for raw, expected in KNOWN_ALIASES:
        assert translate_alert_component(raw) == expected == translate_component_label(raw)


# ---------------------------------------------------------------------------
# 2. General's component filter: label unified, raw join key untouched
# ---------------------------------------------------------------------------

def test_component_filter_label_matches_alertas_for_the_same_raw_value():
    """The dropdown option's label must read identically to how Alertas
    would display the same raw component."""
    data = {"alerts": [{"componente": "post_engine"}], "oil": []}
    options = build_component_filter_options(data)
    assert options == [{"label": "Posterior al motor", "value": "POST_ENGINE"}]
    assert options[0]["label"] == translate_alert_component("post_engine")


def test_component_filter_value_stays_raw_uppercase_for_joins():
    """`value` is what create_critical_equipment_summary_table's
    `component_filter` comparisons match against (`.str.upper() ==
    component_filter.upper()`) — it must never become the translated label."""
    data = {"alerts": [{"componente": "rifle"}], "oil": []}
    options = build_component_filter_options(data)
    assert options[0]["value"] == "RIFLE"
    assert options[0]["label"] != "RIFLE"


def test_component_filter_deduplicates_across_alerts_and_oil_sources():
    """Same component, different casing, from the two different source
    dataframes — must collapse into a single dropdown entry, not two."""
    data = {
        "alerts": [{"componente": "Motor"}],
        "oil": [{"component_details": [{"component": "motor"}]}],
    }
    options = build_component_filter_options(data)
    assert len(options) == 1
    assert options[0] == {"label": "Motor", "value": "MOTOR"}


def test_component_filter_excludes_desconocido():
    data = {"alerts": [{"componente": "Desconocido"}], "oil": []}
    assert build_component_filter_options(data) == []


def test_component_filter_handles_missing_or_malformed_input():
    assert build_component_filter_options(None) == []
    assert build_component_filter_options({}) == []
    assert build_component_filter_options({"alerts": [], "oil": []}) == []
    # A component_details entry that isn't a dict must not raise.
    malformed = {"alerts": [], "oil": [{"component_details": ["not-a-dict", None]}]}
    assert build_component_filter_options(malformed) == []


def test_component_filter_options_sorted_by_raw_value():
    """Sort order is on the raw (uppercase) value — deterministic and
    independent of the translated label's alphabetical order."""
    data = {"alerts": [{"componente": "rifle"}, {"componente": "engine"}], "oil": []}
    options = build_component_filter_options(data)
    assert [o["value"] for o in options] == ["ENGINE", "RIFLE"]


# ---------------------------------------------------------------------------
# W34-12 — TELEMETRY_LABELS unified against SIGNAL_LABELS. All 5 originally
# escalated semantic conflicts were resolved by the user's explicit domain
# decisions (documentation/general/W34_HANDOFF.md) and are now unified like
# every other code — this set is intentionally empty, not removed, so a
# future *new* conflict has an obvious place to land instead of silently
# failing test_telemetry_labels_match_signal_labels_except_escalated_conflicts.
# ---------------------------------------------------------------------------

# Must only ever shrink (a domain decision resolving one) — never grow
# silently. Currently empty: all 5 original conflicts were resolved.
W34_12_ESCALATED_CONFLICTS = set()

# Codes TELEMETRY_LABELS defines that SIGNAL_LABELS has no entry for at all
# (not a conflict — there is nothing to unify against). DeltaExh was resolved
# by domain decision to be the same concept as SIGNAL_LABELS["RtLtExhTemp"]
# and is no longer telemetry-only.
W34_12_TELEMETRY_ONLY_CODES = {"gear_mismatch"}


@pytest.mark.parametrize("client", ["cda", "capstone"])
def test_telemetry_labels_match_signal_labels_except_escalated_conflicts(client):
    for code, label in TELEMETRY_LABELS[client].items():
        if code in W34_12_TELEMETRY_ONLY_CODES or code in W34_12_ESCALATED_CONFLICTS:
            continue
        assert code in SIGNAL_LABELS, f"{code!r} should be catalogued in SIGNAL_LABELS"
        assert label == SIGNAL_LABELS[code], (
            f"{code!r} diverged: TELEMETRY_LABELS[{client!r}]={label!r} "
            f"vs SIGNAL_LABELS={SIGNAL_LABELS[code]!r} — either it's a real "
            f"style unification that broke, or a new conflict that needs "
            f"escalating (add it to W34_12_ESCALATED_CONFLICTS with a reason)."
        )


def test_escalated_conflicts_are_confirmed_still_divergent():
    """If any of these five now happens to match SIGNAL_LABELS (e.g. someone
    resolved it with a real domain decision), it must be removed from the
    escalated set — this list may only shrink, never silently stay stale."""
    still_divergent = set()
    for client in ("cda", "capstone"):
        for code in W34_12_ESCALATED_CONFLICTS:
            label = TELEMETRY_LABELS[client].get(code)
            if label is not None and label != SIGNAL_LABELS.get(code):
                still_divergent.add(code)
    assert still_divergent == W34_12_ESCALATED_CONFLICTS


def test_telemetry_only_codes_have_no_signal_labels_entry():
    """Confirms these two are correctly 'nothing to unify against', not
    silently-uncaught divergences."""
    for code in W34_12_TELEMETRY_ONLY_CODES:
        assert code not in SIGNAL_LABELS


def test_oil_filter_and_oil_diff_pressure_are_distinguishable():
    """Quality-review follow-up: applying the Fase 7 domain decision for
    oil_diff_pressure_psi ("...del filtro de aceite") accidentally collided
    with oil_filter_dp_psi's pre-existing, unrelated label — the same exact
    text for two different, independently-alertable sensors (confirmed real
    and co-occurring in config/features/capstone.yaml's oil_pressure
    functional group). Confirmed by domain decision: oil_filter_dp_psi is the
    filter's differential pressure; oil_diff_pressure_psi is the engine oil's
    differential pressure."""
    assert SIGNAL_LABELS["oil_filter_dp_psi"] != SIGNAL_LABELS["oil_diff_pressure_psi"]
    assert "filtro" in SIGNAL_LABELS["oil_filter_dp_psi"].lower()
    assert "motor" in SIGNAL_LABELS["oil_diff_pressure_psi"].lower()


def test_no_new_undeclared_divergence_exists():
    """The exhaustive form of the guarantee: every TELEMETRY_LABELS code is
    accounted for by exactly one of the three buckets (unified, escalated,
    telemetry-only) — nothing falls through uncategorized."""
    for client in ("cda", "capstone"):
        for code in TELEMETRY_LABELS[client]:
            in_signal_labels = code in SIGNAL_LABELS
            is_escalated = code in W34_12_ESCALATED_CONFLICTS
            is_telemetry_only = code in W34_12_TELEMETRY_ONLY_CODES
            assert in_signal_labels != is_telemetry_only  # exactly one must hold
            if in_signal_labels and not is_escalated:
                assert TELEMETRY_LABELS[client][code] == SIGNAL_LABELS[code]


def test_resolve_client_dicts_falls_back_to_signal_labels_for_uncurated_codes():
    """Quality-review follow-up: TELEMETRY_LABELS is a curated per-client
    subset, not the full catalogue — a signal already in SIGNAL_LABELS but
    not yet added as a key here used to render as its raw code in Predictivo
    (tab_predictive_evidence.py's `telem_labels.get(signal, signal)`), instead
    of the same label Alertas/Telemetría already show for it."""
    from dashboard.tabs.tab_predictive_evidence import _resolve_client_dicts

    code_not_in_cda_telemetry_labels = next(
        code for code in SIGNAL_LABELS if code not in TELEMETRY_LABELS["cda"]
    )
    _, telem_labels, _ = _resolve_client_dicts("cda", "motor")
    assert telem_labels[code_not_in_cda_telemetry_labels] == SIGNAL_LABELS[code_not_in_cda_telemetry_labels]

    # The curated per-client entry still wins over the SIGNAL_LABELS fallback
    # for any code that IS in TELEMETRY_LABELS.
    curated_code = next(iter(TELEMETRY_LABELS["cda"]))
    assert telem_labels[curated_code] == TELEMETRY_LABELS["cda"][curated_code]
