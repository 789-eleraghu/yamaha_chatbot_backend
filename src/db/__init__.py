"""
Database Package - ClickHouse Only

Exports:
- db_client: ClickHouse database client singleton
- chat_repo: Chat history repository singleton
"""

from src.db.client import db_client, ClickHouseClient
from src.db.chat_history import chat_repo, ChatHistoryRepository

__all__ = [
    "db_client",
    "ClickHouseClient",
    "chat_repo",
    "ChatHistoryRepository",
]
