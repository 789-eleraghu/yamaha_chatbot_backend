"""
Authentication Routes
Endpoints for token generation and user info.
"""

from typing import Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException

from src.auth.jwt_handler import create_access_token, create_dev_token, JWTPayload
from src.auth.dependencies import require_auth
from src.core.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


class TokenRequest(BaseModel):
    """Request body for token generation."""
    user_id: str
    consumer_id: int
    email: Optional[str] = None
    name: Optional[str] = None


class TokenResponse(BaseModel):
    """Response containing access token."""
    access_token: str
    token_type: str = "bearer"
    user_id: str
    consumer_id: int


class UserResponse(BaseModel):
    """Current user information."""
    user_id: str
    consumer_id: int
    email: Optional[str]
    name: Optional[str]
    role: str


@router.post("/token", response_model=TokenResponse)
async def generate_token(request: TokenRequest):
    """
    Generate a JWT access token.

    In development mode, this endpoint is open for easy testing.
    In production, this should be protected or replaced with proper OAuth flow.
    """
    if settings.ENVIRONMENT != "development":
        raise HTTPException(
            status_code=403,
            detail="Token generation endpoint only available in development"
        )

    token = create_access_token(
        user_id=request.user_id,
        consumer_id=request.consumer_id,
        email=request.email,
        name=request.name,
    )

    return TokenResponse(
        access_token=token,
        user_id=request.user_id,
        consumer_id=request.consumer_id,
    )


@router.get("/dev-token", response_model=TokenResponse)
async def get_dev_token(consumer_id: int = 1):
    """
    Get a development token that never expires.
    Only available in development environment.

    Usage: GET /api/auth/dev-token?consumer_id=1
    """
    if settings.ENVIRONMENT != "development":
        raise HTTPException(
            status_code=403,
            detail="Development token endpoint only available in development"
        )

    token = create_dev_token(consumer_id=consumer_id)
    user_id = f"dev_user_{consumer_id}"

    return TokenResponse(
        access_token=token,
        user_id=user_id,
        consumer_id=consumer_id,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(user: JWTPayload = Depends(require_auth)):
    """
    Get current authenticated user information.
    Requires valid JWT token in Authorization header.
    """
    return UserResponse(
        user_id=user.user_id,
        consumer_id=user.consumer_id,
        email=user.email,
        name=user.name,
        role=user.role,
    )


@router.get("/verify")
async def verify_token_endpoint(user: JWTPayload = Depends(require_auth)):
    """
    Verify if the current token is valid.
    Returns token metadata if valid, 401 if invalid.
    """
    return {
        "valid": True,
        "user_id": user.user_id,
        "consumer_id": user.consumer_id,
        "expires_at": user.exp.isoformat() if user.exp else None,
    }
