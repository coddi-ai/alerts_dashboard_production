"""
Authentication event logging utility.

Writes each successful login as its own independent JSON object, both to
local disk (below DASHBOARD_DATA_ROOT - an EFS volume in production, shared
by every running instance) and to S3. The local copy is what
src/data/auth_events_repository.py actually reads for the "Registro de
usuarios" chart, matching how every other dataset in this app is read; the
S3 copy is the durable backup that survives even if the local volume is ever
lost or recreated. Each destination is independent and best-effort - a
failure in one is logged but never blocks the other, and never prevents the
user from logging in. See documentation/general/admin_improvements.md for
why the original single-CSV writer (src/utils/auth_logger.py) was replaced.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from dotenv import load_dotenv
from pathlib import Path

from src.data.auth_events_repository import record_local_event
from src.utils.logger import get_logger

logger = get_logger(__name__)

S3_PREFIX = "MultiTechnique Alerts/auxiliar/authentication_register"


def log_authentication_event(username: str, client_id: str = None) -> None:
    """
    Record one successful login as an independent JSON object, locally and in S3.

    Never include passwords, hashes, or other secrets in the event.

    Args:
        username: The username that logged in successfully.
        client_id: The user's primary/default client (first entry of their
            assigned clients list), recorded for audit context.
    """
    project_root = Path(__file__).parent.parent.parent
    load_dotenv(project_root / ".env")
    bucket_name = os.getenv("BUCKET_NAME")

    now = datetime.now(timezone.utc)
    event = {
        "event_id": str(uuid.uuid4()),
        "username": username,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "deploy_status": os.getenv("DEPLOY_STATUS", "unknown"),
        "client_id": client_id or "unknown",
    }
    relative_key = (
        f"year={now:%Y}/month={now:%m}/day={now:%d}/"
        f"{now.strftime('%Y%m%dT%H%M%S%f')}_{event['event_id']}.json"
    )

    try:
        record_local_event(event, relative_key)
    except Exception as e:
        logger.error(f"Failed to persist authentication event locally for user '{username}': {type(e).__name__}: {e}")

    try:
        _put_event(bucket_name, f"{S3_PREFIX}/{relative_key}", event)
    except Exception as e:
        logger.error(
            f"Failed to log authentication event for user '{username}' "
            f"(bucket={bucket_name}, prefix={S3_PREFIX}): {type(e).__name__}: {e}"
        )


def _put_event(bucket_name: str, s3_key: str, event: dict) -> None:
    """Upload a single authentication event JSON object to S3."""
    access_key = os.getenv("ACCESS_KEY")
    secret_key = os.getenv("SECRET_KEY")

    if not bucket_name:
        logger.warning(f"BUCKET_NAME not set, skipping auth event upload (prefix={S3_PREFIX})")
        return

    if access_key and secret_key:
        s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )
    else:
        s3_client = boto3.client("s3", region_name="us-east-1")

    s3_client.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=json.dumps(event).encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(f"Authentication event uploaded to S3: {s3_key}")
