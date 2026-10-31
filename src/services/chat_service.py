"""
Chat Lifecycle & Persistence Service
Encapsulates thread creation, message persistence, event auditing,
and history conversion for LangGraph execution.
"""

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from src.db.chat_history import async_generate_chat_title, chat_repo, generate_chat_title
from src.services.authorization import auth_service

# Type alias for chat creation return type
Tuple_Chat = Tuple[str, Dict[str, Any]]

class ChatService:
    """Manages chat persistence, lifecycle, and message retrieval."""

    @staticmethod
    def list_user_chats(user_id: str, include_archived: bool = False, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        clean_user_id = auth_service.sanitize_identifier(user_id, "user_id")
        chats = chat_repo.list_chats(user_id=clean_user_id, include_archived=include_archived, limit=limit, offset=offset)
        if clean_user_id in ("dev_user_1", "default_user") and not chats:
            chats = chat_repo.list_chats(user_id="default_user", include_archived=include_archived, limit=limit, offset=offset)
        return chats

    @staticmethod
    def create_chat(user_id: str, name: Optional[str] = None, chat_id: Optional[str] = None) -> Dict[str, Any]:
        clean_user_id = auth_service.sanitize_identifier(user_id, "user_id")
        from src.db.chat_history import is_valid_uuid
        if chat_id and is_valid_uuid(chat_id):
            clean_chat_id = auth_service.sanitize_identifier(chat_id, "chat_id")
        else:
            clean_chat_id = str(uuid.uuid4())
        return chat_repo.create_chat(user_id=clean_user_id, name=name, chat_id=clean_chat_id)

    @staticmethod
    def get_chat(chat_id: str, user_id: str) -> Dict[str, Any]:
        return auth_service.verify_chat_ownership(chat_id, user_id, action="view")

    @staticmethod
    def update_chat(
        chat_id: str,
        user_id: str,
        name: Optional[str] = None,
        is_archived: Optional[bool] = None
    ) -> Dict[str, Any]:
        auth_service.verify_chat_ownership(chat_id, user_id, action="modify")
        if name is not None:
            chat_repo.set_chat_title(chat_id, name)
        if is_archived is not None:
            chat_repo.archive_chat(chat_id, is_archived)
        return chat_repo.get_chat(chat_id)

    @staticmethod
    def archive_chat(chat_id: str, user_id: str, archive_flag: bool = True) -> bool:
        auth_service.verify_chat_ownership(chat_id, user_id, action="archive")
        return chat_repo.archive_chat(chat_id, archive_flag)

    @staticmethod
    def delete_chat(chat_id: str, user_id: str) -> bool:
        auth_service.verify_chat_ownership(chat_id, user_id, action="delete")
        return chat_repo.delete_chat(chat_id)

    @staticmethod
    def get_chat_messages(chat_id: str, user_id: str, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        auth_service.verify_chat_ownership(chat_id, user_id, action="view messages for")
        return chat_repo.get_chat_messages(chat_id, limit=limit, offset=offset)

    @staticmethod
    def get_chat_events(chat_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        auth_service.verify_chat_ownership(chat_id, user_id, action="view audit events for")
        return chat_repo.get_realtime_events(chat_id, limit=limit)

    @staticmethod
    def get_or_create_active_chat(chat_id: Optional[str], user_id: str, initial_prompt: str) -> Tuple_Chat:
        clean_user_id = auth_service.sanitize_identifier(user_id, "user_id")
        from src.db.chat_history import is_valid_uuid
        if chat_id and is_valid_uuid(chat_id):
            resolved_chat_id = auth_service.sanitize_identifier(chat_id, "chat_id")
        else:
            resolved_chat_id = str(uuid.uuid4())

        existing_chat = chat_repo.get_chat(resolved_chat_id)
        if not existing_chat:
            title = generate_chat_title(initial_prompt)
            existing_chat = chat_repo.create_chat(user_id=clean_user_id, name=title, chat_id=resolved_chat_id)
        else:
            if existing_chat.get("user_id") != clean_user_id:
                auth_service.verify_chat_ownership(resolved_chat_id, clean_user_id, action="post to")
            if existing_chat.get("name") in ("New Chat", "Yamaha Energy Assistant", None, ""):
                title = generate_chat_title(initial_prompt)
                chat_repo.set_chat_title(resolved_chat_id, title)
                existing_chat["name"] = title

        return resolved_chat_id, existing_chat

    @staticmethod
    async def get_or_create_active_chat_async(chat_id: Optional[str], user_id: str, context: Any) -> Tuple_Chat:
        """
        Get or create an active chat session.

        Returns: (chat_id, chat_dict) where chat_dict includes:
        - All chat fields
        - 'title_generated': True if a new title was generated this call
        - 'name': The current/updated title
        """
        import asyncio
        clean_user_id = auth_service.sanitize_identifier(user_id, "user_id")
        from src.db.chat_history import is_valid_uuid
        if chat_id and is_valid_uuid(chat_id):
            resolved_chat_id = auth_service.sanitize_identifier(chat_id, "chat_id")
        else:
            resolved_chat_id = str(uuid.uuid4())

        title_generated = False
        existing_chat = await chat_repo.get_chat_async(resolved_chat_id)

        if not existing_chat:
            # New chat - generate title
            title = await async_generate_chat_title(context)
            existing_chat = await chat_repo.create_chat_async(user_id=clean_user_id, name=title, chat_id=resolved_chat_id)
            title_generated = True
        else:
            if existing_chat.get("user_id") != clean_user_id:
                auth_service.verify_chat_ownership(resolved_chat_id, clean_user_id, action="post to")
            if existing_chat.get("name") in ("New Chat", "Yamaha Energy Assistant", None, ""):
                # Existing chat with placeholder or generic title - generate real contextual title
                title = await async_generate_chat_title(context)
                await asyncio.to_thread(chat_repo.set_chat_title, resolved_chat_id, title)
                existing_chat["name"] = title  # Update in returned dict
                title_generated = True

        # Mark if title was generated this call (for SSE notification)
        existing_chat["title_generated"] = title_generated

        return resolved_chat_id, existing_chat

    @staticmethod
    def load_langchain_history(chat_id: str, current_user_msg_id: Optional[int] = None, limit: int = 10) -> List[BaseMessage]:
        """
        Convert stored database messages to LangChain BaseMessage objects for multi-turn context.
        Fetches the MOST RECENT conversation turns to provide up-to-date context.
        Ensures strict user/assistant alternation and clean boundary conditions.
        """
        raw_msgs = chat_repo.get_recent_chat_messages(chat_id, limit=limit)
        convo_history: List[BaseMessage] = []
        for msg in raw_msgs:
            if current_user_msg_id and (msg.get("message_id") == current_user_msg_id or msg.get("id") == current_user_msg_id):
                continue
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                convo_history.append(HumanMessage(content=content))
            elif role == "assistant":
                # Clean synthetic annotations so the LLM doesn't imitate them in plain text
                clean_content = re.sub(r"\*?\[Telemetry data verified via tool: [^\]]+\]\*?", "", content).strip()
                convo_history.append(AIMessage(content=clean_content or content))

        # Enforce strict user/assistant alternation to prevent Bedrock ValidationExceptions
        # and eliminate duplicate or unresponded consecutive user turns
        alternated: List[BaseMessage] = []
        for msg in convo_history:
            if not alternated:
                if isinstance(msg, HumanMessage):
                    alternated.append(msg)
            else:
                last_is_human = isinstance(alternated[-1], HumanMessage)
                curr_is_human = isinstance(msg, HumanMessage)
                if last_is_human and curr_is_human:
                    alternated[-1] = msg  # Keep latest user query
                elif not last_is_human and not curr_is_human:
                    alternated[-1] = msg  # Keep latest assistant response
                else:
                    alternated.append(msg)
        convo_history = alternated

        # Bedrock Converse API requires that the conversation history begins with a user/human turn
        while convo_history and not isinstance(convo_history[0], HumanMessage):
            convo_history.pop(0)

        # Ensure conversation history ends with an assistant message so the new user message
        # is the only pending question (prevent double user questions)
        while convo_history and isinstance(convo_history[-1], HumanMessage):
            convo_history.pop(-1)

        return convo_history

    @staticmethod
    def save_user_turn(chat_id: str, prompt: str, model_name: str) -> int:
        user_msg_id = chat_repo.save_message(
            chat_id=chat_id,
            role="user",
            content=prompt,
            model=model_name
        )
        chat_repo.record_realtime_event(
            chat_id=chat_id,
            event_type="run_start",
            payload={"prompt": prompt, "user_msg_id": user_msg_id},
            message_id=user_msg_id
        )
        return user_msg_id

    @staticmethod
    def save_tool_turn(
        chat_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Any,
        tool_call_id: str,
        user_msg_id: int
    ):
        import json
        content_str = json.dumps(tool_output) if isinstance(tool_output, (dict, list)) else str(tool_output)

        # Build metadata with tool details - include input, output structure, and chart config
        tool_metadata = {
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "tool_input": tool_input,  # Save input parameters
        }

        # If tool_output contains chart_config, extract it for easy access
        if isinstance(tool_output, dict):
            if "chart_config" in tool_output:
                tool_metadata["chart_config"] = tool_output["chart_config"]
            elif "chart_type" in tool_output:
                # The output itself is a chart config
                tool_metadata["chart_config"] = tool_output
            # Also preserve data for re-rendering
            if "data" in tool_output:
                tool_metadata["chart_data"] = tool_output["data"]

        chat_repo.save_message(
            chat_id=chat_id,
            role="tool",
            content=content_str,
            metadata=tool_metadata
        )
        chat_repo.record_realtime_event(
            chat_id=chat_id,
            event_type="tool_call_result",
            payload={"toolName": tool_name, "output": tool_output, "toolCallId": tool_call_id},
            message_id=user_msg_id
        )

    @staticmethod
    def save_assistant_turn(
        chat_id: str,
        content: str,
        model_name: str,
        metadata: Dict[str, Any],
        user_msg_id: int
    ):
        chat_repo.save_message(
            chat_id=chat_id,
            role="assistant",
            content=content,
            model=model_name,
            metadata=metadata
        )
        chat_repo.record_realtime_event(
            chat_id=chat_id,
            event_type="run_complete",
            payload={"status": "completed", "tools": metadata.get("tools_used", [])},
            message_id=user_msg_id
        )

    @staticmethod
    def record_error(chat_id: str, error_message: str, user_msg_id: Optional[int] = None):
        chat_repo.record_realtime_event(
            chat_id=chat_id,
            event_type="error",
            payload={"error": error_message},
            message_id=user_msg_id
        )

    # -------------------------------------------------------------
    # Asynchronous Non-Blocking Persistence Methods
    # -------------------------------------------------------------
    @staticmethod
    async def save_user_turn_async(chat_id: str, prompt: str, model_name: str) -> int:
        import asyncio
        return await asyncio.to_thread(ChatService.save_user_turn, chat_id, prompt, model_name)

    @staticmethod
    async def save_tool_turn_async(
        chat_id: str,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_output: Any,
        tool_call_id: str,
        user_msg_id: int
    ):
        import asyncio
        await asyncio.to_thread(
            ChatService.save_tool_turn,
            chat_id, tool_name, tool_input, tool_output, tool_call_id, user_msg_id
        )

    @staticmethod
    async def save_assistant_turn_async(
        chat_id: str,
        content: str,
        model_name: str,
        metadata: Dict[str, Any],
        user_msg_id: int
    ):
        import asyncio
        await asyncio.to_thread(
            ChatService.save_assistant_turn,
            chat_id, content, model_name, metadata, user_msg_id
        )

    @staticmethod
    async def record_error_async(chat_id: str, error_message: str, user_msg_id: Optional[int] = None):
        import asyncio
        await asyncio.to_thread(
            ChatService.record_error,
            chat_id, error_message, user_msg_id
        )

chat_service = ChatService()
