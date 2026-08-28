"""W34-05 — Modificar Filtros: Alertas Detalle drops the telemetry-presence
filter and gains an inclusive "fecha desde" filter.

Semantics under test (explicit, per the W34 plan): fecha desde is inclusive,
no date means no lower bound, an invalid date degrades to "no lower bound"
rather than raising. The date is interpreted as a Chile calendar day
(W34-06) — its midnight boundary is converted to UTC before comparing
against Timestamp.
"""

from pathlib import Path

import pandas as pd
import pytest

from dashboard.tabs.tab_alerts_detail import create_layout
from dashboard.callbacks.alerts_callbacks import (
    filter_alert_dropdown_by_criteria,
    populate_detail_filter_options,
)
from src.data.loaders import _load_alerts_data_cached


def _write_alerts_csv(tmp_path: Path, rows: list[dict]) -> None:
    alerts_path = tmp_path / "alerts" / "golden" / "capstone" / "consolidated_alerts.csv"
    alerts_path.parent.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(alerts_path, index=False)


def _base_row(fusion_id: str, timestamp: str, unit: str = "CA-42") -> dict:
    return {
        "FusionID": fusion_id,
        "Timestamp": timestamp,
        "UnitId": unit,
        "sistema": "motor",
        "subsistema": "engine",
        "componente": "engine",
        "Trigger_type": "Telemetria",
        "TribologyID": None,
    }


@pytest.fixture
def three_alerts(tmp_path, monkeypatch):
    """Three alerts spanning three days, all at Chile-local midday (16:00
    UTC = 12:00 Chile in July, winter/no-DST) so the fecha-desde boundary
    tests aren't sensitive to time-of-day, only to the date."""
    _write_alerts_csv(
        tmp_path,
        [
            _base_row("F-1", "2026-07-08T16:00:00Z"),
            _base_row("F-2", "2026-07-09T16:00:00Z"),
            _base_row("F-3", "2026-07-10T16:00:00Z"),
        ],
    )
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    _load_alerts_data_cached.cache_clear()
    yield
    _load_alerts_data_cached.cache_clear()


# ---------------------------------------------------------------------------
# 1. Layout: the telemetry filter is gone, the date filter exists
# ---------------------------------------------------------------------------

def test_telemetry_filter_id_is_not_in_the_layout_tree():
    layout_str = str(create_layout())
    assert "detail-filter-telemetry" not in layout_str


def test_date_from_filter_id_is_in_the_layout_tree():
    layout_str = str(create_layout())
    assert "detail-filter-date-from" in layout_str


def test_tribology_filter_still_present_after_removing_telemetry():
    """Only the telemetry filter is removed — its sibling must survive."""
    layout_str = str(create_layout())
    assert "detail-filter-tribology" in layout_str


# ---------------------------------------------------------------------------
# 2. Callback wiring: telemetry Input is gone, not just the layout id
# ---------------------------------------------------------------------------

def test_callback_signature_no_longer_takes_a_telemetry_argument():
    import inspect

    params = list(inspect.signature(filter_alert_dropdown_by_criteria).parameters)
    assert "has_telemetry" not in params
    assert "start_date" in params


# ---------------------------------------------------------------------------
# 3. Fecha desde — inclusive, empty = no limit, out-of-range, invalid
# ---------------------------------------------------------------------------

def test_no_date_means_no_lower_bound(three_alerts):
    options = filter_alert_dropdown_by_criteria(
        units=["CA-42"], sistemas=None, start_date=None, has_tribology=None,
        client="capstone", current_value=None,
    )
    assert len(options) == 3


def test_date_from_excludes_alerts_before_the_chosen_chile_calendar_day(three_alerts):
    """2026-07-09 16:00 UTC = 2026-07-09 12:00 Chile (July, no DST, UTC-4).
    Fecha desde = 2026-07-09 must include F-2 (that day) and F-3 (later),
    exclude F-1 (the day before)."""
    options = filter_alert_dropdown_by_criteria(
        units=["CA-42"], sistemas=None, start_date="2026-07-09",
        has_tribology=None, client="capstone", current_value=None,
    )
    labels = {opt["value"] for opt in options}
    assert labels == {"F-2", "F-3"}


def test_date_from_boundary_is_exact(tmp_path, monkeypatch):
    """One alert exactly at the Chile-midnight boundary of the chosen date
    must be included — the inclusive edge the plan explicitly requires."""
    _write_alerts_csv(
        tmp_path,
        [
            # 2026-07-09 04:00:00 UTC = 2026-07-09 00:00:00 Chile exactly
            # (July, UTC-4) — the inclusive boundary itself.
            _base_row("F-boundary", "2026-07-09T04:00:00Z"),
            # One second before the boundary, in Chile terms.
            _base_row("F-before", "2026-07-09T03:59:59Z"),
        ],
    )
    monkeypatch.setenv("DASHBOARD_DATA_ROOT", str(tmp_path))
    _load_alerts_data_cached.cache_clear()
    try:
        options = filter_alert_dropdown_by_criteria(
            units=["CA-42"], sistemas=None, start_date="2026-07-09",
            has_tribology=None, client="capstone", current_value=None,
        )
    finally:
        _load_alerts_data_cached.cache_clear()

    labels = [opt["value"] for opt in options]
    assert "F-boundary" in labels
    assert "F-before" not in labels


def test_date_after_the_last_alert_returns_no_options_without_raising(three_alerts):
    options = filter_alert_dropdown_by_criteria(
        units=["CA-42"], sistemas=None, start_date="2027-01-01",
        has_tribology=None, client="capstone", current_value=None,
    )
    assert options == []


def test_invalid_date_degrades_to_no_lower_bound_instead_of_raising(three_alerts):
    """An unparseable date must not take down the whole dropdown — every
    alert still shows, same as if no date had been picked."""
    options = filter_alert_dropdown_by_criteria(
        units=["CA-42"], sistemas=None, start_date="not-a-date",
        has_tribology=None, client="capstone", current_value=None,
    )
    assert len(options) == 3


def test_date_on_a_chile_dst_transition_degrades_to_no_lower_bound(three_alerts):
    """Critical-review follow-up: Chile's DST transition happens at local
    midnight, so a calendar date can itself be a nonexistent local instant
    (e.g. 2026-09-06 00:00 Chile does not exist — clocks spring forward from
    2026-09-05 24:00 straight to 2026-09-06 01:00). to_utc_naive used to
    raise pytz.NonExistentTimeError for this on the scalar (date-boundary)
    path even though its own Series path already degraded to NaT for the
    same input shape — the fix must not silently empty the whole dropdown
    either, only skip the unrepresentable bound, same as an invalid string."""
    options = filter_alert_dropdown_by_criteria(
        units=["CA-42"], sistemas=None, start_date="2026-09-06",
        has_tribology=None, client="capstone", current_value=None,
    )
    assert len(options) == 3


def test_date_filter_combines_with_unit_filter(three_alerts):
    """fecha desde is one more AND-combined criterion, not a replacement for
    the others."""
    options = filter_alert_dropdown_by_criteria(
        units=["CA-99"],  # no alert has this unit
        sistemas=None, start_date="2026-07-01",
        has_tribology=None, client="capstone", current_value=None,
    )
    assert options == []
