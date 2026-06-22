"""
Authentication module for Multi-Technical-Alerts dashboard.

Provides user authentication and authorization for client data access.
"""

import hashlib
from typing import Dict, List, Optional
from config.users import USERS


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
