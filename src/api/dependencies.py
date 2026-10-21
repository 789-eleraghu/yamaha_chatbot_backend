"""
FastAPI Dependencies for Authentication & User Context
"""

from typing import Optional
from fastapi import Header
from src.services.authorization import UserContext, auth_service

def get_current_user(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id")
) -> UserContext:
    """Resolve current user from header or fallback."""
    return auth_service.resolve_user_context(x_user_id=x_user_id)
