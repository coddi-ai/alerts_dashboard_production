"""
Authentication events repository.

Steady-state reads never call S3 live. src/utils/auth_event_logger.py writes
each login event to local disk (below DASHBOARD_DATA_ROOT, the same mounted
data root every other loader in this app reads from - an EFS volume in
production, refreshed from S3 independently) and keeps one consolidated
Parquet file up to date as it does so. This module just reads that Parquet
file - matching how every other dataset in this app is read (see
src/data/loaders.py).

The only time this module talks to S3 is a one-time backfill: if a fresh
environment (new EFS volume, first boot) has no local events at all yet, it
recovers whatever history already exists in S3 before building the local
Parquet for the first time. After that, S3 is never consulted again for
reads.

A malformed *individual event file* is skipped (logged, not fatal) so it
never breaks the rest of the view. A failure to establish *any* local state
at all (no local events AND S3 backfill unavailable) is a different
situation - it's raised as AuthEventsUnavailableError so the caller can show
"unable to load" rather than silently rendering the same empty state as "no
events yet".
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from dotenv import load_dotenv

from src.data.s3_downloader import S3Downloader
from src.utils.logger import get_logger

logger = get_logger(__name__)

S3_PREFIX = "MultiTechnique Alerts/auxiliar/authentication_register/"
LOCAL_EVENTS_SUBDIR = Path("auxiliar") / "authentication_register"
CONSOLIDATED_PARQUET_RELPATH = Path("auxiliar") / "authentication_register.parquet"
REQUIRED_FIELDS = ("event_id", "username", "timestamp", "deploy_status")
OPTIONAL_FIELDS = ("client_id",)
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
CACHE_TTL_SECONDS = 300

_cache: dict = {"data": None, "loaded_at": 0.0}


class AuthEventsUnavailableError(Exception):
    """Raised when no local events exist yet and the S3 backfill can't be reached (not the same as 'no events yet')."""


def _data_root() -> Path:
    return Path(os.getenv("DASHBOARD_DATA_ROOT", "data")).expanduser()


def _local_events_dir(base_dir: Optional[Path] = None) -> Path:
    return (base_dir or _data_root()) / LOCAL_EVENTS_SUBDIR


def _consolidated_parquet_path(base_dir: Optional[Path] = None) -> Path:
    return (base_dir or _data_root()) / CONSOLIDATED_PARQUET_RELPATH


def local_event_path(relative_key: str, base_dir: Optional[Path] = None) -> Path:
    """Resolve where a single event's JSON file lives locally, given its S3-relative key (e.g. 'year=2026/.../evt.json')."""
    return _local_events_dir(base_dir) / relative_key


def _get_downloader() -> Optional[S3Downloader]:
    project_root = Path(__file__).parent.parent.parent
    load_dotenv(project_root / ".env")

    bucket_name = os.getenv("BUCKET_NAME")
    if not bucket_name:
        return None

    return S3Downloader(
        bucket_name=bucket_name,
        aws_access_key_id=os.getenv("ACCESS_KEY"),
        aws_secret_access_key=os.getenv("SECRET_KEY"),
    )


def _parse_event_file(path: Path) -> Optional[dict]:
    """Parse and validate a single local event JSON file. Returns None if malformed."""
    try:
        event = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(event, dict):
            raise ValueError("event is not a JSON object")

        missing = [field for field in REQUIRED_FIELDS if not event.get(field)]
        if missing:
            raise ValueError(f"missing required fields: {missing}")

        return event
    except Exception as e:
        logger.warning(f"Skipping malformed authentication event '{path}': {type(e).__name__}: {e}")
        return None


def _rebuild_consolidated_parquet(base_dir: Optional[Path] = None) -> pd.DataFrame:
    """Re-scan every local event JSON file and rewrite the consolidated Parquet from scratch. Atomic (temp file + replace) so a concurrent reader never sees a half-written file."""
    events_dir = _local_events_dir(base_dir)

    records = []
    if events_dir.exists():
        for path in sorted(events_dir.rglob("*.json")):
            event = _parse_event_file(path)
            if event is not None:
                records.append({field: event.get(field, "unknown") for field in ALL_FIELDS})

    df = pd.DataFrame(records, columns=list(ALL_FIELDS))

    parquet_path = _consolidated_parquet_path(base_dir)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = parquet_path.with_suffix(".parquet.tmp")
    df.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, parquet_path)

    return df


def _backfill_from_s3(base_dir: Optional[Path] = None) -> bool:
    """
    One-time recovery for a fresh environment: pull any pre-existing
    S3-only events down to local disk so history survives the switch to
    local-first reads.

    Returns:
        True if S3 could be reached (even if it returned zero objects).
        False if S3 isn't configured or couldn't be listed - the caller
        decides whether that's fatal based on whether anything is on local
        disk already.
    """
    downloader = _get_downloader()
    if downloader is None:
        return False

    try:
        keys = downloader.list_objects(S3_PREFIX)
    except Exception as e:
        logger.error(f"Failed to list authentication events in S3 for local backfill: {type(e).__name__}: {e}")
        return False

    events_dir = _local_events_dir(base_dir)
    events_dir.mkdir(parents=True, exist_ok=True)

    for key in keys:
        relative_key = key[len(S3_PREFIX):].lstrip("/")
        local_path = events_dir / relative_key
        if local_path.exists():
            continue
        try:
            response = downloader.s3_client.get_object(Bucket=downloader.bucket_name, Key=key)
            body = response["Body"].read()
            local_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")
            tmp_path.write_bytes(body)
            os.replace(tmp_path, local_path)
        except Exception as e:
            logger.warning(f"Failed to backfill authentication event '{key}' from S3: {type(e).__name__}: {e}")

    logger.info(f"Backfilled authentication events from S3 (bucket={downloader.bucket_name}, found {len(keys)} objects)")
    return True


def _bootstrap_local_state(base_dir: Optional[Path] = None) -> bool:
    """
    Make sure local disk reflects any pre-existing S3 history, at most once
    per fresh environment. Idempotent no-op once the consolidated Parquet or
    any local event file already exists - called by both the write path
    (record_local_event) and the read path (list_login_events) so history
    survives regardless of which one happens first in a brand new
    environment (a login before the chart has ever been opened must not
    silently skip recovering older S3-only events).

    Returns:
        True if local state can be trusted from here (already bootstrapped,
        or this call successfully reached S3 - even with zero objects
        found). False only for a brand new environment where S3 can't be
        reached either - callers decide whether that's fatal.
    """
    if _consolidated_parquet_path(base_dir).exists():
        return True

    events_dir = _local_events_dir(base_dir)
    if events_dir.exists() and any(events_dir.rglob("*.json")):
        return True

    return _backfill_from_s3(base_dir)


def record_local_event(event: dict, relative_key: str, base_dir: Optional[Path] = None) -> None:
    """
    Write one event JSON locally (mirroring the S3 key layout) and refresh the
    consolidated Parquet used by list_login_events(). Called by
    src/utils/auth_event_logger.py right after a successful login, before the
    S3 upload. Raises on failure - the caller treats this as best-effort and
    logs/swallows it (the S3 copy remains durable either way).
    """
    _bootstrap_local_state(base_dir)  # best-effort recovery of prior S3 history before adding to it

    local_path = local_event_path(relative_key, base_dir)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(event), encoding="utf-8")
    os.replace(tmp_path, local_path)

    _rebuild_consolidated_parquet(base_dir)


def list_login_events(use_cache: bool = True, base_dir: Optional[Path] = None) -> pd.DataFrame:
    """
    Load the consolidated local Parquet of login events (rebuilding it once,
    from local JSON files, if it doesn't exist yet in this environment).

    Args:
        use_cache: If True, reuse a short-lived in-memory cache instead of
            re-reading the Parquet file on every call.
        base_dir: Override for the data root (tests only) - defaults to
            DASHBOARD_DATA_ROOT / "data".

    Returns:
        DataFrame with columns [event_id, username, timestamp, deploy_status,
        client_id]. Empty (same columns) only when there are genuinely no
        valid events.

    Raises:
        AuthEventsUnavailableError: if there are no local events yet AND the
            one-time S3 backfill can't be reached either - distinct from
            "zero events exist", so callers can show a real error state.
    """
    if use_cache and _cache["data"] is not None and (time.time() - _cache["loaded_at"]) < CACHE_TTL_SECONDS:
        return _cache["data"]

    if not _bootstrap_local_state(base_dir):
        raise AuthEventsUnavailableError("No local authentication events found and S3 backfill is unavailable")

    parquet_path = _consolidated_parquet_path(base_dir)
    if parquet_path.exists():
        try:
            df = pd.read_parquet(parquet_path)
        except Exception as e:
            raise AuthEventsUnavailableError(f"Failed to read local authentication events: {type(e).__name__}: {e}") from e
    else:
        df = _rebuild_consolidated_parquet(base_dir)

    if use_cache:
        _cache["data"] = df
        _cache["loaded_at"] = time.time()

    return df


def get_login_counts_by_user_and_status(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate login events: count of timestamp grouped by username and deploy_status.

    Args:
        df: DataFrame as returned by list_login_events().

    Returns:
        DataFrame with columns [username, deploy_status, count].
    """
    if df.empty:
        return pd.DataFrame(columns=["username", "deploy_status", "count"])

    return (
        df.groupby(["username", "deploy_status"])["timestamp"]
        .count()
        .reset_index(name="count")
    )
