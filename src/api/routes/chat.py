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

from src.agent import SSE_HEADERS, streaming_engine
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
    title: Optional[str] = Field(default=None, description="Alias for name")
    is_archived: Optional[bool] = Field(default=None, description="Archive flag")

class SetTitleRequest(BaseModel):
    title: Optional[str] = Field(default=None, description="New title")
    name: Optional[str] = Field(default=None, description="Alias for title")

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
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: UserContext = Depends(get_current_user)
):
    """
    List chats for the authenticated user ordered by updated_at DESC.
    Supports pagination via limit and offset parameters.

    Returns:
    - threads: List of chat objects
    - hasMore: Boolean indicating if more chats exist
    - total: Total count of chats (optional, for UI)
    """
    target_user = user_id or current_user.user_id
    chats = chat_service.list_user_chats(
        user_id=target_user,
        include_archived=include_archived,
        limit=limit + 1,  # Fetch one extra to check hasMore
        offset=offset
    )

    has_more = len(chats) > limit
    if has_more:
        chats = chats[:limit]  # Remove the extra item

    # Ensure both name and title are present on every thread
    for c in chats:
        c["title"] = c.get("name") or "New Chat"

    return {
        "threads": chats,
        "hasMore": has_more,
        "offset": offset,
        "limit": limit,
    }

@router.post("/chats")
async def create_chat(
    payload: CreateChatRequest,
    current_user: UserContext = Depends(get_current_user)
):
    """Create a new chat conversation."""
    target_user = payload.user_id if payload.user_id != "default_user" else current_user.user_id
    res = chat_service.create_chat(user_id=target_user, name=payload.name, chat_id=payload.chat_id)
    if isinstance(res, dict):
        res["title"] = res.get("name") or "New Chat"
    return res

@router.get("/chats/{chat_id}")
async def get_chat(
    chat_id: str,
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Retrieve chat details with ownership validation."""
    target_user = user_id or current_user.user_id
    res = chat_service.get_chat(chat_id=chat_id, user_id=target_user)
    if isinstance(res, dict):
        res["title"] = res.get("name") or "New Chat"
    return res

@router.patch("/chats/{chat_id}")
async def update_chat(
    chat_id: str,
    payload: UpdateChatRequest,
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Update chat title or archive state."""
    target_user = user_id or current_user.user_id
    new_title = payload.name if payload.name is not None else payload.title
    res = chat_service.update_chat(chat_id=chat_id, user_id=target_user, name=new_title, is_archived=payload.is_archived)
    if isinstance(res, dict):
        res["title"] = res.get("name") or "New Chat"
    return res

@router.post("/chats/{chat_id}/title")
@router.put("/chats/{chat_id}/title")
async def set_chat_title_endpoint(
    chat_id: str,
    payload: SetTitleRequest,
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Explicitly set or rename chat title."""
    target_user = user_id or current_user.user_id
    new_title = payload.title or payload.name
    if not new_title:
        raise HTTPException(status_code=400, detail="Title is required")
    return chat_service.update_chat(chat_id=chat_id, user_id=target_user, name=new_title)

@router.post("/chats/{chat_id}/generate-title")
async def generate_chat_title_endpoint(
    chat_id: str,
    user_id: Optional[str] = Query(default=None),
    current_user: UserContext = Depends(get_current_user)
):
    """Generate and persist a clean contextual title based on conversation content."""
    from src.db.chat_history import async_generate_chat_title
    target_user = user_id or current_user.user_id
    chat = chat_service.get_chat(chat_id=chat_id, user_id=target_user)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    messages = chat_service.get_chat_messages(chat_id=chat_id, user_id=target_user, limit=5)
    context_texts = [m.get("content", "") for m in messages if m.get("role") == "user" and m.get("content")]
    context = " | ".join(context_texts) if context_texts else (chat.get("name") or "Yamaha Energy Query")

    new_title = await async_generate_chat_title(context)
    chat_service.update_chat(chat_id=chat_id, user_id=target_user, name=new_title)
    return {"chat_id": chat_id, "title": new_title, "name": new_title}

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

def _transform_messages_for_frontend(messages: List[Dict[str, Any]], format_type: str = "assistant_ui") -> List[Dict[str, Any]]:
    """
    Transform raw database messages into frontend-friendly format.

    Format types:
    - "assistant_ui" (default): Compatible with assistant-ui / AI SDK UIMessage format.
      Tool calls are embedded as parts within assistant messages (no role="tool").
    - "raw": Raw database format with role='tool' messages (causes frontend errors)

    The assistant_ui format groups tool messages with their following assistant message,
    embedding them as tool-invocation parts that the UI library can render.

    Charts are sent as tool-invocation parts with chart tool names (create_breakdown_chart, etc.)
    matching the SSE streaming format so frontend can render them.
    """
    import json as json_module

    # Chart tool names the frontend recognizes
    CHART_TOOL_NAMES = {
        "create_breakdown_chart",
        "create_time_series_chart",
        "create_demand_utilization_gauge",
        "create_gauge_chart",
        "create_load_heatmap",
        "create_heatmap_chart",
        "create_shift_comparison_chart",
        "create_correlation_scatter_plot",
        "create_visualization",
        "create_chart",
        "create_power_quality_chart",
        "create_specialized_chart",
        "create_comparison_chart",
        "aggregate_energy_telemetry",
    }

    def _get_chart_tool_name(chart_config: dict) -> str:
        """Determine appropriate chart tool name based on chart_type."""
        chart_type = chart_config.get("chart_type", "bar")
        if chart_type in ("line", "area", "stacked_area"):
            return "create_time_series_chart"
        elif chart_type == "gauge":
            return "create_demand_utilization_gauge"
        elif chart_type == "heatmap":
            return "create_load_heatmap"
        elif chart_type in ("grouped_bar", "stacked_bar"):
            return "create_shift_comparison_chart"
        else:
            return "create_breakdown_chart"

    result = []
    pending_tools = []  # Collect tool messages to embed in next assistant message

    for msg in messages:
        role = msg.get("role")
        metadata = msg.get("metadata", {})

        if role == "user":
            # Clear pending tools from any prior abandoned/unanswered turn so they don't leak
            pending_tools.clear()
            result.append({
                "id": str(msg.get("message_id")),
                "role": "user",
                "content": msg.get("content", ""),
                "createdAt": msg.get("created_at"),
            })

        elif role == "tool":
            # Parse tool output content
            try:
                content = msg.get("content", "")
                tool_output = json_module.loads(content) if content else {}
            except (json_module.JSONDecodeError, TypeError):
                tool_output = {"raw": msg.get("content", "")}

            # Extract chart_config - prefer output (has full data) over metadata (summary only)
            chart_config = None
            if isinstance(tool_output, dict):
                if "chart_config" in tool_output:
                    chart_config = tool_output["chart_config"]
                elif tool_output.get("chart_type") and tool_output.get("series"):
                    # The output itself is a chart config with data
                    chart_config = tool_output
            # Only use metadata as fallback if output doesn't have chart
            if not chart_config and metadata.get("chart_config"):
                chart_config = metadata["chart_config"]

            tool_name = metadata.get("tool_name")

            # Store tool info to embed in next assistant message
            pending_tools.append({
                "toolCallId": metadata.get("tool_call_id"),
                "toolName": tool_name,
                "args": metadata.get("tool_input", {}),
                "result": tool_output,
                "chartConfig": chart_config,
                "isChartTool": tool_name in CHART_TOOL_NAMES,
            })

        elif role == "assistant":
            # Build parts array for assistant message (assistant-ui format)
            parts = []
            seen_call_ids = set()
            chart_added = False

            # Add tool invocation parts (from pending tools) with strict deduplication
            for tool in pending_tools:
                cid = tool.get("toolCallId")
                if cid and cid in seen_call_ids:
                    continue
                if cid:
                    seen_call_ids.add(cid)

                t_name = tool["toolName"] or "unknown_tool"
                is_chart = tool.get("isChartTool") or (t_name in CHART_TOOL_NAMES) or bool(tool.get("chartConfig"))

                if is_chart:
                    if chart_added:
                        # Skip duplicate chart tool in the same assistant turn
                        continue
                    chart_added = True

                parts.append({
                    "type": f"tool-{t_name}",
                    "toolCallId": tool["toolCallId"],
                    "toolName": t_name,
                    "state": "output-available",
                    "input": tool["args"],
                    "output": tool["result"],
                    "args": tool["args"],
                    "result": tool["result"],
                })

                # If tool has chart config and is NOT already a chart tool,
                # add a synthetic chart tool invocation for frontend rendering ONLY if no chart added
                if tool.get("chartConfig") and not tool.get("isChartTool") and not chart_added:
                    chart_config = tool["chartConfig"]
                    chart_tool_name = _get_chart_tool_name(chart_config)
                    chart_call_id = f"chart_{tool['toolCallId']}"
                    chart_args = {
                        "chart_type": chart_config.get("chart_type", "bar"),
                        "title": chart_config.get("title", "Energy Visualization"),
                    }
                    parts.append({
                        "type": f"tool-{chart_tool_name}",
                        "toolCallId": chart_call_id,
                        "toolName": chart_tool_name,
                        "state": "output-available",
                        "input": chart_args,
                        "output": chart_config,
                        "args": chart_args,
                        "result": chart_config,
                    })
                    chart_added = True

            # Add text content as part
            content = msg.get("content", "")
            if content:
                parts.append({
                    "type": "text",
                    "text": content,
                })

            # Also add chart from assistant metadata ONLY if no chart tool was already added
            if metadata.get("chart") and not chart_added:
                chart_config = metadata["chart"]
                chart_tool_name = _get_chart_tool_name(chart_config)
                chart_call_id = f"chart_meta_{msg.get('message_id')}"
                chart_args = {
                    "chart_type": chart_config.get("chart_type", "bar"),
                    "title": chart_config.get("title", "Energy Visualization"),
                }
                parts.append({
                    "type": f"tool-{chart_tool_name}",
                    "toolCallId": chart_call_id,
                    "toolName": chart_tool_name,
                    "state": "output-available",
                    "input": chart_args,
                    "output": chart_config,
                    "args": chart_args,
                    "result": chart_config,
                })
                chart_added = True

            assistant_msg = {
                "id": str(msg.get("message_id")),
                "role": "assistant",
                "content": content,  # Keep content for backward compatibility
                "parts": parts,      # Structured parts for UI rendering
                "createdAt": msg.get("created_at"),
                "model": msg.get("model"),
            }

            # Clear pending tools after attaching to assistant message
            pending_tools = []

            result.append(assistant_msg)

    return result


@router.get("/chats/{chat_id}/messages")
async def get_chat_messages(
    chat_id: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: Optional[str] = Query(default=None),
    format: str = Query(default="assistant_ui", description="Format: 'assistant_ui' (default) or 'raw'"),
    current_user: UserContext = Depends(get_current_user)
):
    """
    Retrieve ordered message history for a chat with pagination.

    Format options:
    - "assistant_ui" (default): Compatible with assistant-ui / AI SDK UIMessage format.
      Tool calls embedded as parts within assistant messages with chartConfig for re-rendering.
    - "raw": Raw database format with role='tool' messages (causes frontend errors)

    Returns:
    - messages: List of messages
    - hasMore: Boolean indicating if more messages exist
    """
    target_user = user_id or current_user.user_id
    raw_messages = chat_service.get_chat_messages(
        chat_id=chat_id,
        user_id=target_user,
        limit=limit + 1,  # Fetch one extra to check hasMore
        offset=offset
    )

    has_more = len(raw_messages) > limit
    if has_more:
        raw_messages = raw_messages[:limit]

    if format == "raw":
        return {
            "messages": raw_messages,
            "hasMore": has_more,
            "offset": offset,
            "limit": limit,
        }

    transformed = _transform_messages_for_frontend(raw_messages, format_type=format)
    return {
        "messages": transformed,
        "hasMore": has_more,
        "offset": offset,
        "limit": limit,
    }


@router.get("/chats/{chat_id}/full")
async def get_chat_with_messages(
    chat_id: str,
    user_id: Optional[str] = Query(default=None),
    format: str = Query(default="assistant_ui", description="Format: 'assistant_ui' (default) or 'raw'"),
    current_user: UserContext = Depends(get_current_user)
):
    """
    Retrieve full chat session with all messages.

    This endpoint is optimized for frontend loading when navigating to a chat by UUID.
    Returns chat metadata and all messages including chart configurations for re-rendering.

    Format options:
    - "assistant_ui" (default): Compatible with assistant-ui / AI SDK UIMessage format.
      Tool calls embedded as parts within assistant messages with chartConfig for re-rendering.
    - "raw": Raw database format (causes frontend errors)

    Response includes:
    - Chat metadata (id, name, timestamps)
    - All messages with parts array containing tool invocations and charts
    """
    target_user = user_id or current_user.user_id
    chat_data = chat_repo.get_chat_with_messages(chat_id)

    if not chat_data:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Verify ownership (allow in development or if user matches)
    chat_owner = chat_data.get("user_id")
    if chat_owner and target_user != "default_user" and chat_owner != target_user:
        from src.core.config import settings
        if settings.ENVIRONMENT not in ("development", "test"):
            raise HTTPException(status_code=403, detail="Access denied")

    # Transform messages for frontend compatibility
    if format != "raw" and chat_data.get("messages"):
        chat_data["messages"] = _transform_messages_for_frontend(chat_data["messages"], format_type=format)

    return chat_data

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
    resolved_chat_id, chat_info = await chat_service.get_or_create_active_chat_async(
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

    # Build headers including thread identifier and title
    response_headers = dict(SSE_HEADERS)
    response_headers["X-Chat-Id"] = resolved_chat_id
    current_title = chat_info.get("name")
    if current_title:
        import urllib.parse
        response_headers["X-Chat-Title"] = urllib.parse.quote(str(current_title))
        response_headers["Access-Control-Expose-Headers"] = "X-Chat-Id, X-Chat-Title"

    # Return SSE streaming response
    return StreamingResponse(
        streaming_engine.create_event_stream(
            prompt=user_prompt,
            user_id=target_user,
            chat_id=resolved_chat_id,
            user_msg_id=user_msg_id,
            convo_history=convo_history,
            model_name=model_name,
            chat_title=current_title if chat_info.get("title_generated") else None,
        ),
        headers=response_headers
    )
