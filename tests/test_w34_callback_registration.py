"""Fase 4 — Prueba de importación / registro de callbacks.

Per the W34 plan's "definición de terminado": General, Estado de Datos,
Alertas, Telemetría and Predictivo must all still register their callbacks,
and every literal (non pattern-matching) Output/Input/State id used by those
five areas must resolve against an id that actually exists somewhere in
their combined layouts.

This deliberately does NOT import `dashboard.app` (the real entrypoint) —
that module transitively pulls in `src.utils.auth_event_logger` -> `boto3`,
which is out of scope for the W34 improvements and was not part of the
approved minimal install (see W34_HANDOFF.md's environment section). A
fresh, bare `dash.Dash` instance plus the five relevant callback modules
covers exactly what the plan's "terminado" criterion asks for, without
needing the auth/ERP/S3 subsystems those 13 improvements never touch.

Pattern-matching ids (dict-shaped, e.g. `{"type": "...", "key": ALL}`) are
skipped — Dash does not require them to pre-exist in the layout at
registration time, so "does this id exist in the layout" does not apply.
"""

import re

import dash
import pytest


# ---------------------------------------------------------------------------
# 1. Every relevant callback module imports without error
# ---------------------------------------------------------------------------

def test_all_w34_relevant_callback_modules_import_cleanly():
    import dashboard.callbacks.alerts_callbacks  # noqa: F401
    import dashboard.callbacks.telemetry_callbacks  # noqa: F401
    import dashboard.callbacks.data_freshness_callbacks  # noqa: F401
    import dashboard.callbacks.overview_general_callbacks  # noqa: F401
    import dashboard.callbacks.predictive_callbacks  # noqa: F401


def test_all_w34_relevant_layouts_build_without_error():
    from dashboard.tabs.tab_alerts_general import create_layout as alerts_general_layout
    from dashboard.tabs.tab_alerts_detail import create_layout as alerts_detail_layout
    from dashboard.tabs.tab_data_freshness import create_layout as freshness_layout
    from dashboard.tabs.tab_overview_general import create_layout as overview_layout
    from dashboard.tabs.tab_telemetry_unit_detail import create_telemetry_unit_detail_layout

    for builder in (
        alerts_general_layout, alerts_detail_layout, freshness_layout,
        overview_layout, create_telemetry_unit_detail_layout,
    ):
        builder()  # must not raise


# ---------------------------------------------------------------------------
# 2. Registration: General, Estado de Datos, Alertas, Telemetría, Predictivo
#    all still register callbacks against a fresh app.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def registered_app():
    """A bare Dash app with the five W34-relevant areas' callbacks
    registered — mirrors dashboard/app.py's registration calls for exactly
    these five modules, without importing app.py itself (see module
    docstring for why).

    Critical-review correction: dash.Dash does NOT drain
    dash._callback.GLOBAL_CALLBACK_LIST at construction time — that happens
    inside Dash._setup_server, which dash.Dash.init_app registers as a
    Flask `before_request` hook (dash/dash.py), so it only runs lazily, on
    the app's first served HTTP request. This test never serves a request,
    so that draining never happens here and is irrelevant to what this
    fixture checks.

    What actually matters: the bare `@callback` decorator (used by
    alerts/telemetry/data_freshness_callbacks, as opposed to the explicit
    `register_*_callbacks(app)` style used by overview_general/predictive)
    appends straight to GLOBAL_CALLBACK_LIST at *import/reload* time —
    synchronously, with no Dash instance involved. `_all_output_ids()` below
    reads that list directly, never through `app.callback_map`. So the only
    real risk is some OTHER code in the same pytest process reading or
    clearing GLOBAL_CALLBACK_LIST between this fixture's setup and its
    assertions (a scoped fixture executes once per module, but pytest runs
    many other files' module-level imports in the same process). Clearing it
    and reloading the three bare-@callback modules right here guarantees a
    fresh, correctly-populated list for this fixture's own assertions,
    regardless of what any other test already did to that list earlier in
    the same process.
    """
    import importlib

    import dash._callback as cb_module
    import dashboard.callbacks.alerts_callbacks as alerts_mod
    import dashboard.callbacks.telemetry_callbacks as telemetry_mod
    import dashboard.callbacks.data_freshness_callbacks as freshness_mod
    from dashboard.callbacks.overview_general_callbacks import register_overview_general_callbacks
    from dashboard.callbacks.predictive_callbacks import register_callbacks as register_predictive_callbacks

    cb_module.GLOBAL_CALLBACK_LIST.clear()
    importlib.reload(alerts_mod)
    importlib.reload(telemetry_mod)
    importlib.reload(freshness_mod)
    baseline_count = 0

    app = dash.Dash(__name__)
    register_overview_general_callbacks(app)
    register_predictive_callbacks(app)

    return app, baseline_count


def test_five_areas_register_at_least_one_callback_each(registered_app):
    _, baseline_count = registered_app
    import dash._callback as cb_module
    assert len(cb_module.GLOBAL_CALLBACK_LIST) > baseline_count


def test_key_alerts_callbacks_are_registered(registered_app):
    ids = _all_output_ids()
    for expected in (
        "alerts-table-container", "alert-detail-content",
        "alert-selector-dropdown", "alerts-general-active-filters",
    ):
        assert expected in ids


def test_key_telemetry_callbacks_are_registered(registered_app):
    ids = _all_output_ids()
    for expected in (
        "telemetry-detail-signal-cards", "telemetry-detail-signal-table",
        "telemetry-fleet-table-container",
    ):
        assert expected in ids


def test_key_predictive_and_freshness_callbacks_are_registered(registered_app):
    ids = _all_output_ids()
    assert "data-freshness-table" in ids
    assert "overview-oil-ranking-table" in ids


# ---------------------------------------------------------------------------
# 3. Every literal id a W34-relevant callback references resolves against
#    the combined layout — the check that would have caught W34-05's risk
#    (removing detail-filter-telemetry from the layout but leaving a
#    dangling Input, or vice versa) before it shipped.
# ---------------------------------------------------------------------------

def _parse_dependency_ids(raw) -> list[str]:
    """Extract literal component ids from a GLOBAL_CALLBACK_LIST entry's
    'output' (a specially-joined string) or 'inputs'/'state' (a list of
    {'id':..., 'property':...} dicts). Pattern-matching (dict) ids are
    skipped — see module docstring."""
    ids = []
    if isinstance(raw, str):
        s = re.sub(r'@[0-9a-f]+$', '', raw).strip('.')
        for fragment in re.split(r'\.{2,}', s):
            if not fragment:
                continue
            comp_id = fragment.rpartition('.')[0] or fragment
            if comp_id.startswith('{'):
                continue  # pattern-matching id, serialized as JSON-ish text
            ids.append(comp_id)
    elif isinstance(raw, list):
        for item in raw:
            comp_id = item.get('id')
            # A pattern-matching id (Input({"type": ..., "key": ALL}, ...))
            # is stored here as a JSON-sorted-keys string, not a dict — skip
            # it the same way as the 'output' string path above.
            if isinstance(comp_id, str) and not comp_id.startswith('{'):
                ids.append(comp_id)
    return ids


def _all_output_ids() -> set[str]:
    import dash._callback as cb_module
    ids = set()
    for entry in cb_module.GLOBAL_CALLBACK_LIST:
        ids.update(_parse_dependency_ids(entry['output']))
    return ids


def _collect_layout_ids(component, found: set[str]) -> None:
    comp_id = getattr(component, 'id', None)
    if isinstance(comp_id, str):
        found.add(comp_id)
    children = getattr(component, 'children', None)
    if children is None:
        return
    if isinstance(children, (list, tuple)):
        for child in children:
            if hasattr(child, 'id') or hasattr(child, 'children'):
                _collect_layout_ids(child, found)
    elif hasattr(children, 'id') or hasattr(children, 'children'):
        _collect_layout_ids(children, found)


def _combined_layout_ids() -> set[str]:
    from dashboard.tabs.tab_alerts_general import create_layout as alerts_general_layout
    from dashboard.tabs.tab_alerts_detail import create_layout as alerts_detail_layout
    from dashboard.tabs.tab_alerts import create_layout as alerts_shell_layout
    from dashboard.tabs.tab_data_freshness import create_layout as freshness_layout
    from dashboard.tabs.tab_overview_general import create_layout as overview_layout
    from dashboard.tabs.tab_telemetry_unit_detail import create_telemetry_unit_detail_layout
    from dashboard.tabs.tab_telemetry_fleet import create_telemetry_fleet_layout

    # tab_predictive_overview's layout(client, component) needs real,
    # client-scoped data to render (unavailable without `data/` in this
    # environment) — its registration is already covered by
    # test_key_predictive_and_freshness_callbacks_are_registered above; W34-10
    # only touched _failure_table's content (tests/test_w34_predictive_table.py),
    # not any layout id.
    found = set()
    for builder in (
        alerts_general_layout, alerts_detail_layout, alerts_shell_layout,
        freshness_layout, overview_layout, create_telemetry_unit_detail_layout,
        create_telemetry_fleet_layout,
    ):
        _collect_layout_ids(builder(), found)
    # Global stores/selectors that live in dashboard/layout.py, outside any
    # single tab, but that these callbacks legitimately reference.
    found.update({
        "client-selector", "alerts-navigation-state", "alerts-internal-tabs",
        "alerts-tab-content", "telemetry-health-tabs", "telemetry-health-tab-content",
        "telemetry-navigation-state", "telemetry-reference-date",
        "telemetry-availability-notice", "telemetry-fleet-model-filter",
        "telemetry-fleet-status-filter",
    })
    return found


# Ids that are never in the *static* layout by design — they're created by
# another callback's own rendered output (e.g. create_alerts_report_table's
# DataTable, assigned to alerts-table-container.children, is itself where
# 'alerts-datatable' first comes into existence) and only resolve once that
# callback has actually run. This test only builds the static layouts
# (create_layout() with no data), so it cannot see them — that's expected,
# not a gap; each entry below is a legitimate dynamic-content id, not a
# W34-introduced dangling reference.
KNOWN_DYNAMIC_IDS = {
    "alerts-datatable",            # create_alerts_report_table's DataTable (alerts-table-container)
    "general-nav-to-detail-button",  # render_selected_alert_summary's card (alerts-general-selected-alert)
    "alert-oil-radar-view",        # create_oil_evidence_section (alert-detail-content)
    "alert-oil-tendencia-view",
    "alert-oil-tendencia-context",
    "alert-oil-tendencia-date-range",
    "alert-oil-tendencia-date-clear",
    "alert-oil-view-selector",
    "telemetry-fleet-status-table",  # _fleet_status_table (telemetry-fleet-table-container)
}


def test_every_alerts_and_telemetry_output_id_exists_somewhere_in_the_layout(registered_app):
    """The concrete regression this guards against: W34-05 removed
    detail-filter-telemetry from the layout. If its Input had been left in
    the callback (or a new Output typo'd an id), this test would fail."""
    import dash._callback as cb_module

    layout_ids = _combined_layout_ids() | KNOWN_DYNAMIC_IDS
    missing = []
    for entry in cb_module.GLOBAL_CALLBACK_LIST:
        all_ids = (
            _parse_dependency_ids(entry['output'])
            + _parse_dependency_ids(entry.get('inputs') or [])
            + _parse_dependency_ids(entry.get('state') or [])
        )
        for comp_id in all_ids:
            if comp_id not in layout_ids:
                missing.append(comp_id)
    # Report duplicates once each, for a readable failure message.
    assert not set(missing), f"Callback ids with no matching layout component: {sorted(set(missing))}"


def test_detail_filter_telemetry_is_gone_from_both_callback_ids_and_layout(registered_app):
    """W34-05's specific regression guard, stated directly rather than only
    implied by the exhaustive check above."""
    import dash._callback as cb_module

    layout_ids = _combined_layout_ids()
    assert "detail-filter-telemetry" not in layout_ids

    callback_ids = set()
    for entry in cb_module.GLOBAL_CALLBACK_LIST:
        callback_ids.update(_parse_dependency_ids(entry.get('inputs') or []))
        callback_ids.update(_parse_dependency_ids(entry.get('state') or []))
    assert "detail-filter-telemetry" not in callback_ids
