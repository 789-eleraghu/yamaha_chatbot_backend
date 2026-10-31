"""
JWT Token Handler
Creates and validates JWT tokens for authentication.
"""

import datetime
from typing import Optional
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, status

from src.core.config import settings


@dataclass
class JWTPayload:
    """JWT token payload structure."""
    user_id: str
    consumer_id: int
    email: Optional[str] = None
    name: Optional[str] = None
    role: str = "user"
    exp: Optional[datetime.datetime] = None
    iat: Optional[datetime.datetime] = None


def create_access_token(
    user_id: str,
    consumer_id: int,
    email: Optional[str] = None,
    name: Optional[str] = None,
    role: str = "user",
    expires_delta: Optional[datetime.timedelta] = None
) -> str:
    """
    Create a JWT access token.

    For development, tokens have a very long expiry (365 days by default).
    In production, this should be reduced significantly.
    """
    now = datetime.datetime.utcnow()

    if expires_delta:
        expire = now + expires_delta
    else:
        # Default: 365 days for development
        expire = now + datetime.timedelta(days=settings.JWT_EXPIRY_DAYS)

    payload = {
        "sub": user_id,
        "consumer_id": consumer_id,
        "email": email,
        "name": name,
        "role": role,
        "iat": now,
        "exp": expire,
    }

    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token


def verify_token(token: str) -> JWTPayload:
    """
    Verify and decode a JWT token.

    Raises HTTPException if token is invalid or expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )

        return JWTPayload(
            user_id=payload.get("sub"),
            consumer_id=payload.get("consumer_id"),
            email=payload.get("email"),
            name=payload.get("name"),
            role=payload.get("role", "user"),
            exp=datetime.datetime.fromtimestamp(payload.get("exp")) if payload.get("exp") else None,
            iat=datetime.datetime.fromtimestamp(payload.get("iat")) if payload.get("iat") else None,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(token: str) -> JWTPayload:
    """
    Get the current user from a JWT token.
    Alias for verify_token for semantic clarity.
    """
    return verify_token(token)


def create_dev_token(consumer_id: int = 1) -> str:
    """
    Create a development token that never expires (well, expires in 100 years).
    Only for development/testing purposes.
    """
    return create_access_token(
        user_id=f"dev_user_{consumer_id}",
        consumer_id=consumer_id,
        email=f"dev{consumer_id}@yamaha.local",
        name=f"Development User {consumer_id}",
        role="admin",
        expires_delta=datetime.timedelta(days=36500)  # ~100 years
    )
