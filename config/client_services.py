"""
Client Service Register.

Centralizes which dashboard services (route/module identifiers) are enabled
per client, replacing ad hoc per-module allow-lists. is_service_enabled() /
is_service_dummy() / get_enabled_services() are the only functions any
dashboard module may use - the configuration must never be interpreted
directly anywhere else.

Source of truth is a single local file, client_services.json, hand-edited
directly in the codebase (no admin UI, no runtime writes) - changes ship
like any other code change. It's re-read automatically whenever its mtime
changes, so editing it takes effect on the next request without needing a
full server restart.

Config shape:

    {
      "<CLIENT_ID>": {
        "<service_id>": {"display": true/false, "dummy": true/false},
        ...
      },
      ...
    }

- display: whether the service's nav item is shown/reachable for that
  client at all. This is what the sidebar (dashboard/layout.py) and the
  route guard (dashboard/callbacks/access_control_callbacks.py) key off.
- dummy: only meaningful when display is true. When true, visiting the
  service shows the shared placeholder page (dashboard/pages/no_services.py)
  instead of the real one - e.g. to preview a nav entry to a client before
  the feature is actually ready for them.

A client or service missing from the config entirely defaults to
{"display": False, "dummy": False} (denied) - unknown identifiers never
silently get access.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

CONFIG_PATH = Path(__file__).parent / "client_services.json"

# Canonical, ordered list of service identifiers. Order here drives both nav
# ordering and default-route resolution. Matches the app's internal
# nav-id/route identifiers (dashboard/services_registry.py). Each predictive
# component (`/predictive/<component>` route) is its own service id
# (`predictive-<component>`) so clients can be granted access per component
# instead of all-or-nothing.
KNOWN_SERVICE_IDS: List[str] = [
    "overview-general",
    "overview-data-freshness",
    "monitoring-alerts",
    "monitoring-telemetry",
    "monitoring-oil",
    "monitoring-mantenciones",
    "predictive-motor",
    "predictive-transmision",
    "agents-campbell-ai",
    "integration-validacion-avisos",
    "integration-seguimiento-avisos",
    "reporting-main",
]

ServiceState = Dict[str, bool]  # {"display": bool, "dummy": bool}
ClientServicesConfig = Dict[str, Dict[str, ServiceState]]  # client_id -> service_id -> state

_DEFAULT_STATE: ServiceState = {"display": False, "dummy": False}


class InvalidClientServicesConfig(Exception):
    """Raised when client_services.json is structurally invalid."""


def normalize_client_id(client_id: str) -> str:
    """Canonical client id form: stripped, upper-cased."""
    return (client_id or "").strip().upper()


def _known_clients() -> set:
    return {normalize_client_id(c) for c in get_settings().clients}


def _parse_service_state(raw, source: str, client_id: str, service_id: str) -> ServiceState:
    if not isinstance(raw, dict) or "display" not in raw:
        raise InvalidClientServicesConfig(
            f"{source}: client '{client_id}' service '{service_id}' must be a mapping with a 'display' key"
        )

    display = raw["display"]
    dummy = raw.get("dummy", False)
    if not isinstance(display, bool) or not isinstance(dummy, bool):
        raise InvalidClientServicesConfig(
            f"{source}: client '{client_id}' service '{service_id}' 'display'/'dummy' must be booleans"
        )

    return {"display": display, "dummy": dummy}


def _parse_clients_mapping(raw: dict, source: str) -> ClientServicesConfig:
    if not isinstance(raw, dict):
        raise InvalidClientServicesConfig(f"{source} must be a mapping of client id -> services")

    parsed: ClientServicesConfig = {}
    for client_id, services in raw.items():
        if not isinstance(services, dict):
            raise InvalidClientServicesConfig(f"{source}: client '{client_id}' must be a mapping of service id -> state")

        parsed[normalize_client_id(client_id)] = {
            service_id: _parse_service_state(state, source, client_id, service_id)
            for service_id, state in services.items()
        }

    return parsed


def load_config(path: Path = CONFIG_PATH) -> ClientServicesConfig:
    """
    Load and structurally parse client_services.json.

    Returns:
        Mapping of client_id -> service_id -> {"display": bool, "dummy": bool}.

    Raises:
        InvalidClientServicesConfig: on any structural problem (not a
            critical field-level issue - those are validated separately by
            validate_startup_config, which logs and default-denies instead
            of crashing).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise InvalidClientServicesConfig(f"Failed to parse {path}: {e}") from e

    return _parse_clients_mapping(raw, str(path))


def validate_startup_config(config: ClientServicesConfig = None, path: Path = CONFIG_PATH) -> List[str]:
    """
    Validate field-level config correctness. Structural errors already raised
    by load_config()/_parse_clients_mapping(); this checks unknown ids and
    clients with nothing displayed.

    Logs every problem found. Returns the list of problem descriptions
    (useful for tests) - callers don't need to inspect it.
    """
    if config is None:
        config = load_config(path)

    known_clients = _known_clients()
    problems: List[str] = []

    for client_id, services in config.items():
        if client_id not in known_clients:
            problems.append(f"Unknown client identifier in client_services config: '{client_id}'")

        unknown_services = set(services.keys()) - set(KNOWN_SERVICE_IDS)
        for service_id in unknown_services:
            problems.append(f"Unknown service identifier for client '{client_id}': '{service_id}'")

        if not any(state.get("display") for state in services.values()):
            problems.append(f"Client '{client_id}' has no displayed services")

    for client_id in known_clients - config.keys():
        problems.append(f"Client '{client_id}' is not present in client_services config (defaults to no access)")

    for problem in problems:
        logger.error(f"client_services config validation issue: {problem}")

    if not problems:
        logger.info("client_services.json validated successfully")

    return problems


_config_cache: Optional[ClientServicesConfig] = None
_config_cache_mtime: Optional[float] = None


def get_client_services_config(force_refresh: bool = False) -> ClientServicesConfig:
    """
    Get the effective client services config, cached in memory and
    automatically reloaded whenever client_services.json's mtime changes -
    so a hand-edit takes effect on the next request without a server
    restart, without re-parsing the file on every single call.
    """
    global _config_cache, _config_cache_mtime

    try:
        current_mtime = CONFIG_PATH.stat().st_mtime
    except OSError as e:
        if _config_cache is not None:
            return _config_cache
        raise InvalidClientServicesConfig(f"Cannot read {CONFIG_PATH}: {type(e).__name__}: {e}") from e

    if not force_refresh and _config_cache is not None and current_mtime == _config_cache_mtime:
        return _config_cache

    _config_cache = load_config()
    _config_cache_mtime = current_mtime

    return _config_cache


def _service_state(client_id: str, service_id: str) -> ServiceState:
    config = get_client_services_config()
    return config.get(normalize_client_id(client_id), {}).get(service_id, _DEFAULT_STATE)


def is_service_enabled(client_id: str, service_id: str) -> bool:
    """
    The single centralized authorization check every dashboard module must
    use to decide nav visibility and route access.

    Unknown client or unknown service both default to DENIED.
    """
    if not client_id or not service_id:
        return False
    return _service_state(client_id, service_id)["display"]


def is_service_dummy(client_id: str, service_id: str) -> bool:
    """
    True if this (displayed) service should show the shared placeholder page
    instead of its real content. Meaningless when is_service_enabled() is
    False - the route is already blocked in that case.
    """
    if not client_id or not service_id:
        return False
    return _service_state(client_id, service_id)["dummy"]


def get_enabled_services(client_id: str) -> List[str]:
    """Displayed ('display': true) services for a client, ordered per KNOWN_SERVICE_IDS."""
    config = get_client_services_config()
    services = config.get(normalize_client_id(client_id), {})
    return [service_id for service_id in KNOWN_SERVICE_IDS if services.get(service_id, _DEFAULT_STATE)["display"]]
