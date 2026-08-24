"""Optional Polars-backed readers for large dashboard sources.

Polars is used only for the expensive file-to-DataFrame boundary.  The public
dashboard contract remains pandas so existing Dash, Plotly and schema code
does not need to change.  Set ``DASHBOARD_FRAME_ENGINE=pandas`` to force the
fallback during troubleshooting.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Iterable, Mapping

import pandas as pd

logger = logging.getLogger(__name__)


def _polars_enabled() -> bool:
    configured = os.getenv("DASHBOARD_FRAME_ENGINE", "auto").lower()
    if configured in {"pandas", "pd", "off", "false", "0"}:
        return False
    try:
        import polars  # noqa: F401
    except ImportError:
        return False
    return True


def _to_pandas(frame):
    # Polars' pandas bridge uses the already-declared PyArrow dependency and
    # preserves the familiar pandas object expected by downstream callbacks.
    return frame.to_pandas(use_pyarrow_extension_array=False)


def read_csv(path: str | Path, *, columns: Iterable[str] | None = None) -> pd.DataFrame:
    """Read CSV with Polars when available, otherwise use pandas."""

    path = Path(path)
    if _polars_enabled():
        try:
            import polars as pl

            kwargs = {"has_header": True, "try_parse_dates": False}
            if columns is not None:
                kwargs["columns"] = list(columns)
            return _to_pandas(pl.read_csv(str(path), **kwargs))
        except Exception as exc:
            # A malformed/legacy CSV should keep the existing pandas fallback
            # rather than making a page unavailable solely because the fast
            # engine could not infer one column.
            logger.warning("Polars CSV read failed for %s; falling back to pandas: %s", path, exc)
    return pd.read_csv(path, usecols=list(columns) if columns is not None else None)


def read_csv_filtered(
    path: str | Path,
    filters: Mapping[str, Iterable[str]],
    *,
    columns: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Materialize only matching CSV rows when Polars is available.

    This is useful for Alertas Detallada: the source is wide and large, but a
    user normally asks for one alert and one unit.  The pandas fallback keeps
    the same result contract and filters after reading the file.
    """

    path = Path(path)
    normalized = {
        key: [str(value).strip() for value in values]
        for key, values in filters.items()
    }
    output_columns = list(columns) if columns is not None else None
    read_columns = (
        list(dict.fromkeys([*normalized.keys(), *output_columns]))
        if output_columns is not None
        else None
    )
    if _polars_enabled():
        try:
            import polars as pl

            lazy = pl.scan_csv(str(path), has_header=True, try_parse_dates=False)
            for key, values in normalized.items():
                lazy = lazy.filter(
                    pl.col(key).cast(pl.Utf8).str.strip_chars().is_in(values)
                )
            if output_columns is not None:
                lazy = lazy.select(output_columns)
            return _to_pandas(lazy.collect())
        except Exception as exc:
            logger.warning(
                "Polars filtered CSV read failed for %s; falling back to pandas: %s",
                path,
                exc,
            )

    frame = pd.read_csv(path, usecols=read_columns)
    for key, values in normalized.items():
        if key in frame.columns:
            frame = frame[frame[key].astype(str).str.strip().isin(values)]
    if output_columns is not None:
        frame = frame[output_columns]
    return frame


def read_parquet(path: str | Path, *, columns: Iterable[str] | None = None) -> pd.DataFrame:
    """Read Parquet with projection support and a pandas fallback."""

    path = Path(path)
    if _polars_enabled():
        try:
            import polars as pl

            return _to_pandas(pl.read_parquet(str(path), columns=list(columns) if columns is not None else None))
        except Exception as exc:
            logger.warning("Polars Parquet read failed for %s; falling back to pandas: %s", path, exc)
    return pd.read_parquet(path, columns=list(columns) if columns is not None else None)


def engine_name() -> str:
    """Return the effective engine name for diagnostics and benchmarks."""

    return "polars" if _polars_enabled() else "pandas"
