"""
Chat History Database Management & Repository
Implements the schema defined in chat_history_schema.md:
- chats
- chat_history
Plus real-time extensions:
- realtime_chat_events (one more table for real-time streaming runs, events & tool execution)
- realtime_device_telemetry (for Component 10 real-time monitoring)
"""

import datetime
import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional
from src.core.config import settings

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_chat_tables():
    """Initializes tables adhering to chat_history_schema.md + real-time tables."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # Table 1: chats
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                chat_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT,
                chat_context TEXT NOT NULL DEFAULT '',
                context_updated_at TEXT,
                summarized_up_to_message_id INTEGER,
                is_archived INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
        """)

        # Table 2: chat_history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_history (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                model TEXT,
                token_count INTEGER,
                metadata TEXT NOT NULL DEFAULT '{}'
            );
        """)

        # Table 3: realtime_chat_events (Real-time events table)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS realtime_chat_events (
                event_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL REFERENCES chats(chat_id) ON DELETE CASCADE,
                message_id INTEGER REFERENCES chat_history(message_id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
        """)

        # Table 4: realtime_device_telemetry (Component 10 live device registry)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS realtime_device_telemetry (
                device_id TEXT PRIMARY KEY,
                device_name TEXT NOT NULL,
                category TEXT NOT NULL,
                prefix TEXT NOT NULL,
                voltage_avg REAL NOT NULL,
                current_avg REAL NOT NULL,
                power_factor REAL NOT NULL,
                real_power_kw REAL NOT NULL,
                apparent_power_kva REAL NOT NULL,
                reactive_power_kvar REAL NOT NULL,
                frequency_hz REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'NORMAL',
                last_updated_ist TEXT NOT NULL
            );
        """)

        # Indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chat_history_chat_time
            ON chat_history (chat_id, created_at, message_id);
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_chats_user_updated
            ON chats (user_id, updated_at DESC);
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_realtime_events_chat
            ON realtime_chat_events (chat_id, created_at);
        """)

        conn.commit()

        # Seed initial real-time telemetry if empty
        cursor.execute("SELECT COUNT(*) AS cnt FROM realtime_device_telemetry;")
        row = cursor.fetchone()
        if row and row["cnt"] == 0:
            seed_initial_telemetry(cursor)
            conn.commit()

    finally:
        conn.close()

def seed_initial_telemetry(cursor: sqlite3.Cursor):
    """Seed Component 10 representative live devices with realistic nominal values."""
    now_ist = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    initial_devices = [
        ("HT_Room", "South Utilities 1000kVA Transformer", "Transformer", "HT_Room.South_Utilities_1000kVA_Transformer/", 239.4, 185.2, 0.96, 128.5, 133.8, 37.4, 50.02, "NORMAL"),
        ("North_Utilities", "North Utilities 2000kVA Transformer", "Transformer", "Incomer.North_Utilities_2000KVA_Transformer/", 241.1, 210.6, 0.98, 149.2, 152.2, 30.3, 50.01, "NORMAL"),
        ("Molding", "Molding PP-PK2-20 (1600T)", "Molding", "Molding.PP-PK2-20_1600T/", 238.8, 92.4, 0.94, 62.1, 66.1, 22.8, 49.99, "NORMAL"),
        ("Compressor", "Compressor 1", "Compressor", "Compressor.Compressor_1/", 240.2, 78.1, 0.95, 53.4, 56.2, 17.5, 50.00, "NORMAL"),
        ("Airconditioning", "Central Chiller", "Airconditioning", "Airconditioning.Chiller/", 239.9, 114.5, 0.93, 76.8, 82.6, 30.5, 50.03, "NORMAL"),
        ("Lighting", "SDB-9 Office Lighting", "Lighting", "Lighting.SDB-9_L_Office/", 240.5, 16.2, 0.99, 11.7, 11.8, 1.5, 50.01, "NORMAL"),
        ("Solar", "Solar Incomer 100kW", "Solar", "Incomer.Incomer_Solar_100kW/", 242.0, 52.0, 1.00, 37.7, 37.7, 0.0, 50.02, "NORMAL"),
        ("DG", "DG Incomer 300kVA", "DG", "Incomer.DG_Incomer_300kVA/", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "STANDBY"),
        ("Dust_Collector", "Main Dust Collector", "Dust_Collector", "Dust_Collector.Dust_Collector/", 239.0, 34.6, 0.91, 22.7, 24.9, 10.2, 49.98, "NORMAL"),
        ("Paintshop", "PP-G4-118 AG AHU AG Paint", "Paintshop", "Paintshop.PP-G4-118_AG_AHU_AG_Paint/", 240.1, 41.3, 0.92, 27.4, 29.8, 11.7, 50.01, "NORMAL"),
    ]

    for d in initial_devices:
        cursor.execute("""
            INSERT OR REPLACE INTO realtime_device_telemetry (
                device_id, device_name, category, prefix,
                voltage_avg, current_avg, power_factor, real_power_kw,
                apparent_power_kva, reactive_power_kvar, frequency_hz,
                status, last_updated_ist
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (*d, now_ist))

def generate_chat_title(context: Any) -> str:
    """
    Generate a clean, contextual 3-6 word chat title using LLM reasoning over context.
    Eliminates rigid keyword-based if/else statements and adapts dynamically.
    """
    if not context:
        return "Yamaha Energy Query"

    # Normalize context into a single string
    text_context = ""
    if isinstance(context, str):
        text_context = context.strip()
    elif isinstance(context, list):
        parts = []
        for item in context[-3:]:  # Focus on latest conversational turns
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

    # Fast bypass for single-word greetings
    if text_context.lower() in ("hi", "hello", "hey", "hola", "greetings"):
        return "Yamaha Energy Assistant"

    # Invoke configured LLM to generate concise contextual title
    try:
        from src.agent.model import get_llm
        from langchain_core.messages import SystemMessage, HumanMessage

        llm = get_llm()
        sys_msg = SystemMessage(content=(
            "You are a concise title generator for an industrial energy assistant. "
            "Generate a professional, descriptive 3 to 6 word title summarizing the user inquiry or conversation context. "
            "Use standard plant terminology (e.g., Shift, Peak Demand, Tariff, DG Generator). "
            "Do NOT use quotation marks, quotes, asterisks, trailing periods, or markdown formatting. "
            "Output ONLY the plain title string."
        ))
        resp = llm.invoke([sys_msg, HumanMessage(content=text_context[:500])])
        raw_title = str(resp.content).strip().strip('"\'*#`')
        if raw_title.lower().startswith("title:"):
            raw_title = raw_title[6:].strip()
        if raw_title:
            return raw_title[:45].strip()
    except Exception as e:
        # Fallback to word-based extraction if model is unavailable
        pass

    # Fallback to sanitized first few words
    words = [w for w in text_context.split() if len(w) > 1 and not w.startswith(("http", "{", "["))]
    if words:
        clean = " ".join(words[:5])
        return clean[:35].strip().title()
    return "Yamaha Energy Query"

async def async_generate_chat_title(context: Any) -> str:
    """Asynchronously generate a clean, contextual 3-6 word chat title using LLM."""
    import asyncio
    return await asyncio.to_thread(generate_chat_title, context)

class ChatHistoryRepository:
    def __init__(self):
        init_chat_tables()

    def create_chat(
        self,
        user_id: str = "default_user",
        name: Optional[str] = None,
        chat_id: Optional[str] = None
    ) -> Dict[str, Any]:
        cid = chat_id or str(uuid.uuid4())
        title = name or "New Chat"
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = get_connection()
        try:
            conn.execute("""
                INSERT INTO chats (chat_id, user_id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    name = CASE WHEN excluded.name != 'New Chat' THEN excluded.name ELSE chats.name END,
                    updated_at = excluded.updated_at;
            """, (cid, user_id, title, now_ts, now_ts))
            conn.commit()

            cursor = conn.cursor()
            cursor.execute("SELECT * FROM chats WHERE chat_id = ?;", (cid,))
            row = cursor.fetchone()
            return dict(row)
        finally:
            conn.close()

    def list_chats(
        self,
        user_id: str = "default_user",
        include_archived: bool = False,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            query = """
                SELECT chat_id, user_id, name, chat_context, context_updated_at,
                       summarized_up_to_message_id, is_archived, created_at, updated_at
                FROM chats
                WHERE user_id = ?
            """
            params: List[Any] = [user_id]
            if not include_archived:
                query += " AND is_archived = 0"
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)

            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_chat(self, chat_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("SELECT * FROM chats WHERE chat_id = ? AND user_id = ?;", (chat_id, user_id))
            else:
                cursor.execute("SELECT * FROM chats WHERE chat_id = ?;", (chat_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def set_chat_title(self, chat_id: str, name: str) -> bool:
        conn = get_connection()
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE chats
                SET name = ?, updated_at = ?
                WHERE chat_id = ?;
            """, (name, now_ts, chat_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def archive_chat(self, chat_id: str, is_archived: bool = True) -> bool:
        conn = get_connection()
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE chats
                SET is_archived = ?, updated_at = ?
                WHERE chat_id = ?;
            """, (1 if is_archived else 0, now_ts, chat_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_chat(self, chat_id: str) -> bool:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM chats WHERE chat_id = ?;", (chat_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def save_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        model: Optional[str] = None,
        token_count: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        conn = get_connection()
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta_json = json.dumps(metadata or {})
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_history (chat_id, role, content, created_at, model, token_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (chat_id, role, content, now_ts, model, token_count, meta_json))
            msg_id = cursor.lastrowid

            # Bump chat's updated_at in same transaction
            cursor.execute("""
                UPDATE chats SET updated_at = ? WHERE chat_id = ?;
            """, (now_ts, chat_id))

            conn.commit()
            return msg_id
        finally:
            conn.close()

    def get_chat_messages(self, chat_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            if limit:
                query = """
                    SELECT message_id, chat_id, role, content, created_at, model, token_count, metadata
                    FROM (
                        SELECT message_id, chat_id, role, content, created_at, model, token_count, metadata
                        FROM chat_history
                        WHERE chat_id = ?
                        ORDER BY created_at DESC, message_id DESC
                        LIMIT ?
                    ) sub
                    ORDER BY created_at ASC, message_id ASC
                """
                params: List[Any] = [chat_id, limit]
            else:
                query = """
                    SELECT message_id, chat_id, role, content, created_at, model, token_count, metadata
                    FROM chat_history
                    WHERE chat_id = ?
                    ORDER BY created_at ASC, message_id ASC
                """
                params: List[Any] = [chat_id]

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if isinstance(d.get("metadata"), str):
                    try:
                        d["metadata"] = json.loads(d["metadata"])
                    except Exception:
                        d["metadata"] = {}
                results.append(d)
            return results
        finally:
            conn.close()

    def record_realtime_event(
        self,
        chat_id: str,
        event_type: str,
        payload: Dict[str, Any],
        message_id: Optional[int] = None
    ) -> str:
        eid = str(uuid.uuid4())
        now_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload_json = json.dumps(payload)

        conn = get_connection()
        try:
            conn.execute("""
                INSERT INTO realtime_chat_events (event_id, chat_id, message_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (eid, chat_id, message_id, event_type, payload_json, now_ts))
            conn.commit()
            return eid
        finally:
            conn.close()

    def get_realtime_events(self, chat_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT event_id, chat_id, message_id, event_type, payload, created_at
                FROM realtime_chat_events
                WHERE chat_id = ?
                ORDER BY created_at ASC
                LIMIT ?;
            """, (chat_id, limit))
            rows = cursor.fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if isinstance(d.get("payload"), str):
                    try:
                        d["payload"] = json.loads(d["payload"])
                    except Exception:
                        d["payload"] = {}
                results.append(d)
            return results
        finally:
            conn.close()

    def get_live_device_telemetry(self, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            if device_id:
                cursor.execute("SELECT * FROM realtime_device_telemetry WHERE device_id = ? OR device_name LIKE ?;", (device_id, f"%{device_id}%"))
            else:
                cursor.execute("SELECT * FROM realtime_device_telemetry ORDER BY device_name ASC;")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # -------------------------------------------------------------
    # Non-Blocking Asynchronous Database Methods (asyncio.to_thread)
    # -------------------------------------------------------------
    async def create_chat_async(self, user_id: str = "default_user", name: Optional[str] = None, chat_id: Optional[str] = None) -> Dict[str, Any]:
        import asyncio
        return await asyncio.to_thread(self.create_chat, user_id=user_id, name=name, chat_id=chat_id)

    async def get_chat_async(self, chat_id: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        import asyncio
        return await asyncio.to_thread(self.get_chat, chat_id=chat_id, user_id=user_id)

    async def list_chats_async(self, user_id: str = "default_user", include_archived: bool = False, limit: int = 50) -> List[Dict[str, Any]]:
        import asyncio
        return await asyncio.to_thread(self.list_chats, user_id=user_id, include_archived=include_archived, limit=limit)

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

    async def record_realtime_event_async(
        self,
        chat_id: str,
        event_type: str,
        payload: Dict[str, Any],
        message_id: Optional[int] = None
    ) -> str:
        import asyncio
        return await asyncio.to_thread(
            self.record_realtime_event,
            chat_id=chat_id,
            event_type=event_type,
            payload=payload,
            message_id=message_id
        )

    async def get_realtime_events_async(self, chat_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        import asyncio
        return await asyncio.to_thread(self.get_realtime_events, chat_id=chat_id, limit=limit)

    async def get_live_device_telemetry_async(self, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        import asyncio
        return await asyncio.to_thread(self.get_live_device_telemetry, device_id=device_id)

chat_repo = ChatHistoryRepository()
