"""
Chat Lifecycle & Persistence Service
Encapsulates thread creation, message persistence, event auditing,
and history conversion for LangGraph execution.
"""

import uuid
from typing import Any, Dict, List, Optional
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from src.db.chat_history import async_generate_chat_title, chat_repo, generate_chat_title
from src.services.authorization import auth_service

class ChatService:
    """Manages chat persistence, lifecycle, and message retrieval."""

    @staticmethod
    def list_user_chats(user_id: str, include_archived: bool = False, limit: int = 50) -> List[Dict[str, Any]]:
        clean_user_id = auth_service.sanitize_identifier(user_id, "user_id")
        return chat_repo.list_chats(user_id=clean_user_id, include_archived=include_archived, limit=limit)

    @staticmethod
    def create_chat(user_id: str, name: Optional[str] = None, chat_id: Optional[str] = None) -> Dict[str, Any]:
        clean_user_id = auth_service.sanitize_identifier(user_id, "user_id")
        clean_chat_id = auth_service.sanitize_identifier(chat_id, "chat_id") if chat_id else str(uuid.uuid4())
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
    def get_chat_messages(chat_id: str, user_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        auth_service.verify_chat_ownership(chat_id, user_id, action="view messages for")
        return chat_repo.get_chat_messages(chat_id, limit=limit)

    @staticmethod
    def get_chat_events(chat_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        auth_service.verify_chat_ownership(chat_id, user_id, action="view audit events for")
        return chat_repo.get_realtime_events(chat_id, limit=limit)

    @staticmethod
    def get_or_create_active_chat(chat_id: Optional[str], user_id: str, initial_prompt: str) -> Tuple_Chat:
        clean_user_id = auth_service.sanitize_identifier(user_id, "user_id")
        resolved_chat_id = auth_service.sanitize_identifier(chat_id, "chat_id") if chat_id else str(uuid.uuid4())

        existing_chat = chat_repo.get_chat(resolved_chat_id)
        if not existing_chat:
            title = generate_chat_title(initial_prompt)
            existing_chat = chat_repo.create_chat(user_id=clean_user_id, name=title, chat_id=resolved_chat_id)
        elif existing_chat.get("user_id") != clean_user_id:
            auth_service.verify_chat_ownership(resolved_chat_id, clean_user_id, action="post to")
        elif existing_chat.get("name") in ("New Chat", None, ""):
            title = generate_chat_title(initial_prompt)
            chat_repo.set_chat_title(resolved_chat_id, title)

        return resolved_chat_id, existing_chat

    @staticmethod
    async def get_or_create_active_chat_async(chat_id: Optional[str], user_id: str, context: Any) -> Tuple_Chat:
        import asyncio
        clean_user_id = auth_service.sanitize_identifier(user_id, "user_id")
        resolved_chat_id = auth_service.sanitize_identifier(chat_id, "chat_id") if chat_id else str(uuid.uuid4())

        existing_chat = await chat_repo.get_chat_async(resolved_chat_id)
        if not existing_chat:
            title = await async_generate_chat_title(context)
            existing_chat = await chat_repo.create_chat_async(user_id=clean_user_id, name=title, chat_id=resolved_chat_id)
        elif existing_chat.get("user_id") != clean_user_id:
            auth_service.verify_chat_ownership(resolved_chat_id, clean_user_id, action="post to")
        elif existing_chat.get("name") in ("New Chat", None, ""):
            title = await async_generate_chat_title(context)
            await asyncio.to_thread(chat_repo.set_chat_title, resolved_chat_id, title)

        return resolved_chat_id, existing_chat

    @staticmethod
    def load_langchain_history(chat_id: str, current_user_msg_id: Optional[int] = None, limit: int = 30) -> List[BaseMessage]:
        """
        Convert stored database messages to LangChain BaseMessage objects for multi-turn context.
        Only user and assistant conversation turns are included; orphan historical tool messages
        are excluded to ensure AWS Bedrock Converse API message alternation and schema invariants.
        """
        raw_msgs = chat_repo.get_chat_messages(chat_id, limit=limit)
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
                convo_history.append(AIMessage(content=content))

        # Bedrock Converse API requires that the conversation history begins with a user/human turn
        while convo_history and not isinstance(convo_history[0], HumanMessage):
            convo_history.pop(0)

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
        chat_repo.save_message(
            chat_id=chat_id,
            role="tool",
            content=content_str,
            metadata={"tool_name": tool_name, "tool_call_id": tool_call_id}
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

Tuple_Chat = Any
chat_service = ChatService()
