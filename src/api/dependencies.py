"""
FastAPI Dependencies for Authentication & User Context
Supports both JWT authentication and legacy X-User-Id header.
"""

from typing import Optional
from fastapi import Header, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.auth.jwt_handler import verify_token, JWTPayload
from src.services.authorization import UserContext, auth_service

# HTTP Bearer token extractor (optional - allows unauthenticated requests)
security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_consumer_id: Optional[str] = Header(default=None, alias="X-Consumer-Id"),
) -> UserContext:
    """
    Resolve current user from JWT token or legacy headers.

    Priority:
    1. JWT Bearer token (if valid)
    2. X-User-Id / X-Consumer-Id headers (legacy)
    3. Default anonymous user
    """
    # Try JWT authentication first
    if credentials:
        try:
            jwt_payload = verify_token(credentials.credentials)
            return UserContext(
                user_id=jwt_payload.user_id,
                consumer_id=jwt_payload.consumer_id,
                email=jwt_payload.email,
                name=jwt_payload.name,
                role=jwt_payload.role,
                is_authenticated=True,
            )
        except Exception:
            pass  # Fall through to legacy auth

    # Legacy header authentication
    consumer_id = int(x_consumer_id) if x_consumer_id else 1
    if x_user_id:
        return UserContext(
            user_id=x_user_id,
            consumer_id=consumer_id,
            is_authenticated=True,
        )

    # Default anonymous user
    return auth_service.resolve_user_context(x_user_id=x_user_id)


async def require_jwt_auth(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
) -> JWTPayload:
    """
    Require valid JWT authentication.
    Use this for strictly protected endpoints.
    """
    return verify_token(credentials.credentials)
