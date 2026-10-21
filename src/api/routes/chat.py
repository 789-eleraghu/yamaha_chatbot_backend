"""
Chat Endpoints & Real-Time Streaming Router
Provides REST chat management and assistant-ui / AI SDK SSE streaming.
Delegates orchestration, persistence, and authorization to dedicated services.
"""

import json
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.agent.streaming import SSE_HEADERS, streaming_engine
from src.api.dependencies import get_current_user
from src.db.chat_history import chat_repo
from src.services.authorization import UserContext, auth_service
from src.services.chat_service import chat_service

router = APIRouter(tags=["Chat & History"])

# -------------------------------------------------------------
# Pydantic Schemas for Chat Management
# -------------------------------------------------------------

class CreateChatRequest(BaseModel):
    user_id: Optional[str] = Field(default="default_user", description="Chat owner user ID")
    name: Optional[str] = Field(default=None, description="Optional title for the chat")
    chat_id: Optional[str] = Field(default=None, description="Optional custom UUID/ID")

class UpdateChatRequest(BaseModel):
    name: Optional[str] = Field(default=None, description="New title for the chat")
    is_archived: Optional[bool] = Field(default=None, description="Archive flag")

class StreamChatRequest(BaseModel):
    id: Optional[str] = Field(default=None, description="Thread or Chat ID")
    chat_id: Optional[str] = Field(default=None, description="Alternative field for Chat ID")
    session_id: Optional[str] = Field(default=None, description="Alternative session identifier")
    user_id: Optional[str] = Field(default="default_user", description="Owner user ID")
    messages: Optional[List[Dict[str, Any]]] = Field(default=None, description="List of messages in conversation")
    message: Optional[str] = Field(default=None, description="Single prompt message (legacy format)")
    config: Optional[Dict[str, Any]] = Field(default=None, description="Client configuration (modelName, etc.)")

def extract_user_text(req: StreamChatRequest) -> str:
    """Extract prompt text from request payload."""
    if req.message:
        return req.message.strip()
    if req.messages:
        for m in reversed(req.messages):
            if m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, str):
                    return content.strip()
                elif isinstance(content, list):
                    parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            parts.append(part.get("text", ""))
                    return " ".join(parts).strip()
                parts = m.get("parts")
                if isinstance(parts, list):
                    text_parts = [
                        p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    return " ".join(text_parts).strip()
    return ""

# -------------------------------------------------------------
# REST Endpoints for Chats & Message History
# -------------------------------------------------------------

@router.get("/chats")
async def list_chats(
    user_id: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=50),
    current_user: UserContext = Depends(get_current_user)
):
    """List chats for the authenticated user ordered by updated_at DESC."""
    target_user = user_id or current_user.user_id
    return chat_service.list_user_chats(user_id=target_user, include_archived=include_archived, limit=limit)

@router.post("/chats")
async def create_chat(
    payload: CreateChatRequest,
    current_user: UserContext = Depends(get_current_user)
):
    """Create a new chat conversation."""
    target_user = payload.user_id if payload.user_id != "default_user" else current_user.user_id
    return chat_service.create_chat(user_id=target_user, name=payload.name, chat_id=payload.chat_id)

@router.get("/chats/{chat_id}")
async def get_chat(
    chat_id: str,
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Retrieve chat details with ownership validation."""
    target_user = user_id or current_user.user_id
    return chat_service.get_chat(chat_id=chat_id, user_id=target_user)

@router.patch("/chats/{chat_id}")
async def update_chat(
    chat_id: str,
    payload: UpdateChatRequest,
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Update chat title or archive state."""
    target_user = user_id or current_user.user_id
    return chat_service.update_chat(chat_id=chat_id, user_id=target_user, name=payload.name, is_archived=payload.is_archived)

@router.post("/chats/{chat_id}/archive")
async def archive_chat(
    chat_id: str,
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Archive chat conversation."""
    target_user = user_id or current_user.user_id
    success = chat_service.archive_chat(chat_id=chat_id, user_id=target_user, archive_flag=True)
    if not success:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "archived", "chat_id": chat_id}

@router.post("/chats/{chat_id}/unarchive")
async def unarchive_chat(
    chat_id: str,
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Unarchive chat conversation."""
    target_user = user_id or current_user.user_id
    success = chat_service.archive_chat(chat_id=chat_id, user_id=target_user, archive_flag=False)
    if not success:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "unarchived", "chat_id": chat_id}

@router.delete("/chats/{chat_id}")
async def delete_chat(
    chat_id: str,
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Delete chat and all associated history/events."""
    target_user = user_id or current_user.user_id
    success = chat_service.delete_chat(chat_id=chat_id, user_id=target_user)
    if not success:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"status": "deleted", "chat_id": chat_id}

@router.get("/chats/{chat_id}/messages")
async def get_chat_messages(
    chat_id: str,
    limit: Optional[int] = Query(default=None),
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Retrieve ordered message history for a chat."""
    target_user = user_id or current_user.user_id
    return chat_service.get_chat_messages(chat_id=chat_id, user_id=target_user, limit=limit)

@router.get("/chats/{chat_id}/events")
async def get_chat_events(
    chat_id: str,
    limit: int = Query(default=50),
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Retrieve real-time event logs for a chat."""
    target_user = user_id or current_user.user_id
    return chat_service.get_chat_events(chat_id=chat_id, user_id=target_user, limit=limit)

@router.get("/telemetry/live")
async def get_live_telemetry(device: Optional[str] = Query(default=None)):
    """Retrieve Component 10 real-time device telemetry snapshots."""
    readings = chat_repo.get_live_device_telemetry(device)
    import datetime
    return {
        "status": "success",
        "timestamp_ist": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(readings),
        "telemetry": readings
    }

# -------------------------------------------------------------
# Main Chat Streaming Endpoint (assistant-ui & AI SDK Compatible)
# -------------------------------------------------------------

@router.post("/chat")
async def chat_streaming_endpoint(
    request: Request,
    current_user: UserContext = Depends(get_current_user)
):
    """
    Unified streaming & natural language query endpoint.
    Emits real-time SSE stream adhering to assistant-ui UIMessage stream protocol.
    Persists chats into `chats` table and messages into `chat_history`.
    """
    body_bytes = await request.body()
    try:
        raw_json = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:
        raw_json = {}

    req = StreamChatRequest(**raw_json)
    user_prompt = extract_user_text(req)
    if not user_prompt:
        user_prompt = "Hello"

    # Resolve target user and chat ID
    target_user = req.user_id if (req.user_id and req.user_id != "default_user") else current_user.user_id
    chat_id = req.id or req.chat_id or req.session_id

    # Retrieve or create active chat session with ownership verification
    resolved_chat_id, _ = await chat_service.get_or_create_active_chat_async(
        chat_id=chat_id,
        user_id=target_user,
        context=user_prompt
    )

    model_name = req.config.get("modelName") if req.config else "qwen.qwen3-vl-235b-a22b"

    # Persist user message to chat history
    user_msg_id = chat_service.save_user_turn(
        chat_id=resolved_chat_id,
        prompt=user_prompt,
        model_name=model_name
    )

    # Load prior conversation history for multi-turn awareness
    convo_history = chat_service.load_langchain_history(
        chat_id=resolved_chat_id,
        current_user_msg_id=user_msg_id,
        limit=8
    )

    # Return SSE streaming response
    return StreamingResponse(
        streaming_engine.create_event_stream(
            prompt=user_prompt,
            user_id=target_user,
            chat_id=resolved_chat_id,
            user_msg_id=user_msg_id,
            convo_history=convo_history,
            model_name=model_name
        ),
        headers=SSE_HEADERS
    )
