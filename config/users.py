"""
User authentication database for Multi-Technical-Alerts.

Contains user credentials and permissions for dashboard access.
"""

import hashlib
from typing import Dict, List


def hash_password(password: str) -> str:
    """
    Hash a password using SHA-256.
    
    Args:
        password: Plain text password
    
    Returns:
        Hexadecimal hash string
    """
    return hashlib.sha256(password.encode()).hexdigest()


# User database
# Format: {username: {"password": hashed_password, "name": display_name, "clients": [allowed_clients]}}
USERS: Dict[str, Dict[str, any]] = {
    "admin": {
        "password": hash_password("admin123"),  # Change in production!
        "name": "Administrator",
        "clients": ["CDA", "EMIN", "ENEX"],  # Access to all clients
        "role": "admin"
    },
    "cda_user": {
        "password": hash_password("CdA.2026"),  # Change in production!
        "name": "CDA",
        "clients": ["CDA"],  # Only CDA data
        "role": "client"
    },
    "emin_user": {
        "password": hash_password("Emin.2026"),  # Change in production!
        "name": "EMIN",
        "clients": ["EMIN"],  # Only EMIN data
        "role": "client"
    },
    "enex_user": {
        "password": hash_password("Enex.2026"),  # Change in production!
        "name": "ENEX User",
        "clients": ["ENEX"],  # Only ENEX data
        "role": "client"
    },
    # Arturo Casanga - CDA Stake holder with access to CDA data
    "a.casanga": {
        "password": hash_password("Teck.2026"),  # Change in production!
        "name": "Arturo Casanga",
        "clients": ["CDA"],  # Only CDA data
        "role": "client"
    },
    
    # Eduardo Carvajal - Coddi Administrator with access to cda data
    "e.carvajal": {
        "password": hash_password("Coddi.2026"),  # Change in production!
        "name": "Eduardo Carvajal",
        "clients": ["CDA"],  # Only CDA data
        "role": "admin"
    },
    # Pedro Cancino - Coddi Administrator with access to all data
    "p.cancino": {
        "password": hash_password("Coddi.2026"),  # Change in production!
        "name": "Pedro Cancino",
        "clients": ["CDA", "EMIN", "ENEX"],  # Access to all clients
        "role": "admin"
    },
    # Patricio Ortiz - Coddi Administrator with access to all data
    "p.ortiz": {
        "password": hash_password("Coddi.2026"),  # Change in production!
        "name": "Patricio Ortiz",
        "clients": ["CDA", "EMIN", "ENEX"],  # Access to all clients
        "role": "admin"
    },
    # Francisco Vilches - Coddi Administrator with access to all data
    "f.vilches": {
        "password": hash_password("Coddi.2026"),  # Change in production!
        "name": "Francisco Vilches",
        "clients": ["CDA", "EMIN", "ENEX"],  # Access to all clients
        "role": "admin"
    },
    # Data Team - Coddi Administrator with access to all data
    "data_team": {
        "password": hash_password("Coddi.2026"),  # Change in production!
        "name": "Data Team",
        "clients": ["CDA", "EMIN", "ENEX"],  # Access to all clients
        "role": "admin"
    }
    
}


def get_user(username: str) -> Dict[str, any] | None:
    """
    Get user information by username.
    
    Args:
        username: Username to lookup
    
    Returns:
        User dict or None if not found
    """
    return USERS.get(username)


def verify_user(username: str, password: str) -> bool:
    """
    Verify user credentials.
    
    Args:
        username: Username
        password: Plain text password
    
    Returns:
        True if credentials valid, False otherwise
    """
    user = get_user(username)
    if user is None:
        return False
    
    return user["password"] == hash_password(password)


def get_user_clients(username: str) -> List[str]:
    """
    Get list of clients a user can access.
    
    Args:
        username: Username
    
    Returns:
        List of client names (empty if user not found)
    """
    user = get_user(username)
    if user is None:
        return []
    
    return user.get("clients", [])


def is_admin(username: str) -> bool:
    """
    Check if user is admin.
    
    Args:
        username: Username
    
    Returns:
        True if user is admin, False otherwise
    """
    user = get_user(username)
    if user is None:
        return False
    
    return user.get("role") == "admin"
