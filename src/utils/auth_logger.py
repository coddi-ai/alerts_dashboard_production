"""
Authentication logging utility.

Appends login attempts to a parquet file and uploads it to S3
so the record persists across data syncs.
"""

import os
import pandas as pd
import boto3
from datetime import datetime
from pathlib import Path
from flask import request
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

AUTH_LOG_PATH = Path("data/auxiliar/authentication_register.parquet")
S3_KEY = "MultiTechnique Alerts/auxiliar/authentication_register.parquet"


def log_authentication(username: str, success: bool) -> None:
    """
    Append an authentication record to the parquet log file and upload to S3.
    Only runs when DEPLOY_STATUS is 'poc'.

    Args:
        username: The username that attempted login.
        success: Whether the login was successful.
    """
    try:
        project_root = Path(__file__).parent.parent.parent
        load_dotenv(project_root / ".env")

        deploy_status = os.getenv("DEPLOY_STATUS", "").lower()
        if deploy_status != "poc":
            return

        ip_address = _get_client_ip()

        new_record = pd.DataFrame([{
            "username": username,
            "timestamp": datetime.now(),
            "success": success,
            "ip_address": ip_address,
        }])

        AUTH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        if AUTH_LOG_PATH.exists():
            existing = pd.read_parquet(AUTH_LOG_PATH)
            df = pd.concat([existing, new_record], ignore_index=True)
        else:
            df = new_record

        df.to_parquet(AUTH_LOG_PATH, index=False)
        _upload_to_s3()
    except Exception as e:
        logger.error(f"Failed to log authentication event: {e}")


def _upload_to_s3() -> None:
    """Upload the authentication register to S3."""
    try:
        project_root = Path(__file__).parent.parent.parent
        load_dotenv(project_root / ".env")

        bucket_name = os.getenv("BUCKET_NAME")
        access_key = os.getenv("ACCESS_KEY")
        secret_key = os.getenv("SECRET_KEY")

        if not bucket_name:
            logger.warning("BUCKET_NAME not set, skipping S3 upload")
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

        s3_client.upload_file(str(AUTH_LOG_PATH.resolve()), bucket_name, S3_KEY)
        logger.info("Authentication register uploaded to S3")
    except Exception as e:
        logger.error(f"Failed to upload auth register to S3: {e}")


def _get_client_ip() -> str:
    """Extract client IP from the Flask request context."""
    try:
        # Support proxied requests (X-Forwarded-For header)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr or "unknown"
    except RuntimeError:
        # Outside request context
        return "unknown"
