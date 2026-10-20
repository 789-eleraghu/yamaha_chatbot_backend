"""
SQLite Client Implementation for Local Mock Database
"""

import sqlite3
from typing import Any, Dict, List, Optional, Tuple
from src.core.config import settings
from src.db.base import DatabaseClient

class SQLiteClient(DatabaseClient):
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.SQLITE_DB_PATH

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def execute_query(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_tag_delta(self, tag_id: str, start_ts: str, end_ts: str) -> Optional[float]:
        """Compute max(value) - min(value) for tag in [start_ts, end_ts)."""
        query = """
            SELECT MAX(value) - MIN(value) AS delta
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp < ? AND value > 0;
        """
        rows = self.execute_query(query, (tag_id, start_ts, end_ts))
        if rows and rows[0]["delta"] is not None:
            return round(float(rows[0]["delta"]), 2)
        return None

    def get_daily_rollup_energy(self, tag_id: str, date_str: str) -> Optional[float]:
        """Fetch energy from tag_daily_energy_rollup for single day."""
        query = """
            SELECT energy
            FROM tag_daily_energy_rollup
            WHERE tag_id = ? AND date = ?;
        """
        rows = self.execute_query(query, (tag_id, date_str))
        if rows and rows[0]["energy"] is not None:
            return round(float(rows[0]["energy"]), 2)
        return None

    def get_nearest_reading_before(self, tag_id: str, ts_str: str) -> Optional[float]:
        """Fetch nearest counter reading at or before ts_str."""
        query = """
            SELECT value
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp <= ? AND value > 0
            ORDER BY reading_timestamp DESC
            LIMIT 1;
        """
        rows = self.execute_query(query, (tag_id, ts_str))
        if rows and rows[0]["value"] is not None:
            return float(rows[0]["value"])
        return None

# Singleton instance
db_client = SQLiteClient()
