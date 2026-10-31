"""
Authorization & Access Control Service for Yamaha EMS Assistant
Enforces chat ownership, tenant isolation, and input sanitization.
"""

import re
from typing import Any, Dict, Optional
from fastapi import Header, HTTPException, status
from pydantic import BaseModel
from src.db.chat_history import chat_repo

class UserContext(BaseModel):
    user_id: str
    consumer_id: int = 1
    email: Optional[str] = None
    name: Optional[str] = None
    role: str = "user"
    is_authenticated: bool = True

class AuthorizationService:
    """Enforces chat ownership and authorization checks."""

    @staticmethod
    def sanitize_identifier(ident: Optional[str], field_name: str = "id") -> str:
        """Validate and sanitize identifiers (UUIDs, alphanumeric, hyphens, underscores)."""
        if not ident or not str(ident).strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid {field_name}: cannot be empty."
            )
        val = str(ident).strip()
        if not re.match(r"^[a-zA-Z0-9_\-\.\:\@]{1,128}$", val):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid characters in {field_name}."
            )
        return val

    @classmethod
    def verify_chat_ownership(
        cls,
        chat_id: str,
        user_id: str,
        action: str = "access"
    ) -> Dict[str, Any]:
        """
        Verify that the chat exists and belongs to the given user.
        Raises 404 if chat doesn't exist, 403 if user is not the owner.
        """
        from src.db.chat_history import is_valid_uuid
        if not is_valid_uuid(chat_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat '{chat_id}' not found."
            )

        clean_chat_id = cls.sanitize_identifier(chat_id, "chat_id")
        clean_user_id = cls.sanitize_identifier(user_id, "user_id")

        chat = chat_repo.get_chat(clean_chat_id)
        if not chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chat '{clean_chat_id}' not found."
            )

        chat_owner = chat.get("user_id")
        if chat_owner:
            # Cross-user access check: Prevent tenant contamination
            from src.core.config import settings
            is_dev = settings.ENVIRONMENT in ("development", "test")
            dev_compatible = is_dev and (clean_user_id in ("default_user", "dev_user_1") or chat_owner == "default_user")
            if not dev_compatible and clean_user_id != "default_user" and chat_owner != clean_user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: You do not have permission to {action} this conversation."
                )
            if not is_dev and clean_user_id != chat_owner:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: Authenticated user mismatch for conversation '{clean_chat_id}'."
                )

        return chat

    @classmethod
    def resolve_user_context(
        cls,
        x_user_id: Optional[str] = None,
        fallback_user_id: Optional[str] = None
    ) -> UserContext:
        """Resolve authenticated user context from headers or payload."""
        uid = x_user_id or fallback_user_id or "default_user"
        clean_uid = cls.sanitize_identifier(uid, "user_id")
        return UserContext(user_id=clean_uid, is_authenticated=True)

auth_service = AuthorizationService()
