"""
Client Service Register.

Centralizes which dashboard services (route/module identifiers) are enabled
per client, replacing the previous ad hoc per-module allow-lists
(`predictive_allowed_clients`, etc.) that were checked independently in
several callbacks. `is_service_enabled()` / `get_enabled_services()` /
`update_enabled_services()` are the only functions any dashboard module may
use - the configuration must never be interpreted or persisted directly
anywhere else.

Runtime source of truth is a JSON object in S3 (durable across restarts and
redeployments - this app already treats local container disk as ephemeral,
see dashboard/app.py's S3-hydration-at-boot). `client_services.yaml` is only
the bootstrap/default used before any admin edit has ever been saved.

Unknown client or service identifiers default to DENIED.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import boto3
import yaml
from botocore.exceptions import ClientError
from dotenv import load_dotenv

from config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).parent / "client_services.yaml"
OVERRIDE_S3_KEY = "MultiTechnique Alerts/config/client_services_override.json"
AUDIT_S3_PREFIX = "MultiTechnique Alerts/auxiliar/client_services_audit"
EFFECTIVE_CACHE_TTL_SECONDS = 30
MAX_UPDATE_RETRIES = 3

# Canonical, ordered list of service identifiers. Order here drives both nav
# ordering and default-route resolution. Matches the app's internal
# nav-id/route identifiers (dashboard/services_registry.py). Predictive is a
# single umbrella service covering all `/predictive/<component>` routes.
KNOWN_SERVICE_IDS: List[str] = [
    "overview-general",
    "overview-data-freshness",
    "monitoring-alerts",
    "monitoring-telemetry",
    "monitoring-oil",
    "predictive",
    "agents-campbell-ai",
    "integration-validacion-avisos",
    "integration-seguimiento-avisos",
    "reporting-main",
]


class InvalidClientServicesConfig(Exception):
    """Raised when a config source (YAML or S3 override) is structurally invalid."""


class UnknownClientError(ValueError):
    """Raised when a client id doesn't match config.settings.Settings.clients."""


class UnknownServiceError(ValueError):
    """Raised when a service id isn't in KNOWN_SERVICE_IDS."""


def normalize_client_id(client_id: str) -> str:
    """Canonical client id form: stripped, upper-cased. Never creates a client - just normalizes for lookup."""
    return (client_id or "").strip().upper()


def _known_clients() -> Set[str]:
    return {normalize_client_id(c) for c in get_settings().clients}


def _parse_clients_mapping(raw: dict, source: str) -> Dict[str, Set[str]]:
    """Shared structural parser for both the YAML bootstrap file and the S3 override JSON."""
    if not isinstance(raw, dict) or not isinstance(raw.get("clients"), dict):
        raise InvalidClientServicesConfig(f"{source} must have a top-level 'clients' mapping")

    parsed: Dict[str, Set[str]] = {}
    for client_id, client_config in raw["clients"].items():
        if not isinstance(client_config, dict) or "enabled_services" not in client_config:
            raise InvalidClientServicesConfig(
                f"{source}: client '{client_id}' must be a mapping with an 'enabled_services' list"
            )

        enabled_services = client_config["enabled_services"]
        if not isinstance(enabled_services, list):
            raise InvalidClientServicesConfig(f"{source}: client '{client_id}' enabled_services must be a list")

        parsed[normalize_client_id(client_id)] = set(enabled_services)

    return parsed


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Set[str]]:
    """
    Load and structurally parse the local YAML bootstrap/default config.

    Returns:
        Mapping of client_id -> set of enabled service ids.

    Raises:
        InvalidClientServicesConfig: on any structural problem (not a
            critical field-level issue - those are validated separately by
            validate_startup_config, which logs and default-denies instead
            of crashing).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise InvalidClientServicesConfig(f"Failed to parse {path}: {e}") from e

    return _parse_clients_mapping(raw, str(path))


def validate_startup_config(config: Dict[str, Set[str]] = None, path: Path = CONFIG_PATH) -> List[str]:
    """
    Validate field-level config correctness. Structural errors already raised
    by load_config()/_parse_clients_mapping(); this checks unknown ids,
    duplicates, and empty clients.

    Logs every problem found. Returns the list of problem descriptions
    (useful for tests) - callers don't need to inspect it.
    """
    if config is None:
        config = load_config(path)

    known_clients = _known_clients()
    problems: List[str] = []

    for client_id, service_ids in config.items():
        if client_id not in known_clients:
            problems.append(f"Unknown client identifier in client_services config: '{client_id}'")

        unknown_services = service_ids - set(KNOWN_SERVICE_IDS)
        for service_id in unknown_services:
            problems.append(
                f"Unknown service identifier for client '{client_id}': '{service_id}'"
            )

        if not service_ids:
            problems.append(f"Client '{client_id}' has no enabled services")

    for client_id in known_clients - config.keys():
        problems.append(f"Client '{client_id}' is not present in client_services config (defaults to no access)")

    for problem in problems:
        logger.error(f"client_services config validation issue: {problem}")

    if not problems:
        logger.info("client_services.yaml validated successfully")

    return problems


# ---------------------------------------------------------------------------
# Durable (S3-backed) runtime override
# ---------------------------------------------------------------------------

def _s3_client_and_bucket():
    """Returns (s3_client, bucket_name), or (None, None) if S3 isn't configured."""
    project_root = Path(__file__).parent.parent
    load_dotenv(project_root / ".env")

    bucket_name = os.getenv("BUCKET_NAME")
    if not bucket_name:
        return None, None

    access_key = os.getenv("ACCESS_KEY")
    secret_key = os.getenv("SECRET_KEY")
    if access_key and secret_key:
        client = boto3.client(
            "s3", aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name="us-east-1"
        )
    else:
        client = boto3.client("s3", region_name="us-east-1")

    return client, bucket_name


def _read_override() -> Tuple[Optional[Dict[str, Set[str]]], Optional[str]]:
    """
    Read the S3 override object.

    Returns:
        (parsed_config, etag) if the override exists and is valid.
        (None, None) if it doesn't exist yet, S3 isn't configured, or it
        can't be read/parsed (logged as an error either way - callers fall
        back to the YAML bootstrap rather than crashing nav/routing).
    """
    s3_client, bucket_name = _s3_client_and_bucket()
    if s3_client is None:
        return None, None

    try:
        response = s3_client.get_object(Bucket=bucket_name, Key=OVERRIDE_S3_KEY)
        raw = json.loads(response["Body"].read())
        etag = response["ETag"]
        return _parse_clients_mapping(raw, OVERRIDE_S3_KEY), etag
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code in ("NoSuchKey", "404"):
            return None, None
        logger.error(
            f"Failed to read client_services override (bucket={bucket_name}, "
            f"key={OVERRIDE_S3_KEY}): {type(e).__name__}: {e}"
        )
        return None, None
    except Exception as e:
        logger.error(
            f"Failed to parse client_services override (bucket={bucket_name}, "
            f"key={OVERRIDE_S3_KEY}): {type(e).__name__}: {e}"
        )
        return None, None


_effective_cache: Optional[Dict[str, Set[str]]] = None
_effective_cache_loaded_at: float = 0.0


def get_client_services_config(force_refresh: bool = False) -> Dict[str, Set[str]]:
    """
    Get the effective client services config: the S3 override if one has ever
    been saved, otherwise the local YAML bootstrap. Cached for
    EFFECTIVE_CACHE_TTL_SECONDS so nav/route checks don't hit S3 on every
    click; force_refresh=True (used right after a save) bypasses that.
    """
    global _effective_cache, _effective_cache_loaded_at

    if not force_refresh and _effective_cache is not None and (time.time() - _effective_cache_loaded_at) < EFFECTIVE_CACHE_TTL_SECONDS:
        return _effective_cache

    override_config, _etag = _read_override()
    _effective_cache = override_config if override_config is not None else load_config()
    _effective_cache_loaded_at = time.time()

    return _effective_cache


def is_service_enabled(client_id: str, service_id: str) -> bool:
    """
    The single centralized authorization check every dashboard module must use.

    Unknown client or unknown service both default to DENIED.
    """
    if not client_id or not service_id:
        return False

    config = get_client_services_config()
    return service_id in config.get(normalize_client_id(client_id), set())


def get_enabled_services(client_id: str) -> List[str]:
    """Enabled services for a client, ordered per KNOWN_SERVICE_IDS."""
    config = get_client_services_config()
    enabled = config.get(normalize_client_id(client_id), set())
    return [service_id for service_id in KNOWN_SERVICE_IDS if service_id in enabled]


def update_enabled_services(client_id: str, service_ids: List[str], updated_by: str) -> None:
    """
    Persist a client's complete enabled-service list to the durable S3
    override, then write an audit record. Raises UnknownClientError /
    UnknownServiceError / RuntimeError on validation or persistence failure -
    nothing is written in that case, and the previously-valid config remains
    active.
    """
    normalized_client = normalize_client_id(client_id)
    if normalized_client not in _known_clients():
        raise UnknownClientError(f"Unknown client: '{client_id}'")

    if not isinstance(service_ids, list):
        raise ValueError("service_ids must be a list")

    validated_services: List[str] = []
    seen: Set[str] = set()
    for service_id in service_ids:
        if service_id not in KNOWN_SERVICE_IDS:
            raise UnknownServiceError(f"Unknown service id: '{service_id}'")
        if service_id not in seen:
            seen.add(service_id)
            validated_services.append(service_id)

    s3_client, bucket_name = _s3_client_and_bucket()
    if s3_client is None:
        raise RuntimeError("Cannot persist client services: S3 is not configured (BUCKET_NAME missing)")

    previous_services: List[str] = []
    for attempt in range(MAX_UPDATE_RETRIES):
        current_config, etag = _read_override()
        if current_config is None:
            current_config = load_config()
        previous_services = sorted(current_config.get(normalized_client, set()))

        new_config = {client: sorted(services) for client, services in current_config.items()}
        new_config[normalized_client] = validated_services
        payload = json.dumps({"clients": {c: {"enabled_services": s} for c, s in new_config.items()}}).encode("utf-8")

        put_kwargs = dict(Bucket=bucket_name, Key=OVERRIDE_S3_KEY, Body=payload, ContentType="application/json")
        if etag:
            put_kwargs["IfMatch"] = etag
        else:
            put_kwargs["IfNoneMatch"] = "*"

        try:
            s3_client.put_object(**put_kwargs)
            break
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code in ("PreconditionFailed", "412"):
                logger.warning(
                    f"Concurrent client_services update detected for '{normalized_client}', "
                    f"retrying (attempt {attempt + 1}/{MAX_UPDATE_RETRIES})"
                )
                continue
            logger.error(
                f"Failed to persist client_services override (bucket={bucket_name}, "
                f"key={OVERRIDE_S3_KEY}): {type(e).__name__}: {e}"
            )
            raise RuntimeError(f"Failed to persist client services: {type(e).__name__}: {e}") from e
    else:
        raise RuntimeError(
            f"Failed to persist client services for '{normalized_client}' after "
            f"{MAX_UPDATE_RETRIES} attempts (concurrent updates)"
        )

    get_client_services_config(force_refresh=True)
    _write_audit_event(normalized_client, previous_services, validated_services, updated_by)


def _write_audit_event(client_id: str, previous_services: List[str], new_services: List[str], updated_by: str) -> None:
    """Write one audit JSON object. A failure here is logged, not raised - the config change already succeeded."""
    bucket_name = None
    try:
        s3_client, bucket_name = _s3_client_and_bucket()
        if s3_client is None:
            return

        now = datetime.now(timezone.utc)
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": "client_services_updated",
            "client_id": client_id,
            "previous_services": previous_services,
            "new_services": new_services,
            "updated_by": updated_by,
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        }
        key = (
            f"{AUDIT_S3_PREFIX}/year={now:%Y}/month={now:%m}/day={now:%d}/"
            f"{now.strftime('%Y%m%dT%H%M%S%f')}_{event['event_id']}.json"
        )
        s3_client.put_object(Bucket=bucket_name, Key=key, Body=json.dumps(event).encode("utf-8"), ContentType="application/json")
        logger.info(f"client_services audit event written: {key}")
    except Exception as e:
        logger.error(
            f"Failed to write client_services audit event (bucket={bucket_name}, "
            f"prefix={AUDIT_S3_PREFIX}): {type(e).__name__}: {e}"
        )
