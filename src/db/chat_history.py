"""
Chat History Repository (PostgreSQL)
Manages chat sessions and message history using existing PostgreSQL tables.

Tables used:
- chats: Chat sessions with metadata
- chat_history: Individual messages within chats
"""

import datetime
import json
import uuid
from typing import Any, Dict, List, Optional

from src.db.postgres_client import pg_client


def generate_chat_title(context: Any) -> str:
    """
    Generate a clean, contextual 3-6 word chat title using LLM reasoning over context.
    """
    if not context:
        return "Yamaha Energy Query"

    text_context = ""
    if isinstance(context, str):
        text_context = context.strip()
    elif isinstance(context, list):
        parts = []
        for item in context[-3:]:
            if isinstance(item, str):
                parts.append(item)
            elif hasattr(item, "content"):
                parts.append(str(item.content))
            elif isinstance(item, dict):
                parts.append(str(item.get("content", "")))
        text_context = " | ".join(parts).strip()
    else:
        text_context = str(context).strip()

    if not text_context:
        return "Yamaha Energy Query"

    if text_context.lower() in ("hi", "hello", "hey", "hola", "greetings"):
        return "Yamaha Energy Assistant"

    try:
        from src.agent.model import get_llm
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = get_llm()
        sys_msg = SystemMessage(content=(
            "You are a concise title generator for an industrial energy assistant. "
            "Generate a professional, descriptive 3 to 6 word title summarizing the user inquiry. "
            "Do NOT use quotation marks, quotes, asterisks, trailing periods, or markdown formatting. "
            "Output ONLY the plain title string."
        ))
        resp = llm.invoke([sys_msg, HumanMessage(content=text_context[:500])])
        raw_title = str(resp.content).strip().strip('"\'*#`')
        if raw_title.lower().startswith("title:"):
            raw_title = raw_title[6:].strip()
        if raw_title:
            return raw_title[:45].strip()
    except Exception:
        pass

    words = [w for w in text_context.split() if len(w) > 1 and not w.startswith(("http", "{", "["))]
    if words:
        clean = " ".join(words[:5])
        return clean[:35].strip().title()
    return "Yamaha Energy Query"


async def async_generate_chat_title(context: Any) -> str:
    """Asynchronously generate a clean, contextual 3-6 word chat title using LLM."""
    import asyncio
    return await asyncio.to_thread(generate_chat_title, context)


def is_valid_uuid(val: Any) -> bool:
    """Validate whether val is a valid UUID string or UUID instance."""
    if not val:
        return False
    if isinstance(val, uuid.UUID):
        return True
    try:
        uuid.UUID(str(val).strip())
        return True
    except (ValueError, TypeError, AttributeError):
        return False


class ChatHistoryRepository:
    """Repository for managing chat sessions and messages in PostgreSQL."""

    def __init__(self):
        pass  # PostgreSQL tables already exist

    def create_chat(
        self,
        user_id: str = "default_user",
        consumer_id: int = 1,
        name: Optional[str] = None,
        chat_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Create a new chat session."""
        if chat_id and is_valid_uuid(chat_id):
            cid = str(uuid.UUID(str(chat_id).strip()))
        else:
            cid = str(uuid.uuid4())
        title = name or "New Chat"

        result = pg_client.execute_write("""
            INSERT INTO chats (chat_id, user_id, consumer_id, name)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE SET
                name = CASE WHEN EXCLUDED.name != 'New Chat' THEN EXCLUDED.name ELSE chats.name END,
                updated_at = NOW()
            RETURNING chat_id, user_id, consumer_id, name, chat_context,
                      context_updated_at, summarized_up_to_message_id, is_archived,
                      created_at, updated_at;
        """, (cid, user_id, consumer_id, title))

        return dict(result) if result else {"chat_id": cid, "user_id": user_id, "name": title}

    def list_chats(
        self,
        user_id: str = "default_user",
        consumer_id: Optional[int] = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List chat sessions for a user with pagination support."""
        if consumer_id:
            query = """
                SELECT chat_id, user_id, consumer_id, name, chat_context, context_updated_at,
                       summarized_up_to_message_id, is_archived, created_at, updated_at
                FROM chats
                WHERE consumer_id = %s
            """
            params = [consumer_id]
        else:
            query = """
                SELECT chat_id, user_id, consumer_id, name, chat_context, context_updated_at,
                       summarized_up_to_message_id, is_archived, created_at, updated_at
                FROM chats
                WHERE user_id = %s
            """
            params = [user_id]

        if not include_archived:
            query += " AND is_archived = FALSE"
        query += " ORDER BY updated_at DESC LIMIT %s OFFSET %s"
        params.append(limit)
        params.append(offset)

        rows = pg_client.execute_query(query, tuple(params))

        # Convert UUID and datetime objects to strings for JSON serialization
        for row in rows:
            if row.get("chat_id"):
                row["chat_id"] = str(row["chat_id"])
            if row.get("created_at"):
                row["created_at"] = row["created_at"].isoformat()
            if row.get("updated_at"):
                row["updated_at"] = row["updated_at"].isoformat()
            if row.get("context_updated_at"):
                row["context_updated_at"] = row["context_updated_at"].isoformat()

        return rows

    def get_chat(self, chat_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a chat session by ID."""
        if not is_valid_uuid(chat_id):
            return None

        if user_id:
            query = """
                SELECT chat_id, user_id, consumer_id, name, chat_context, context_updated_at,
                       summarized_up_to_message_id, is_archived, created_at, updated_at
                FROM chats
                WHERE chat_id = %s AND user_id = %s;
            """
            rows = pg_client.execute_query(query, (str(chat_id), user_id))
        else:
            query = """
                SELECT chat_id, user_id, consumer_id, name, chat_context, context_updated_at,
                       summarized_up_to_message_id, is_archived, created_at, updated_at
                FROM chats
                WHERE chat_id = %s;
            """
            rows = pg_client.execute_query(query, (str(chat_id),))

        if not rows:
            return None

        row = rows[0]
        # Convert for JSON serialization
        if row.get("chat_id"):
            row["chat_id"] = str(row["chat_id"])
        if row.get("created_at"):
            row["created_at"] = row["created_at"].isoformat()
        if row.get("updated_at"):
            row["updated_at"] = row["updated_at"].isoformat()
        if row.get("context_updated_at"):
            row["context_updated_at"] = row["context_updated_at"].isoformat()

        return row

    def set_chat_title(self, chat_id: str, name: str) -> bool:
        """Update the chat title."""
        if not is_valid_uuid(chat_id):
            return False
        result = pg_client.execute_write("""
            UPDATE chats
            SET name = %s, updated_at = NOW()
            WHERE chat_id = %s
            RETURNING chat_id;
        """, (name, str(chat_id)))
        return result is not None

    def archive_chat(self, chat_id: str, is_archived: bool = True) -> bool:
        """Archive or unarchive a chat."""
        if not is_valid_uuid(chat_id):
            return False
        result = pg_client.execute_write("""
            UPDATE chats
            SET is_archived = %s, updated_at = NOW()
            WHERE chat_id = %s
            RETURNING chat_id;
        """, (is_archived, str(chat_id)))
        return result is not None

    def delete_chat(self, chat_id: str) -> bool:
        """Delete a chat and all its messages (CASCADE)."""
        if not is_valid_uuid(chat_id):
            return False
        result = pg_client.execute_write("""
            DELETE FROM chats WHERE chat_id = %s RETURNING chat_id;
        """, (str(chat_id),))
        return result is not None

    def save_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        model: Optional[str] = None,
        token_count: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Save a message to chat history.

        The metadata field can contain chart_config for visualization messages,
        which allows re-rendering charts when loading chat history.
        """
        if not is_valid_uuid(chat_id):
            return 0
        meta_json = json.dumps(metadata or {})

        result = pg_client.execute_write("""
            INSERT INTO chat_history (chat_id, role, content, model, token_count, metadata)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            RETURNING message_id;
        """, (str(chat_id), role, content, model, token_count, meta_json))

        # Update chat's updated_at timestamp
        pg_client.execute_write("""
            UPDATE chats SET updated_at = NOW() WHERE chat_id = %s;
        """, (str(chat_id),))

        return result["message_id"] if result else 0

    def get_chat_messages(self, chat_id: str, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Get messages for a chat with pagination support.

        Returns messages with metadata including chart_config for re-rendering visualizations.
        Messages are returned in chronological order (oldest first).

        Args:
            chat_id: The chat UUID
            limit: Maximum number of messages to return (None = all)
            offset: Number of messages to skip from the beginning
        """
        if not is_valid_uuid(chat_id):
            return []

        query = """
            SELECT message_id, chat_id, role, content, created_at, model, token_count, metadata
            FROM chat_history
            WHERE chat_id = %s
            ORDER BY created_at ASC, message_id ASC
        """
        params = [str(chat_id)]

        if limit:
            query += " LIMIT %s"
            params.append(limit)

        if offset > 0:
            query += " OFFSET %s"
            params.append(offset)

        rows = pg_client.execute_query(query, tuple(params))

        results = []
        for row in rows:
            d = dict(row)
            # Convert for JSON serialization
            if d.get("chat_id"):
                d["chat_id"] = str(d["chat_id"])
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat()
            # metadata is already a dict from jsonb
            results.append(d)

        return results

    def get_recent_chat_messages(self, chat_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get the most recent messages for a chat, ordered chronologically (oldest to newest).
        Used to construct conversation context for the LLM.

        Args:
            chat_id: The chat UUID
            limit: Maximum number of recent messages to return
        """
        if not is_valid_uuid(chat_id):
            return []

        query = """
            SELECT * FROM (
                SELECT message_id, chat_id, role, content, created_at, model, token_count, metadata
                FROM chat_history
                WHERE chat_id = %s
                ORDER BY created_at DESC, message_id DESC
                LIMIT %s
            ) sub
            ORDER BY created_at ASC, message_id ASC;
        """
        rows = pg_client.execute_query(query, (str(chat_id), limit))

        results = []
        for row in rows:
            d = dict(row)
            if d.get("chat_id"):
                d["chat_id"] = str(d["chat_id"])
            if d.get("created_at"):
                d["created_at"] = d["created_at"].isoformat()
            results.append(d)

        return results

    async def get_recent_chat_messages_async(self, chat_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Async wrapper for get_recent_chat_messages."""
        return await asyncio.to_thread(self.get_recent_chat_messages, chat_id=chat_id, limit=limit)

    def get_chat_with_messages(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a chat session with all its messages.
        Useful for loading full chat history in frontend.
        """
        if not is_valid_uuid(chat_id):
            return None
        chat = self.get_chat(chat_id)
        if not chat:
            return None

        messages = self.get_chat_messages(chat_id)
        chat["messages"] = messages
        return chat

    # -------------------------------------------------------------
    # Async Methods (using asyncio.to_thread)
    # -------------------------------------------------------------
    async def create_chat_async(
        self,
        user_id: str = "default_user",
        consumer_id: int = 1,
        name: Optional[str] = None,
        chat_id: Optional[str] = None
    ) -> Dict[str, Any]:
        import asyncio
        return await asyncio.to_thread(
            self.create_chat, user_id=user_id, consumer_id=consumer_id, name=name, chat_id=chat_id
        )

    async def get_chat_async(self, chat_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        import asyncio
        return await asyncio.to_thread(self.get_chat, chat_id=chat_id, user_id=user_id)

    async def list_chats_async(
        self,
        user_id: str = "default_user",
        consumer_id: Optional[int] = None,
        include_archived: bool = False,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        import asyncio
        return await asyncio.to_thread(
            self.list_chats, user_id=user_id, consumer_id=consumer_id,
            include_archived=include_archived, limit=limit
        )

    async def save_message_async(
        self,
        chat_id: str,
        role: str,
        content: str,
        model: Optional[str] = None,
        token_count: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        import asyncio
        return await asyncio.to_thread(
            self.save_message,
            chat_id=chat_id,
            role=role,
            content=content,
            model=model,
            token_count=token_count,
            metadata=metadata
        )

    async def get_chat_messages_async(self, chat_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        import asyncio
        return await asyncio.to_thread(self.get_chat_messages, chat_id=chat_id, limit=limit)

    async def get_chat_with_messages_async(self, chat_id: str) -> Optional[Dict[str, Any]]:
        import asyncio
        return await asyncio.to_thread(self.get_chat_with_messages, chat_id=chat_id)

    # -------------------------------------------------------------
    # Event Tracking (stub methods - events are non-essential audit logs)
    # -------------------------------------------------------------
    def record_realtime_event(
        self,
        chat_id: str,
        event_type: str,
        payload: Optional[Dict[str, Any]] = None,
        message_id: Optional[int] = None
    ) -> None:
        """
        Record a real-time event for audit/debugging purposes.
        Currently a no-op - events can be stored in a separate table if needed.
        """
        # TODO: Create a chat_events table if audit logging is required
        pass

    def get_realtime_events(
        self,
        chat_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get real-time events for a chat.
        Currently returns empty list - implement if audit logging is needed.
        """
        return []

    def get_live_device_telemetry(self, device: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get live device telemetry.
        This should query ClickHouse, not PostgreSQL.
        """
        # This is a stub - actual telemetry comes from ClickHouse
        return []


# Singleton instance
chat_repo = ChatHistoryRepository()
