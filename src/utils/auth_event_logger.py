"""
Authentication event logging utility.

Writes each successful login as its own independent JSON object directly to
S3 (no local file, no read-modify-write of shared state), so concurrent
logins and multi-instance deployments can never overwrite each other's
history. See documentation/general/admin_improvements.md for why the
previous single-CSV writer (src/utils/auth_logger.py) was replaced.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from dotenv import load_dotenv
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

S3_PREFIX = "MultiTechnique Alerts/auxiliar/authentication_register"


def log_authentication_event(username: str) -> None:
    """
    Record one successful login as an independent JSON object in S3.

    Failures are logged and swallowed - a logging error must never prevent
    the user from logging into the platform.

    Args:
        username: The username that logged in successfully.
    """
    try:
        now = datetime.now(timezone.utc)
        event = {
            "event_id": str(uuid.uuid4()),
            "username": username,
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "deploy_status": os.getenv("DEPLOY_STATUS", "unknown"),
        }

        s3_key = (
            f"{S3_PREFIX}/"
            f"year={now:%Y}/month={now:%m}/day={now:%d}/"
            f"{now.strftime('%Y%m%dT%H%M%S%f')}_{event['event_id']}.json"
        )

        _put_event(s3_key, event)
    except Exception as e:
        logger.error(f"Failed to log authentication event for {username}: {e}")


def _put_event(s3_key: str, event: dict) -> None:
    """Upload a single authentication event JSON object to S3."""
    project_root = Path(__file__).parent.parent.parent
    load_dotenv(project_root / ".env")

    bucket_name = os.getenv("BUCKET_NAME")
    access_key = os.getenv("ACCESS_KEY")
    secret_key = os.getenv("SECRET_KEY")

    if not bucket_name:
        logger.warning("BUCKET_NAME not set, skipping auth event upload")
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
