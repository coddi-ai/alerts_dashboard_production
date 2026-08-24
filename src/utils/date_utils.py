"""
Date utility functions for Multi-Technical-Alerts.

Provides helpers for date parsing and calculations.
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Union


# W34-06 — "Cuadrar Instante de Alertas". Alertas normalized event timestamps to
# UTC-naive at the loading boundary but then displayed that UTC clock reading
# directly, while Estado de Datos converted the same kind of value to Chile
# time first — the same real-world instant read with a 3-4h difference
# depending on which tab you were looking at.
#
# The fix keeps every comparison/window/filter in UTC-naive (unchanged from
# today) and adds a single, explicit conversion step for presentation only:
#   CSV/parquet -> to_utc_naive() -> [comparisons, windows, filters]
#                                  -> to_local_naive()/format_local() -> UI
# Nothing outside this module should call pytz or do its own tz_localize on an
# alert timestamp; going through these two functions is what keeps every
# surface (table, header, chart, selection) reading the same instant.
DEFAULT_DISPLAY_TZ = "America/Santiago"


def to_utc_naive(
    value: Union[pd.Series, "pd.Timestamp", str, datetime, None],
    source_tz: str = "UTC",
) -> Union[pd.Series, pd.Timestamp]:
    """Normalize a datetime-like value (or Series) to UTC, timezone-naive.

    This is the single place that decides what an alert instant "is" before
    any comparison, window or filter touches it — call it once at the loading
    boundary, never again downstream (re-parsing an already-normalized column
    is how a double conversion creeps in).

    Args:
        value: a scalar (str/datetime/Timestamp) or a pandas Series of them.
            May already carry an explicit UTC offset (Capstone's ISO
            timestamps, e.g. ``-04:00``) — that offset always wins and
            converts correctly regardless of `source_tz`.
        source_tz: timezone to assume for entries that arrive *naive* (no
            offset in the string). Defaults to "UTC", identical to this
            project's existing behavior everywhere it normalizes a timestamp
            today (`pd.to_datetime(..., utc=True)` treats a naive value as
            already being UTC). Declaring it explicitly — rather than that
            silent default — is what lets a future client whose source
            exports naive local time say so, instead of having it silently
            misread as UTC.

    Returns:
        The same shape as `value` (Series in, Series out), tz-naive, in UTC.
    """
    if source_tz == "UTC":
        # Identical to the inline calls this replaces in src/data/loaders.py.
        if isinstance(value, pd.Series):
            parsed = pd.to_datetime(value, utc=True, errors="coerce")
            # A column mixing formats — e.g. legacy naive rows alongside newer
            # offset-aware ISO rows in the same accumulating "consolidated"
            # CSV — makes pandas infer one format from the array and silently
            # NaT every row that doesn't match it, even though each value
            # parses fine on its own (verified directly: a Series with one
            # Capstone offset timestamp mixed among naive ones NaTs the
            # offset row under the bulk call, but not when parsed alone).
            # Retry only the values that came back NaT despite a non-null
            # source, one at a time, so the per-element parser runs instead
            # of the whole-array fast path.
            mismatched = parsed.isna() & value.notna()
            if mismatched.any():
                parsed = parsed.copy()
                parsed.loc[mismatched] = value.loc[mismatched].map(
                    lambda item: pd.to_datetime(item, utc=True, errors="coerce")
                )
            return parsed.dt.tz_convert(None)
        return pd.to_datetime(value, utc=True).tz_convert(None)

    if isinstance(value, pd.Series):
        parsed = pd.to_datetime(value, errors="coerce")
        localized = (
            parsed.dt.tz_localize(source_tz, ambiguous="NaT", nonexistent="NaT")
            if parsed.dt.tz is None
            else parsed.dt.tz_convert(source_tz)
        )
        return localized.dt.tz_convert("UTC").dt.tz_localize(None)

    parsed = pd.Timestamp(value)
    # Critical-review follow-up: mirror the Series branch's ambiguous/
    # nonexistent handling above — without it, a scalar date landing exactly
    # on a DST transition (Chile's own transition happens at local midnight,
    # so any date-range boundary can hit it) raised pytz's
    # NonExistentTimeError/AmbiguousTimeError instead of returning NaT like
    # its Series counterpart already does for the same input shape.
    localized = (
        parsed.tz_localize(source_tz, ambiguous="NaT", nonexistent="NaT")
        if parsed.tzinfo is None else parsed
    )
    if pd.isna(localized):
        return pd.NaT
    return localized.tz_convert("UTC").tz_localize(None)


def to_local_naive(
    value: Union[pd.Series, "pd.Timestamp", str, datetime, None],
    tz_name: str = DEFAULT_DISPLAY_TZ,
) -> Union[pd.Series, pd.Timestamp]:
    """Shift an already UTC-naive value (or Series) to `tz_name` wall-clock time.

    Strips tzinfo again after the shift, so the result composes with plain
    naive-datetime arithmetic exactly like the input did — a fixed offset
    shift does not change relative deltas, so code that only compares or
    subtracts already-shifted values (gap detection, a ±N-minute window)
    keeps working unchanged.

    Must only be called on values already normalized by `to_utc_naive` (or
    the equivalent inline UTC normalization in the loaders); it assumes the
    input is UTC and does not re-detect an existing offset. Comparisons,
    windows and filters should still happen in UTC-naive (before this call);
    this is the conversion for the last step, right before something is shown
    to a person.
    """
    if isinstance(value, pd.Series):
        localized = value.dt.tz_localize("UTC").dt.tz_convert(tz_name)
        return localized.dt.tz_localize(None)
    localized = pd.Timestamp(value).tz_localize("UTC").tz_convert(tz_name)
    return localized.tz_localize(None)


def format_local(
    value: Union[pd.Series, "pd.Timestamp", str, datetime, None],
    fmt: str = "%d/%m/%Y %H:%M",
    tz_name: str = DEFAULT_DISPLAY_TZ,
) -> Union[str, pd.Series]:
    """Format a UTC-naive alert timestamp (or Series of them) as local
    wall-clock text, in one step.

    The replacement for calling `.strftime()`/`.dt.strftime()` directly on a
    UTC-naive value or column — doing that shows a UTC clock reading as if it
    were already local time, which is the W34-06 defect this closes.

    Accepts a scalar (returns `str`, `"-"` for `None`/NaT/an unparseable
    value) or a pandas Series (returns a `str`-dtype Series, `"-"` per entry
    for the same cases) — both forms are used across the Alertas views: a
    single alert's header needs a scalar, a table column needs the vectorized
    form.
    """
    if isinstance(value, pd.Series):
        local = to_local_naive(value, tz_name)
        return local.dt.strftime(fmt).where(local.notna(), "-")
    if value is None:
        return "-"
    try:
        if pd.isna(value):
            return "-"
    except (TypeError, ValueError):
        pass
    try:
        return to_local_naive(value, tz_name).strftime(fmt)
    except (TypeError, ValueError):
        return "-"


def parse_date(date_str: any, format: Optional[str] = None) -> pd.Timestamp:
    """
    Parse date from various formats to Timestamp.
    
    Args:
        date_str: Date string or datetime object
        format: Optional date format string
    
    Returns:
        Parsed Timestamp
    """
    if pd.isna(date_str):
        return pd.NaT
    
    if isinstance(date_str, pd.Timestamp):
        return date_str
    
    if isinstance(date_str, datetime):
        return pd.Timestamp(date_str)
    
    if format:
        try:
            return pd.to_datetime(date_str, format=format)
        except:
            pass
    
    # Try automatic parsing
    return pd.to_datetime(date_str, errors='coerce')


def days_between(date1: pd.Timestamp, date2: pd.Timestamp) -> int:
    """
    Calculate days between two dates.
    
    Args:
        date1: First date
        date2: Second date
    
    Returns:
        Number of days (absolute value)
    """
    if pd.isna(date1) or pd.isna(date2):
        return 0
    
    delta = abs(date1 - date2)
    return delta.days


def format_date_spanish(date: pd.Timestamp) -> str:
    """
    Format date in Spanish style (DD/MM/YYYY).
    
    Args:
        date: Timestamp to format
    
    Returns:
        Formatted date string
    """
    if pd.isna(date):
        return "N/A"
    
    return date.strftime("%d/%m/%Y")


def get_month_name_spanish(date: pd.Timestamp) -> str:
    """
    Get Spanish month name from date.
    
    Args:
        date: Timestamp
    
    Returns:
        Spanish month name
    """
    months = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
        5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
        9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }
    
    if pd.isna(date):
        return "N/A"
    
    return months.get(date.month, "N/A")


def filter_by_date_range(
    df: pd.DataFrame,
    date_column: str,
    start_date: Optional[pd.Timestamp] = None,
    end_date: Optional[pd.Timestamp] = None
) -> pd.DataFrame:
    """
    Filter DataFrame by date range.
    
    Args:
        df: DataFrame to filter
        date_column: Name of date column
        start_date: Optional start date (inclusive)
        end_date: Optional end date (inclusive)
    
    Returns:
        Filtered DataFrame
    """
    result = df.copy()
    
    if start_date is not None:
        result = result[result[date_column] >= start_date]
    
    if end_date is not None:
        result = result[result[date_column] <= end_date]
    
    return result


def get_recent_months(n_months: int = 6) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Get date range for last N months.
    
    Args:
        n_months: Number of months to look back
    
    Returns:
        Tuple of (start_date, end_date)
    """
    end_date = pd.Timestamp.now()
    start_date = end_date - pd.DateOffset(months=n_months)
    
    return start_date, end_date
