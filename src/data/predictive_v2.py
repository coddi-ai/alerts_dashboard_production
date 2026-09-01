"""
Readers for the Predictive Data Contract v2.0 (long-format Parquet, local
mirror at data/{tecnica}/golden/{cliente}/{componente}/{tabla}/year=/week=/).

See documentation/predictive/predictive_data_contracts.md for the full
contract. This module only reads the local mirror - no live S3/AWS client
is created here, matching the contract's "no runtime S3 dependency" rule.

Partition reading mirrors the existing telemetry pattern in
src/data/loaders.py (_latest_telemetry_partition / _telemetry_partition_generation
/ _filter_latest_week) rather than pyarrow.dataset, so these readers behave
like the rest of the loaders module.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow.parquet as pq

from src.utils.logger import get_logger
from src.utils.file_utils import safe_read_parquet
from src.data.catalog import dashboard_data_root

logger = get_logger(__name__)

_DEFAULT_WEEKS = 13  # ~91 days of available weekly partitions


@dataclass(frozen=True)
class ComponentAvailability:
    """Per-table existence for one client/component under the new layout."""
    risk_scores: bool = False
    unit_status_summary: bool = False
    cumulative_risk_curve: bool = False
    signal_daily_status: bool = False
    legacy_csv: Optional[Path] = None


# ── Path resolution ────────────────────────────────────────────────────────

def _predictive_root(client: str) -> Path:
    return dashboard_data_root() / "predictive" / "golden" / (client or "").lower()


def _telemetry_root(client: str) -> Path:
    return dashboard_data_root() / "telemetry" / "golden" / (client or "").lower()


def risk_scores_base_path(client: str, component: str) -> Path:
    return _predictive_root(client) / component / "risk_scores"


def unit_status_summary_base_path(client: str, component: str) -> Path:
    return _predictive_root(client) / component / "unit_status_summary"


def cumulative_risk_curve_base_path(client: str, component: str) -> Path:
    return _predictive_root(client) / component / "cumulative_risk_curve"


def signal_daily_status_base_path(client: str, component: str) -> Path:
    return _telemetry_root(client) / component / "signal_daily_status"


# ── Discovery (Change 1: single shared discovery function) ────────────────

def _has_partitions(base: Path) -> bool:
    if not base.is_dir():
        return False
    return any(base.glob("year=*/week=*"))


@lru_cache(maxsize=16)
def _discover_predictive_layout_cached(client: str, root_mtime_ns: int) -> dict:
    root = _predictive_root(client)
    layout = {}
    if not root.is_dir():
        return layout
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            component = entry.name
            candidate_csv = root / f"{component}.csv"
            layout[component] = ComponentAvailability(
                risk_scores=_has_partitions(entry / "risk_scores"),
                unit_status_summary=_has_partitions(entry / "unit_status_summary"),
                cumulative_risk_curve=_has_partitions(entry / "cumulative_risk_curve"),
                signal_daily_status=_has_partitions(
                    _telemetry_root(client) / component / "signal_daily_status"
                ),
                legacy_csv=candidate_csv if candidate_csv.is_file() else None,
            )
        elif entry.suffix == ".csv":
            component = entry.stem
            # Only fills components not already populated by the dir branch
            # above - sorted() puts "motor" before "motor.csv", so a
            # component with both a directory and a legacy CSV is already
            # correctly recorded by the time this branch runs for it.
            layout.setdefault(component, ComponentAvailability(legacy_csv=entry))
    return layout


def discover_predictive_layout(client: str) -> dict:
    """Per-component table availability for `client`.

    This is the single shared discovery function (Change 1) - callers no
    longer scan `data/predictive/golden/{client}/*.csv` themselves. Cached
    until the client's predictive root directory changes (new component
    materialized/removed).
    """
    root = _predictive_root(client)
    if not root.exists():
        return {}
    try:
        root_mtime_ns = root.stat().st_mtime_ns
    except OSError:
        return {}
    return _discover_predictive_layout_cached((client or "").lower(), root_mtime_ns)


# ── Partition listing / reading (risk_scores, unit_status_summary, signal_daily_status) ──

def _list_week_partitions(base: Path) -> list:
    """All (year, week, path) partitions under `base`, sorted ascending."""
    if not base.is_dir():
        return []
    partitions = []
    for year_dir in base.glob("year=*"):
        if not year_dir.is_dir():
            continue
        try:
            year = int(year_dir.name.split("=", 1)[1])
        except (IndexError, ValueError):
            continue
        for week_dir in year_dir.glob("week=*"):
            if not week_dir.is_dir():
                continue
            try:
                week = int(week_dir.name.split("=", 1)[1])
            except (IndexError, ValueError):
                continue
            partitions.append((year, week, week_dir))
    partitions.sort(key=lambda item: (item[0], item[1]))
    return partitions


def _partition_generation(path: Path) -> tuple:
    """Lightweight (mtime_ns, size) cache key for one partition directory."""
    files = tuple(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else ()
    if not files:
        return 0, 0
    stats = tuple(p.stat() for p in files)
    return max(s.st_mtime_ns for s in stats), sum(s.st_size for s in stats)


@lru_cache(maxsize=64)
def _read_partition_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    df = safe_read_parquet(Path(path))
    if "Fecha" in df.columns:
        df["Fecha"] = pd.to_datetime(df["Fecha"])
    return df


def _read_partition(path: Path) -> pd.DataFrame:
    mtime_ns, size = _partition_generation(path)
    return _read_partition_cached(str(path), mtime_ns, size).copy(deep=True)


def read_latest_partition(base: Path) -> pd.DataFrame:
    """Read only the most recent (year, week) partition under `base`.

    Used for `unit_status_summary` (one row per unit per run - only the
    latest run matters). A stalled/skipped upstream run does not mean "no
    data", it means "use the last partition that IS present".
    """
    partitions = _list_week_partitions(base)
    if not partitions:
        return pd.DataFrame()
    _, _, path = partitions[-1]
    return _read_partition(path)


def read_last_n_weeks(base: Path, n: int = _DEFAULT_WEEKS) -> pd.DataFrame:
    """Read and concatenate the last `n` available week partitions under `base`.

    Used for `risk_scores`/`signal_daily_status`, which need history. Reads
    only the listed partitions (never a full-dataset scan), each cached
    independently so a sliding window mostly hits cache.
    """
    partitions = _list_week_partitions(base)[-n:]
    if not partitions:
        return pd.DataFrame()
    frames = [_read_partition(path) for _, _, path in partitions]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _generation_for_last_n_weeks(base: Path, n: int = _DEFAULT_WEEKS) -> tuple:
    partitions = _list_week_partitions(base)[-n:]
    if not partitions:
        return 0, 0
    gens = [_partition_generation(p) for _, _, p in partitions]
    return max(g[0] for g in gens), sum(g[1] for g in gens)


# ── High-level table readers ────────────────────────────────────────────────

def load_risk_scores(client: str, component: str) -> pd.DataFrame:
    return read_last_n_weeks(risk_scores_base_path(client, component))


def load_unit_status_summary(client: str, component: str) -> pd.DataFrame:
    return read_latest_partition(unit_status_summary_base_path(client, component))


def load_signal_daily_status(client: str, component: str) -> pd.DataFrame:
    return read_last_n_weeks(signal_daily_status_base_path(client, component))


def risk_scores_generation(client: str, component: str) -> tuple:
    """(mtime_ns, size) cache key covering the exact partitions load_risk_scores
    would read for this client/component - for callers that want their own
    cache keyed on "has this component's data changed"."""
    return _generation_for_last_n_weeks(risk_scores_base_path(client, component))


def risk_scores_to_wide(df_long: pd.DataFrame) -> pd.DataFrame:
    """Pivot long-format `risk_scores` (Unit, Fecha, failure_mode, risk_value)
    into one column per mode plus `ranking`, indexed by (Unit, Fecha) - the
    same wide shape the legacy CSV loader's rolling-window computation
    expects, so that computation can be reused unchanged (Change 2).

    A missing unit/day/mode combination is simply absent from the input and
    becomes NaN here (pivot_table never manufactures 0 for an unobserved
    cell), matching the contract's "absence is not a zero" rule.
    """
    if df_long is None or df_long.empty:
        return pd.DataFrame(columns=["Unit", "Fecha", "ranking"])
    wide = df_long.pivot_table(
        index=["Unit", "Fecha"], columns="failure_mode", values="risk_value", aggfunc="last",
    )
    wide.columns = [str(c) for c in wide.columns]
    wide = wide.reset_index()
    wide["Fecha"] = pd.to_datetime(wide["Fecha"])
    return wide


def get_failure_mode_keys(client: str, component: str) -> list:
    """Distinct failure modes actually present in this client/component's
    data (Change 3: mode lists must come from the data, not a hardcoded
    count). Prefers `unit_status_summary.modos_ordenados` (already ordered
    highest->lowest); falls back to the distinct `risk_scores.failure_mode`
    values. Returns [] when neither new-layout table exists, so callers can
    fall back to their config-driven list unchanged.
    """
    df_status = load_unit_status_summary(client, component)
    if not df_status.empty and "modos_ordenados" in df_status.columns:
        raw = df_status["modos_ordenados"].dropna()
        if not raw.empty:
            try:
                modos = json.loads(raw.iloc[0])
                keys = list(modos.keys())
                if keys:
                    return keys
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.warning(
                    "No se pudo parsear modos_ordenados para %s/%s", client, component
                )
    df_scores = load_risk_scores(client, component)
    if not df_scores.empty and "failure_mode" in df_scores.columns:
        modes = sorted(m for m in df_scores["failure_mode"].unique() if m != "ranking")
        if modes:
            return modes
    return []


# ── Cumulative risk curve (Change 6: dedicated reader, own metadata) ──────

_CURVE_METADATA_KEYS = ("config", "banda", "tendencia")

CUMULATIVE_CURVE_COLUMNS = [
    "Unit", "Fecha", "ciclo", "curva", "componentHours_filled",
    "ranking_acumulado_ajustado", "banda_media", "banda_umbral",
    "estado", "zona_final", "es_vigente",
]


@lru_cache(maxsize=16)
def _read_cumulative_curve_cached(path: str, mtime_ns: int, size: int):
    file_path = Path(path)
    table = pq.read_table(file_path)
    df = table.to_pandas()
    metadata = table.schema.metadata or {}
    attrs = {}
    for key in _CURVE_METADATA_KEYS:
        raw = metadata.get(key.encode())
        if raw is None:
            continue
        try:
            attrs[key] = json.loads(raw.decode())
        except (ValueError, json.JSONDecodeError):
            logger.warning("No se pudo parsear metadata '%s' de %s", key, file_path)
    if "Fecha" in df.columns:
        df["Fecha"] = pd.to_datetime(df["Fecha"])
    return df, attrs


def read_cumulative_risk_curve(client: str, component: str) -> Optional[pd.DataFrame]:
    """Dedicated reader for `cumulative_risk_curve` (Change 6).

    Does NOT use read_latest_partition/safe_read_parquet: each partition
    already carries the unit's full history (not just that week), and the
    parquet's config/banda/tendencia schema-level metadata - needed for
    correct zone boundaries - is silently dropped by a plain pandas read.
    This reads via pyarrow.parquet directly and reattaches the 3 metadata
    keys as df.attrs.

    Returns None if the table doesn't exist for this client/component,
    checked independently of risk_scores/unit_status_summary (a component
    can have those without having a cumulative_risk_curve yet).
    """
    base = cumulative_risk_curve_base_path(client, component)
    partitions = _list_week_partitions(base)
    if not partitions:
        return None
    _, _, path = partitions[-1]
    files = sorted(path.glob("*.parquet"))
    if not files:
        return None
    target = files[0]
    try:
        stat = target.stat()
        df, attrs = _read_cumulative_curve_cached(str(target), stat.st_mtime_ns, stat.st_size)
    except Exception as exc:  # noqa: BLE001 - never break the overview on a bad curve file
        logger.warning("No se pudo leer cumulative_risk_curve en %s: %s", target, exc)
        return None
    df = df.copy(deep=True)
    df.attrs.update(attrs)
    return df
