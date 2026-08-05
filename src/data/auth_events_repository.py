"""
Authentication events repository.

Reads the individual login-event JSON objects written by
src/utils/auth_event_logger.py and consolidates them into a DataFrame for
the admin "Registro de usuarios" chart. The individual S3 objects remain the
source of truth; this module only ever reads them, never rewrites them, and
a malformed object is skipped rather than breaking the whole view.
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
REQUIRED_FIELDS = ("event_id", "username", "timestamp", "deploy_status")
CACHE_TTL_SECONDS = 300

_cache: dict = {"data": None, "loaded_at": 0.0}


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


def _fetch_event(s3_client, bucket_name: str, key: str) -> Optional[dict]:
    """Fetch and validate a single login-event JSON object. Returns None if malformed."""
    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=key)
        event = json.loads(response["Body"].read())

        if not isinstance(event, dict):
            raise ValueError("event is not a JSON object")

        missing = [field for field in REQUIRED_FIELDS if not event.get(field)]
        if missing:
            raise ValueError(f"missing required fields: {missing}")

        return event
    except Exception as e:
        logger.warning(f"Skipping malformed authentication event '{key}': {e}")
        return None


def list_login_events(use_cache: bool = True) -> pd.DataFrame:
    """
    Consolidate all login-event JSON objects in S3 into a DataFrame.

    Args:
        use_cache: If True, reuse a short-lived in-memory cache instead of
            re-listing/re-reading S3 on every call. The cache is never the
            source of truth - it just avoids repeated S3 round-trips.

    Returns:
        DataFrame with columns [event_id, username, timestamp, deploy_status].
        Empty DataFrame (same columns) if there are no events or S3 isn't
        configured.
    """
    if use_cache and _cache["data"] is not None and (time.time() - _cache["loaded_at"]) < CACHE_TTL_SECONDS:
        return _cache["data"]

    columns = list(REQUIRED_FIELDS)
    downloader = _get_downloader()

    if downloader is None:
        logger.warning("BUCKET_NAME not set, cannot list authentication events")
        return pd.DataFrame(columns=columns)

    try:
        keys = downloader.list_objects(S3_PREFIX)
    except Exception as e:
        logger.error(f"Failed to list authentication events: {e}")
        return pd.DataFrame(columns=columns)

    events = []
    for key in keys:
        event = _fetch_event(downloader.s3_client, downloader.bucket_name, key)
        if event is not None:
            events.append({field: event[field] for field in REQUIRED_FIELDS})

    df = pd.DataFrame(events, columns=columns)

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
