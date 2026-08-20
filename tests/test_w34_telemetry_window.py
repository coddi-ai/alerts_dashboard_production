"""W34-09 — Simplificar análisis de una señal.

Before: the view opened on the longest materialized episode (or the last 3
days with no episode) and always drew event/anomaly overlays.

After: starts at 1 day by default, no event overlays, and three buttons
(1/7/30 días) that only change the window width — see
tests/test_telemetry_report.py for the event-overlay opt-in coverage
(`show_events=True`) and the modified default-behavior tests.
"""

import inspect

import pandas as pd
import pytest

from dashboard.components.telemetry_charts import build_signal_timeseries_card
from dashboard.callbacks.telemetry_callbacks import update_signal_cards
from dashboard.tabs.tab_telemetry_unit_detail import create_telemetry_unit_detail_layout


def _raw_df(days: int = 40) -> pd.DataFrame:
    """40 days of hourly data — comfortably covers the 30-day button."""
    dates = pd.date_range("2026-06-01", periods=days * 24, freq="h")
    return pd.DataFrame({"Fecha": dates, "EngCoolTemp": range(len(dates))})


# ---------------------------------------------------------------------------
# 1. window_days controls the initial x-axis range exactly
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("window_days", [1, 7, 30])
def test_window_days_sets_the_exact_initial_range(window_days):
    raw = _raw_df()
    latest = raw["Fecha"].max()
    figure = build_signal_timeseries_card(
        "EngCoolTemp", raw, pd.DataFrame(), pd.DataFrame(), "T_01", pd.DataFrame(),
        window_days=window_days,
    )
    expected_start = latest - pd.Timedelta(days=window_days)
    assert figure.layout.xaxis.range[0] == expected_start
    assert figure.layout.xaxis.range[1] == latest


def test_window_days_clamps_to_series_start_when_series_is_shorter():
    """A 5-hour series asked for a 30-day window must clamp to its own
    start, not request a range before any data exists."""
    raw = pd.DataFrame({
        "Fecha": pd.date_range("2026-06-01", periods=5, freq="h"),
        "EngCoolTemp": range(5),
    })
    figure = build_signal_timeseries_card(
        "EngCoolTemp", raw, pd.DataFrame(), pd.DataFrame(), "T_01", pd.DataFrame(),
        window_days=30,
    )
    assert figure.layout.xaxis.range[0] == pd.Timestamp("2026-06-01 00:00:00")


def test_default_window_is_one_day():
    raw = _raw_df()
    latest = raw["Fecha"].max()
    figure = build_signal_timeseries_card(
        "EngCoolTemp", raw, pd.DataFrame(), pd.DataFrame(), "T_01", pd.DataFrame(),
    )
    assert figure.layout.xaxis.range[0] == latest - pd.Timedelta(days=1)


# ---------------------------------------------------------------------------
# 2. No overlays in the simplified view, regardless of window_days
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("window_days", [1, 7, 30])
def test_no_event_overlays_at_any_window_size(window_days):
    raw = _raw_df()
    events = pd.DataFrame([{
        "unit": "T_01", "feature": "EngCoolTemp",
        "start_time": "2026-06-05 00:00:00", "end_time": "2026-06-05 02:00:00",
        "duration_minutes": 120, "event_type_binary": "anomaly", "event_type_weighted": "warning",
    }])
    figure = build_signal_timeseries_card(
        "EngCoolTemp", raw, pd.DataFrame(), pd.DataFrame(), "T_01", events,
        window_days=window_days,
    )
    assert not figure.layout.shapes
    names = [trace.name for trace in figure.data]
    assert not any("Anomalía" in str(name) for name in names)
    assert not any("Evento" in str(name) for name in names)


# ---------------------------------------------------------------------------
# 3. Signal with no data in the requested window: empty figure, no exception
# ---------------------------------------------------------------------------

def test_window_1_day_with_no_recent_data_shows_empty_figure_without_raising():
    """All values are NaN in the raw column — dropna leaves nothing to plot,
    and the function must degrade to its empty-figure message, not raise."""
    raw = pd.DataFrame({
        "Fecha": pd.date_range("2026-06-01", periods=24, freq="h"),
        "EngCoolTemp": [None] * 24,
    })
    figure = build_signal_timeseries_card(
        "EngCoolTemp", raw, pd.DataFrame(), pd.DataFrame(), "T_01", pd.DataFrame(),
        window_days=1,
    )
    assert figure.layout.annotations
    assert "Sin datos" in figure.layout.annotations[0].text


# ---------------------------------------------------------------------------
# 4. The callback preserves unit/signal/system when the window button changes
# ---------------------------------------------------------------------------

def test_callback_signature_includes_window_days_alongside_the_others():
    """window_days is an independent Input — unit/system/signal keep their
    own Inputs above it, so changing the button never resets them (Dash only
    re-invokes the callback; it does not clear sibling Input values)."""
    params = list(inspect.signature(update_signal_cards).parameters)
    assert params == ["signal", "system", "unit", "client", "window_days"]


def test_layout_button_group_has_the_three_expected_options():
    layout_str = str(create_telemetry_unit_detail_layout())
    assert "telemetry-detail-window-days" in layout_str
    for label in ("1 día", "7 días", "30 días"):
        assert label in layout_str
