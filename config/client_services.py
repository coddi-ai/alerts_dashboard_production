"""
Client Service Register.

Centralizes which dashboard services (route/module identifiers) are enabled
per client, replacing the previous ad hoc per-module allow-lists
(`predictive_allowed_clients`, etc.) that were checked independently in
several callbacks. `is_service_enabled()` is the single authorization
function every dashboard module must use - the configuration must never be
interpreted directly anywhere else.

Unknown client or service identifiers default to DENIED.
"""

from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

from config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).parent / "client_services.yaml"

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
    """Raised when client_services.yaml is structurally invalid (fail fast)."""


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Set[str]]:
    """
    Load and structurally parse client_services.yaml.

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

    if not isinstance(raw, dict) or not isinstance(raw.get("clients"), dict):
        raise InvalidClientServicesConfig(
            f"{path} must have a top-level 'clients' mapping"
        )

    parsed: Dict[str, Set[str]] = {}
    for client_id, client_config in raw["clients"].items():
        if not isinstance(client_config, dict) or "enabled_services" not in client_config:
            raise InvalidClientServicesConfig(
                f"Client '{client_id}' must be a mapping with an 'enabled_services' list"
            )

        enabled_services = client_config["enabled_services"]
        if not isinstance(enabled_services, list):
            raise InvalidClientServicesConfig(
                f"Client '{client_id}' enabled_services must be a list"
            )

        parsed[client_id] = set(enabled_services)

    return parsed


def validate_startup_config(config: Dict[str, Set[str]] = None, path: Path = CONFIG_PATH) -> List[str]:
    """
    Validate field-level config correctness. Structural errors already raised
    by load_config(); this checks unknown ids, duplicates, and empty clients.

    Logs every problem found. Returns the list of problem descriptions
    (useful for tests) - callers don't need to inspect it.
    """
    if config is None:
        config = load_config(path)

    known_clients = set(get_settings().clients)
    problems: List[str] = []

    for client_id, service_ids in config.items():
        if client_id not in known_clients:
            problems.append(f"Unknown client identifier in client_services.yaml: '{client_id}'")

        unknown_services = service_ids - set(KNOWN_SERVICE_IDS)
        for service_id in unknown_services:
            problems.append(
                f"Unknown service identifier for client '{client_id}': '{service_id}'"
            )

        if not service_ids:
            problems.append(f"Client '{client_id}' has no enabled services")

    for client_id in known_clients - config.keys():
        problems.append(f"Client '{client_id}' is not present in client_services.yaml (defaults to no access)")

    for problem in problems:
        logger.error(f"client_services.yaml validation issue: {problem}")

    if not problems:
        logger.info("client_services.yaml validated successfully")

    return problems


_config_cache: Optional[Dict[str, Set[str]]] = None
_config_cache_mtime: Optional[float] = None


def get_client_services_config() -> Dict[str, Set[str]]:
    """
    Get the parsed client services config, reloading it whenever
    client_services.yaml's mtime changes so edits take effect without a
    server restart (this file is small and read infrequently - a human
    clicking around, not a hot path - so re-checking mtime is negligible).
    """
    global _config_cache, _config_cache_mtime

    try:
        current_mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        current_mtime = None

    if _config_cache is None or current_mtime != _config_cache_mtime:
        _config_cache = load_config()
        _config_cache_mtime = current_mtime

    return _config_cache


def is_service_enabled(client_id: str, service_id: str) -> bool:
    """
    The single centralized authorization check every dashboard module must use.

    Unknown client or unknown service both default to DENIED.
    """
    if not client_id or not service_id:
        return False

    config = get_client_services_config()
    return service_id in config.get(client_id.upper(), set())


def get_enabled_services(client_id: str) -> List[str]:
    """Enabled services for a client, ordered per KNOWN_SERVICE_IDS."""
    config = get_client_services_config()
    enabled = config.get((client_id or "").upper(), set())
    return [service_id for service_id in KNOWN_SERVICE_IDS if service_id in enabled]
