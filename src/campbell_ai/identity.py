"""Identity adapter that reuses dashboard users, roles and client permissions."""

from __future__ import annotations

import re

from config.users import USERS, get_user
from src.campbell_ai.errors import (
    CampbellAuthenticationError,
    CampbellAuthorizationError,
    CampbellSessionError,
)
from src.campbell_ai.models import DashboardPrincipal


_CLIENT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$")


def normalize_client_id(client: str) -> str:
    normalized = str(client or "").strip().lower().replace(" ", "_")
    if not _CLIENT_PATTERN.fullmatch(normalized):
        raise CampbellAuthorizationError("Identificador de cliente invalido")
    return normalized


def normalize_session_id(session_id: str) -> str:
    normalized = str(session_id or "").strip()
    if not _SESSION_PATTERN.fullmatch(normalized):
        raise CampbellSessionError("Identificador de sesion invalido")
    return normalized


def resolve_dashboard_principal(username: str, company_id: str) -> DashboardPrincipal:
    """Resolve identity and authorize a client using the dashboard user registry."""
    normalized_username = str(username or "").strip()
    user = get_user(normalized_username)
    if not user:
        raise CampbellAuthenticationError("Usuario del dashboard no encontrado")

    requested_client = normalize_client_id(company_id)
    allowed_clients = [normalize_client_id(value) for value in user.get("clients", [])]
    if requested_client not in allowed_clients:
        raise CampbellAuthorizationError(
            f"El usuario no tiene acceso al cliente {requested_client.upper()}"
        )

    return DashboardPrincipal(
        username=normalized_username,
        role=str(user.get("role", "client")),
        company_id=requested_client,
        allowed_clients=allowed_clients,
    )


def known_dashboard_clients() -> list[str]:
    """Return normalized client IDs configured in the dashboard user registry."""
    return sorted(
        {
            normalize_client_id(client)
            for user in USERS.values()
            for client in user.get("clients", [])
        }
    )
