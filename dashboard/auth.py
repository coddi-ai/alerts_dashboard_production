"""
Authentication module for Multi-Technical-Alerts dashboard.

Provides user authentication and authorization for client data access.
"""

import hashlib
import os
from typing import Dict, List, Optional

from flask import current_app, has_request_context, session as flask_session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config.users import USERS


IDENTITY_PROOF_FIELD = "_identity_proof"
IDENTITY_PROOF_SALT = "tds-dashboard-identity-v1"


def should_process_login(n_clicks: int | None, n_submit: int | None) -> bool:
    """Return True only after an explicit login button or Enter action."""
    return bool(n_clicks or n_submit)


def _identity_serializer() -> URLSafeTimedSerializer:
    if not has_request_context():
        raise RuntimeError("Dashboard identity requires an active request")
    return URLSafeTimedSerializer(
        current_app.secret_key,
        salt=IDENTITY_PROOF_SALT,
    )


def add_identity_proof(user: Dict) -> Dict:
    """Attach a signed, time-limited identity proof to browser user data."""
    username = str(user.get("username", "")).strip()
    if not username or username not in USERS:
        raise ValueError("Cannot issue identity proof for an unknown dashboard user")
    enriched = dict(user)
    enriched[IDENTITY_PROOF_FIELD] = _identity_serializer().dumps(
        {"username": username}
    )
    return enriched


def current_dashboard_user_data() -> Dict | None:
    """Build signed browser-safe user data from the active Flask session."""
    username = resolve_authenticated_username()
    if not username:
        return None
    user = USERS.get(username)
    if not user:
        return None
    return add_identity_proof(
        {
            "username": username,
            "name": user.get("name", username),
            "role": user.get("role"),
            "clients": user.get("clients", []),
        }
    )


def resolve_authenticated_username(user_data: Dict | None = None) -> str | None:
    """Resolve identity from Flask or a valid signed dashboard proof."""
    if not has_request_context():
        return None

    claimed_username = ""
    if isinstance(user_data, dict):
        claimed_username = str(user_data.get("username", "")).strip()

    session_username = str(flask_session.get("dashboard_user", "")).strip()
    if session_username:
        if session_username not in USERS:
            return None
        if claimed_username and claimed_username != session_username:
            return None
        return session_username

    if not claimed_username or claimed_username not in USERS:
        return None
    proof = str((user_data or {}).get(IDENTITY_PROOF_FIELD, "")).strip()
    if not proof:
        return None

    max_age = int(os.getenv("DASHBOARD_IDENTITY_MAX_AGE_SECONDS", "43200"))
    try:
        payload = _identity_serializer().loads(proof, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    if str(payload.get("username", "")).strip() != claimed_username:
        return None
    return claimed_username


def hash_password(password: str) -> str:
    """
    Hash a password using SHA-256.
    
    Args:
        password: Plain text password
    
    Returns:
        Hashed password
    """
    return hashlib.sha256(password.encode()).hexdigest()


def authenticate_user(username: str, password: str) -> Optional[Dict]:
    """
    Authenticate user credentials.
    
    Args:
        username: Username
        password: Plain text password
    
    Returns:
        User info dict if authenticated, None otherwise
    """
    user = USERS.get(username)
    
    if user is None:
        return None
    
    # Hash provided password and compare
    if hash_password(password) == user['password']:
        return {
            'username': username,
            'name': user.get('name', username),
            'role': user['role'],
            'clients': user['clients']
        }
    
    return None


def get_user_permissions(user: Dict) -> List[str]:
    """
    Get list of clients user has access to.
    
    Args:
        user: User info dictionary
    
    Returns:
        List of client names
    """
    return user.get('clients', [])


def is_admin(user: Dict) -> bool:
    """
    Check if user has admin role.
    
    Args:
        user: User info dictionary
    
    Returns:
        True if admin, False otherwise
    """
    return user.get('role') == 'admin'


def can_access_client(user: Dict, client: str) -> bool:
    """
    Check if user can access specific client data.
    
    Args:
        user: User info dictionary
        client: Client name (e.g., 'CDA', 'EMIN')
    
    Returns:
        True if user has access, False otherwise
    """
    return client in get_user_permissions(user)
