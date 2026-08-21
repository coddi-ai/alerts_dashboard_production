"""W34-13 — Corregir Fuentes disponibles en Estado x Unidad.

The defect: `create_critical_equipment_summary_table`'s Telemetría column
defaulted to `telem_status = 'Normal'` unconditionally — a client with the
underlying service disabled (or a unit with zero records under an enabled
service) still showed a green "Normal" badge, reading as a confirmed-healthy
finding when nothing had actually been checked.

The fix adds a `client` parameter, gated through
`config.client_services.is_service_enabled`, and two distinct "no signal"
states:
  - "Sin Fuente": the client doesn't have the underlying service enabled at
    all (Telemetría reads monitoring-alerts OR overview-data-freshness;
    Tribología reads monitoring-oil).
  - "Sin Datos": the service is enabled, but this specific unit has no
    record — a per-unit gap, not a per-client one.

Scoping note: the original plan sketched a *third* state ("estado
desconocido" — a row present but with no resolvable status). No real data
was available to confirm this behaves differently from "Sin Datos" in
practice, so it was deliberately not implemented as a separate label —
recorded in the W34 handoff, not silently dropped.

No column is hidden when a source is unavailable (the badge itself carries
the state) — this sidesteps the header/row cell-count desync risk the plan
flagged for the "hide the column" alternative, at the cost of the column
staying visible with a distinct badge instead of disappearing.
"""

import pandas as pd
import pytest

import dashboard.callbacks.overview_general_callbacks as overview_module
from dashboard.callbacks.overview_general_callbacks import create_critical_equipment_summary_table


def _sample_frames():
    df_telemetry = pd.DataFrame([{"unit_id": "U1"}, {"unit_id": "U2"}])
    df_oil = pd.DataFrame()
    df_alerts = pd.DataFrame()
    df_maintenance = pd.DataFrame()
    df_freshness = pd.DataFrame()
    return df_telemetry, df_oil, df_alerts, df_maintenance, df_freshness


def _badge_text_for_column(html_div, column_index: int) -> list[str]:
    """Extract each row's rendered badge text ('🟢 Normal', '▪️ Sin Fuente', ...)
    for one column (0=Unidad, 1=Telemetría, 2=Tribología, 3=Descripción)."""
    table = html_div.children  # the html.Table itself
    tbody = table.children[1]
    texts = []
    for tr in tbody.children:
        cell = tr.children[column_index]
        texts.append(str(cell))
    return texts


# ---------------------------------------------------------------------------
# 1. Real clients from config/client_services.json — no monkeypatching
# ---------------------------------------------------------------------------

def test_enex_has_no_telemetry_signal_and_never_shows_normal():
    """ENEX has neither monitoring-alerts nor overview-data-freshness enabled
    — this table's Telemetría column has genuinely nothing to read for any
    unit. Must show 'Sin Fuente', never the old default 'Normal'."""
    frames = _sample_frames()
    result = create_critical_equipment_summary_table(*frames, client="ENEX")
    telemetria_badges = _badge_text_for_column(result, 1)
    assert all("Normal" not in badge for badge in telemetria_badges)
    assert all("Sin Fuente" in badge for badge in telemetria_badges)


def test_capstone_shows_real_telemetria_despite_lacking_the_dedicated_service():
    """CAPSTONE has no 'monitoring-telemetry' service, but DOES have
    monitoring-alerts and overview-data-freshness — the two sources this
    TABLE's Telemetría column actually reads from. It must show real
    (computed) status, not 'Sin Fuente' — the column's data dependency is
    not the same as the nav tab of the same name."""
    frames = _sample_frames()
    result = create_critical_equipment_summary_table(*frames, client="CAPSTONE")
    telemetria_badges = _badge_text_for_column(result, 1)
    assert all("Sin Fuente" not in badge for badge in telemetria_badges)


def test_cda_unaffected_all_services_enabled():
    """CDA has every relevant service enabled — behavior must be unchanged:
    units with no alert/freshness record show the per-unit 'Sin Datos', not
    a client-level 'Sin Fuente'."""
    frames = _sample_frames()
    result = create_critical_equipment_summary_table(*frames, client="CDA")
    telemetria_badges = _badge_text_for_column(result, 1)
    assert all("Sin Fuente" not in badge for badge in telemetria_badges)


# ---------------------------------------------------------------------------
# 2. Synthetic client (monkeypatched) — no real client currently lacks
#    monitoring-oil, so this is the only way to exercise that branch.
# ---------------------------------------------------------------------------

@pytest.fixture
def no_oil_client(monkeypatch):
    """A client with telemetry sources enabled but tribology disabled."""
    real = overview_module.is_service_enabled

    def fake(client_id, service_id):
        if client_id == "NOOILCO" and service_id == "monitoring-oil":
            return False
        if client_id == "NOOILCO":
            return service_id in ("monitoring-alerts", "overview-data-freshness")
        return real(client_id, service_id)

    monkeypatch.setattr(overview_module, "is_service_enabled", fake)
    return "NOOILCO"


def test_synthetic_client_without_oil_service_shows_sin_fuente_for_tribologia(no_oil_client):
    frames = _sample_frames()
    result = create_critical_equipment_summary_table(*frames, client=no_oil_client)
    tribologia_badges = _badge_text_for_column(result, 2)
    assert all("Sin Fuente" in badge for badge in tribologia_badges)


def test_synthetic_client_without_oil_still_shows_real_telemetria(no_oil_client):
    """Losing one source must not blank out the other."""
    frames = _sample_frames()
    result = create_critical_equipment_summary_table(*frames, client=no_oil_client)
    telemetria_badges = _badge_text_for_column(result, 1)
    assert all("Sin Fuente" not in badge for badge in telemetria_badges)


# ---------------------------------------------------------------------------
# 3. Per-unit "Sin Datos": service enabled, but this unit has no record
# ---------------------------------------------------------------------------

def test_unit_with_service_enabled_but_no_record_shows_sin_datos_not_normal():
    """CDA (all services on), but the unit has zero alerts and no freshness
    row — 'Sin Datos', distinct from both 'Normal' (checked, healthy) and
    'Sin Fuente' (client-level, service off)."""
    df_telemetry = pd.DataFrame([{"unit_id": "GHOST-1"}])
    df_oil = pd.DataFrame()
    df_alerts = pd.DataFrame()  # no alert history at all
    df_maintenance = pd.DataFrame()
    df_freshness = pd.DataFrame()  # no freshness record either

    result = create_critical_equipment_summary_table(
        df_telemetry, df_oil, df_alerts, df_maintenance, df_freshness, client="CDA"
    )
    badges = _badge_text_for_column(result, 1)
    assert len(badges) == 1
    assert "Sin Datos" in badges[0]
    assert "Normal" not in badges[0]
    assert "Sin Fuente" not in badges[0]


def test_sin_datos_and_sin_fuente_are_visually_distinct_states(no_oil_client):
    """The whole point of having two labels is that they render differently —
    a collision would defeat the distinction. STATUS_STYLE is nested inside
    create_critical_equipment_summary_table (not independently importable),
    so this compares the two states as they actually render: a client
    missing monitoring-oil entirely ('Sin Fuente') vs. a unit with the
    service enabled but no record ('Sin Datos')."""
    sin_fuente_result = create_critical_equipment_summary_table(*_sample_frames(), client=no_oil_client)
    sin_fuente_badge = _badge_text_for_column(sin_fuente_result, 2)[0]

    df_telemetry = pd.DataFrame([{"unit_id": "GHOST-1"}])
    sin_datos_result = create_critical_equipment_summary_table(
        df_telemetry, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), client="CDA",
    )
    sin_datos_badge = _badge_text_for_column(sin_datos_result, 1)[0]

    assert "Sin Fuente" in sin_fuente_badge
    assert "Sin Datos" in sin_datos_badge
    assert sin_fuente_badge != sin_datos_badge  # different label AND style


# ---------------------------------------------------------------------------
# 4. priority: a real alarm on one side survives regardless of the other
#    side's availability (never suppressed by treating "Sin Fuente" as 0)
# ---------------------------------------------------------------------------

def test_real_critical_status_is_not_suppressed_by_an_unavailable_other_column(no_oil_client):
    """A unit with a real Anormal alert (Telemetría) on a client missing
    monitoring-oil (Tribología='Sin Fuente') must still rank as high-priority
    overall — the unavailable column must never drag it down to 'nothing to
    see here'."""
    df_telemetry = pd.DataFrame([{"unit_id": "U-CRIT"}])
    df_oil = pd.DataFrame()
    df_alerts = pd.DataFrame([{
        "UnitId": "U-CRIT", "componente": "motor", "Trigger_type": "Telemetria",
        "Timestamp": pd.Timestamp("2026-07-10 12:00:00"), "sistema": "motor",
    }])
    df_maintenance = pd.DataFrame()
    df_freshness = pd.DataFrame()

    result = create_critical_equipment_summary_table(
        df_telemetry, df_oil, df_alerts, df_maintenance, df_freshness,
        client=no_oil_client,
    )
    tribologia_badges = _badge_text_for_column(result, 2)
    assert "Sin Fuente" in tribologia_badges[0]
    # The row must not have silently fallen to the "Operación normal" message.
    # NOTE: indexing a Dash Component itself (e.g. `component[1]`) is an
    # ID-based lookup, not positional — `.children[i]` on a Component or on
    # a plain list attribute is positional; the two must not be confused
    # (see _badge_text_for_column for the working pattern).
    description_cell = _badge_text_for_column(result, 3)[0]
    assert "Operación normal" not in description_cell


# ---------------------------------------------------------------------------
# 5. Column/cell count stays consistent across every scenario (no column
#    hiding => no header/row desync risk)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("client", ["CDA", "ENEX", "CAPSTONE"])
def test_header_and_row_cell_counts_match_across_every_client_scenario(client):
    frames = _sample_frames()
    result = create_critical_equipment_summary_table(*frames, client=client)
    table = result.children
    header_cells = table.children[0].children.children  # Thead > Tr > [Th...]
    body_rows = table.children[1].children
    assert len(header_cells) == 4  # Unidad, Telemetría, Tribología, Descripción
    for row in body_rows:
        assert len(row.children) == len(header_cells)
