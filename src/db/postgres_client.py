"""
PostgreSQL Client for Chat Management
Uses psycopg2 for synchronous operations and asyncpg for async operations.
"""

import json
import uuid
import datetime
from typing import Any, Dict, List, Optional
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from src.core.config import settings


class PostgresClient:
    """PostgreSQL client for chat history and session management."""

    def __init__(self):
        self.config = {
            "host": settings.POSTGRES_HOST,
            "port": settings.POSTGRES_PORT,
            "dbname": settings.POSTGRES_DATABASE,
            "user": settings.POSTGRES_USER,
            "password": settings.POSTGRES_PASSWORD,
            "connect_timeout": 5,
        }

    @contextmanager
    def get_connection(self):
        """Get a database connection with automatic cleanup."""
        conn = psycopg2.connect(**self.config, cursor_factory=RealDictCursor)
        try:
            yield conn
        finally:
            conn.close()

    def execute_query(self, query: str, params: tuple = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return results."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]

    def execute_write(self, query: str, params: tuple = None) -> Optional[Any]:
        """Execute an INSERT/UPDATE/DELETE and return lastrowid or affected rows."""
        with self.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                conn.commit()
                try:
                    return cursor.fetchone()
                except psycopg2.ProgrammingError:
                    return {"affected_rows": cursor.rowcount}

    def test_connection(self) -> bool:
        """Test if the PostgreSQL connection is working."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1 AS ok;")
                    return True
        except Exception as e:
            print(f"PostgreSQL connection test failed: {e}")
            return False


# Singleton instance
pg_client = PostgresClient()
