"""
FastAPI Authentication Dependencies
Dependency injection for route protection.
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.auth.jwt_handler import verify_token, JWTPayload

# HTTP Bearer token extractor
security = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> JWTPayload:
    """
    Dependency that requires a valid JWT token.
    Use this for protected endpoints.

    Usage:
        @router.get("/protected")
        async def protected_route(user: JWTPayload = Depends(require_auth)):
            return {"user_id": user.user_id}
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_token(credentials.credentials)


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[JWTPayload]:
    """
    Dependency that optionally validates a JWT token.
    Returns None if no token is provided, but validates if one is.

    Usage:
        @router.get("/optional-auth")
        async def optional_route(user: Optional[JWTPayload] = Depends(get_optional_user)):
            if user:
                return {"user_id": user.user_id}
            return {"message": "anonymous"}
    """
    if not credentials:
        return None

    try:
        return verify_token(credentials.credentials)
    except HTTPException:
        return None
