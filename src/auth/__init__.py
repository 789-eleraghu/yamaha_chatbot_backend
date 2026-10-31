"""
Authentication Module
JWT-based authentication for the Yamaha Energy Assistant API.
"""

from src.auth.jwt_handler import (
    create_access_token,
    verify_token,
    get_current_user,
    JWTPayload,
)
from src.auth.dependencies import require_auth, get_optional_user

__all__ = [
    "create_access_token",
    "verify_token",
    "get_current_user",
    "require_auth",
    "get_optional_user",
    "JWTPayload",
]
