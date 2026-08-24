"""W34-06 — Cuadrar Instante de Alertas.

Alertas normalized event timestamps to UTC-naive at the loading boundary but
then displayed that UTC clock reading directly, while Estado de Datos
converted the same kind of value to Chile time first — the same real-world
instant read with a 3-4h difference depending on which tab you were looking
at. The fix: every comparison/window/filter stays UTC-naive (unchanged); a
single explicit step (`to_local_naive`/`format_local`) converts to
America/Santiago only at the point something is shown to a person.

Covers: mixed input formats normalize to the same UTC instant, local
conversion is DST-correct for both Chilean seasons, display call sites
(table, dropdown, header) agree, and the telemetry evidence window still
selects the same rows after the fix (comparisons never touch local time).
"""

from datetime import timedelta

import pandas as pd
import pytest

from src.utils.date_utils import format_local, to_local_naive, to_utc_naive
from dashboard.components.alerts_report import prepare_alert_rows
from dashboard.components.alerts_tables import create_alerts_report_table
from dashboard.components.alerts_charts import create_sensor_trends_chart_golden


# ---------------------------------------------------------------------------
# 1. to_utc_naive — mixed input formats produce the same instant
# ---------------------------------------------------------------------------

# All five strings name the same real-world instant: 2026-07-10 16:00:00 UTC.
MIXED_FORMAT_TIMESTAMPS = [
    "2026-07-10 16:00:00",           # naive -> treated as UTC (today's default)
    "2026-07-10T16:00:00Z",          # Zulu suffix
    "2026-07-10T12:00:00-04:00",     # explicit negative offset (Capstone-style)
    "2026-07-10T13:00:00-03:00",     # different offset, same instant
    "2026-07-10T16:00:00.000",       # ISO with milliseconds, naive
]


@pytest.mark.parametrize("raw", MIXED_FORMAT_TIMESTAMPS)
def test_mixed_formats_normalize_to_the_same_utc_instant(raw):
    normalized = to_utc_naive(raw)
    assert normalized == pd.Timestamp("2026-07-10 16:00:00")
    assert normalized.tzinfo is None


@pytest.mark.parametrize("raw", MIXED_FORMAT_TIMESTAMPS)
def test_each_format_normalizes_consistently_as_a_whole_column(raw):
    """loaders.py calls to_utc_naive() on an entire CSV column. A single
    client's export is usually internally consistent (one format per
    source), but a genuinely mixed column is the realistic risk this
    function exists to handle — see
    test_a_genuinely_mixed_column_normalizes_every_row below — so this is a
    narrower sanity check, not proof the mixed case is unreachable."""
    series = pd.Series([raw, raw])
    normalized = to_utc_naive(series)
    assert (normalized == pd.Timestamp("2026-07-10 16:00:00")).all()
    assert normalized.dt.tz is None


def test_a_genuinely_mixed_column_normalizes_every_row():
    """Found during W34 visual QA: a "consolidated" CSV that accumulates
    rows over time plausibly mixes legacy naive rows with newer
    offset-aware ISO rows in the very same Timestamp column (e.g. CDA's
    alerts CSV, built from a synthetic fixture reproducing this exact
    layout, silently dropped 2 of 5 real-looking alert rows before this
    test existed). pandas' bulk `pd.to_datetime(series, utc=True)` infers
    one format from the array and NaTs every row that doesn't match it,
    even though each value parses fine in isolation — to_utc_naive must
    retry those instead of losing the row.
    """
    series = pd.Series(MIXED_FORMAT_TIMESTAMPS + [None, float("nan")])
    normalized = to_utc_naive(series)
    same_instant = normalized.iloc[:len(MIXED_FORMAT_TIMESTAMPS)]
    assert (same_instant == pd.Timestamp("2026-07-10 16:00:00")).all()
    assert normalized.dt.tz is None
    assert normalized.iloc[len(MIXED_FORMAT_TIMESTAMPS):].isna().all()


# ---------------------------------------------------------------------------
# 1b. to_utc_naive scalar branch — DST transition dates (critical-review
#     follow-up: the scalar branch didn't pass ambiguous=/nonexistent= the
#     way its own Series branch above already does, so a date landing on
#     Chile's own transition instant raised pytz.NonExistentTimeError
#     instead of returning NaT like the Series path).
# ---------------------------------------------------------------------------

def test_to_utc_naive_scalar_matches_series_on_a_nonexistent_local_date():
    """2026-09-06 00:00 Chile does not exist (spring-forward). The scalar
    and Series code paths must agree: both NaT, neither raises."""
    nonexistent_date = pd.Timestamp("2026-09-06")
    scalar_result = to_utc_naive(nonexistent_date, source_tz="America/Santiago")
    series_result = to_utc_naive(pd.Series([nonexistent_date]), source_tz="America/Santiago")
    assert pd.isna(scalar_result)
    assert series_result.isna().all()


def test_to_utc_naive_scalar_still_works_for_an_ordinary_date():
    """The DST fix must not regress the common case."""
    ordinary_date = pd.Timestamp("2026-07-09")
    result = to_utc_naive(ordinary_date, source_tz="America/Santiago")
    assert not pd.isna(result)
    assert result == pd.Timestamp("2026-07-09 04:00:00")  # Chile winter, UTC-4


# ---------------------------------------------------------------------------
# 2. to_local_naive / format_local — DST-correct, both Chilean seasons
# ---------------------------------------------------------------------------

def test_local_conversion_is_dst_correct_in_chilean_summer():
    """January is Chilean summer (DST in effect): UTC-3."""
    local = to_local_naive(pd.Timestamp("2026-01-15 12:00:00"))
    assert local == pd.Timestamp("2026-01-15 09:00:00")


def test_local_conversion_is_dst_correct_in_chilean_winter():
    """July is Chilean winter (no DST): UTC-4."""
    local = to_local_naive(pd.Timestamp("2026-07-10 16:00:00"))
    assert local == pd.Timestamp("2026-07-10 12:00:00")


def test_format_local_matches_manual_conversion():
    utc_instant = pd.Timestamp("2026-07-10 16:00:00")
    assert format_local(utc_instant) == "10/07/2026 12:00"


def test_format_local_handles_missing_and_invalid_values():
    assert format_local(None) == "-"
    assert format_local(pd.NaT) == "-"
    assert format_local("not a date") == "-"


def test_format_local_vectorizes_over_a_series_with_nat():
    series = pd.Series([pd.Timestamp("2026-07-10 16:00:00"), pd.NaT])
    formatted = format_local(series)
    assert formatted.iloc[0] == "10/07/2026 12:00"
    assert formatted.iloc[1] == "-"


def test_local_conversion_does_not_compound_on_repeated_formatting():
    """Idempotency guard: formatting must not shift the value a second time —
    this is exactly the 'conversion doble' the objective rules out."""
    utc_instant = pd.Timestamp("2026-07-10 16:00:00")
    first = format_local(utc_instant)
    second = format_local(utc_instant)  # same UTC input, not the local output
    assert first == second == "10/07/2026 12:00"


# ---------------------------------------------------------------------------
# 3. Every display surface agrees: prepare_alert_rows / table / dropdown
# ---------------------------------------------------------------------------

def _alert_row(timestamp: str) -> dict:
    return {
        "FusionID": "F-1",
        "TelemetryID": "T-1",
        "Timestamp": timestamp,
        "UnitId": "CA-42",
        "sistema": "motor",
        "subsistema": "engine",
        "componente": "engine",
        "Trigger_type": "Telemetria",
        "Trigger_Var": "EngCoolTemp",
        "mensaje_ia": "",
        "has_telemetry": True,
        "has_tribology": False,
    }


@pytest.mark.parametrize("raw", MIXED_FORMAT_TIMESTAMPS)
def test_prepare_alert_rows_date_display_is_the_same_local_instant(raw):
    """The header (`_alert_case_header` reads `date_display`) shows the same
    instant regardless of which of the five equivalent input formats the
    source used."""
    frame = prepare_alert_rows(pd.DataFrame([_alert_row(raw)]))
    assert frame.loc[0, "date_display"] == "10/07/2026 12:00"


def test_alerts_report_table_fecha_column_matches_prepare_alert_rows():
    """The live executive table (create_alerts_report_table) must show the
    exact same instant as the header — both must go through the same
    UTC-naive-internal / local-at-display pipeline."""
    alerts_df = prepare_alert_rows(
        pd.DataFrame([_alert_row("2026-07-10T12:00:00-04:00")])
    )
    table = create_alerts_report_table(alerts_df)
    assert table.data[0]["Fecha"] == "10/07/2026 12:00"


def test_alerts_report_table_handles_missing_timestamp_without_raising():
    row = _alert_row("2026-07-10T12:00:00-04:00")
    row["Timestamp"] = None
    alerts_df = pd.DataFrame([row])
    alerts_df["Timestamp"] = pd.to_datetime(alerts_df["Timestamp"])  # all-NaT column
    table = create_alerts_report_table(alerts_df)
    assert table.data[0]["Fecha"] == "-"


def test_filter_alert_rows_date_from_uses_chile_calendar_day_not_utc():
    """Quality-review follow-up: filter_alert_rows backs the Alertas General
    tab's own top-level date-range filter (alerts-date-range-picker) and used
    to compare start_date/end_date via a bare pd.to_datetime against the
    already-UTC-naive Timestamp column -- the exact W34-06 defect this file's
    other tests cover for every other Alertas surface, just missed here.

    An alert at 23:30 Chile local time on 2026-07-31 is already 2026-08-01 in
    UTC. A user filtering "desde 01/08/2026" expects the Chile calendar day,
    so this alert (which happened the Chile day before) must NOT be included."""
    from dashboard.components.alerts_report import filter_alert_rows

    late_july_31_chile = to_utc_naive(
        pd.Timestamp("2026-07-31 23:30:00"), source_tz="America/Santiago"
    )
    row = _alert_row(str(late_july_31_chile))
    alerts_df = pd.DataFrame([row])

    filtered_from_aug_1 = filter_alert_rows(alerts_df, start_date="2026-08-01")
    assert filtered_from_aug_1.empty

    filtered_from_jul_31 = filter_alert_rows(alerts_df, start_date="2026-07-31")
    assert len(filtered_from_jul_31) == 1


def test_filter_alert_rows_on_a_dst_transition_date_keeps_alerts_instead_of_emptying():
    """Critical-review follow-up: 2026-09-06 00:00 Chile does not exist
    (spring-forward), so to_utc_naive returns NaT for that boundary. A naive
    `Timestamp >= NaT` comparison is always False, which would silently
    empty the WHOLE result — worse than the crash it replaced. The bound
    must be skipped instead, same as an unparseable date string."""
    from dashboard.components.alerts_report import filter_alert_rows

    row = _alert_row("2026-09-10 12:00:00")  # after the transition, unrelated to it
    alerts_df = pd.DataFrame([row])

    filtered = filter_alert_rows(alerts_df, start_date="2026-09-06")
    assert len(filtered) == 1


# ---------------------------------------------------------------------------
# 4. The evidence window still selects the same rows (comparisons stay UTC)
# ---------------------------------------------------------------------------

def _telemetry_fixture(alert_time_utc: pd.Timestamp) -> pd.DataFrame:
    """One row inside the ±90/+10 window, one just outside each edge."""
    offsets_minutes = [-95, -89, -30, 0, 9, 15]  # first and last are outside
    rows = []
    for offset in offsets_minutes:
        rows.append(
            {
                "TimeStart": alert_time_utc + timedelta(minutes=offset),
                "Trigger": "EngCoolTemp",
                "EngCoolTemp_Value": 90.0,
                "EngCoolTemp_Upper_Limit": 100.0,
                "EngCoolTemp_Lower_Limit": None,
                "State": "Operacional",
            }
        )
    return pd.DataFrame(rows)


def test_evidence_window_keeps_the_same_row_count_after_local_conversion():
    """W34-06's highest-risk failure mode: shifting the chart's time axis to
    local must not shift the +/-90/+10 min windowing, or the evidence goes
    silently empty. The window comparison happens in UTC-naive before the
    local shift; only 4 of the 6 fixture rows (-89, -30, 0, +9) are inside."""
    alert_time = pd.Timestamp("2026-07-10 16:00:00")  # UTC-naive, as loaders produce
    data = _telemetry_fixture(alert_time)

    figure = create_sensor_trends_chart_golden(
        alert_data=data,
        feature_names=["EngCoolTemp"],
        unit_id="CA-42",
        alert_time=alert_time,
        feature_name_map={"EngCoolTemp": "Temperatura del refrigerante del motor"},
    )

    # One trace per gap-segment of the single plotted feature; total points
    # across all of them must equal the 4 in-window rows, not all 6.
    value_trace_points = sum(
        len(trace.x) for trace in figure.data
        if trace.name == "Temperatura del refrigerante del motor"
    )
    assert value_trace_points == 4


def test_evidence_chart_axis_shows_local_time_not_utc():
    """The chart's own x-axis (not just the surrounding page) must read the
    same local instant as the table/header — that's what 'coincide ... en
    tabla, encabezado, gráfico' requires, not just the hover text."""
    alert_time = pd.Timestamp("2026-07-10 16:00:00")  # 12:00 Chile (winter, UTC-4)
    data = _telemetry_fixture(alert_time)

    figure = create_sensor_trends_chart_golden(
        alert_data=data,
        feature_names=["EngCoolTemp"],
        unit_id="CA-42",
        alert_time=alert_time,
        feature_name_map={"EngCoolTemp": "Temperatura del refrigerante del motor"},
    )

    value_trace = next(
        trace for trace in figure.data
        if trace.name == "Temperatura del refrigerante del motor"
    )
    plotted_times = pd.to_datetime(list(value_trace.x))
    # The alert itself (offset 0) must appear at 12:00 local, not 16:00 UTC.
    assert pd.Timestamp("2026-07-10 12:00:00") in plotted_times.tolist()
    assert pd.Timestamp("2026-07-10 16:00:00") not in plotted_times.tolist()
