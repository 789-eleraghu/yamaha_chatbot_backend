"""
Database Client - ClickHouse Only
Provides unified database access for production ClickHouse database.
All telemetry queries use native ClickHouse syntax.
"""

import threading
from typing import Any, Dict, List, Optional, Tuple, Union

import clickhouse_connect
from clickhouse_connect.driver import Client

from src.core.config import settings
from src.db.base import DatabaseClient


class ClickHouseClient(DatabaseClient):
    """
    ClickHouse database client using HTTP interface.
    Thread-safe implementation with thread-local client connections and stateless requests.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None
    ):
        self.host = host or settings.CLICKHOUSE_HOST
        self.port = port or settings.CLICKHOUSE_PORT
        self.database = database or settings.CLICKHOUSE_DATABASE
        self.user = user or settings.CLICKHOUSE_USER
        self.password = password or settings.CLICKHOUSE_PASSWORD
        self._local = threading.local()

    def _get_client(self) -> Client:
        """Get or create thread-local ClickHouse client connection without session locking."""
        client = getattr(self._local, "client", None)
        if client is None:
            client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.user,
                password=self.password,
                connect_timeout=10,
                send_receive_timeout=60,
                autogenerate_session_id=False
            )
            self._local.client = client
        return client

    def execute_query(
        self,
        query: str,
        params: Optional[Union[Dict[str, Any], Tuple[Any, ...], List[Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a SELECT query and return list of row dictionaries.

        Args:
            query: ClickHouse query with named parameters like {param_name:Type}
            params: Dict of parameter values (e.g., {"date": "2026-10-20"})

        Returns:
            List of dictionaries, one per row
        """
        client = self._get_client()

        if isinstance(params, dict) and params:
            result = client.query(query, parameters=params)
        elif isinstance(params, (tuple, list)) and params:
            # Legacy support: convert positional params to dict
            param_dict = {f"p{i}": v for i, v in enumerate(params)}
            result = client.query(query, parameters=param_dict)
        else:
            result = client.query(query)

        # Convert to list of dicts
        columns = result.column_names
        rows = []
        for row in result.result_rows:
            rows.append(dict(zip(columns, row)))

        return rows

    def execute_native(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a native ClickHouse query with named parameters.
        Preferred method for new code.

        Args:
            query: ClickHouse query with {name:Type} placeholders
            params: Dictionary of parameter values

        Returns:
            List of dictionaries, one per row
        """
        client = self._get_client()
        result = client.query(query, parameters=params or {})

        columns = result.column_names
        rows = []
        for row in result.result_rows:
            rows.append(dict(zip(columns, row)))

        return rows

    def get_tag_delta(self, tag_id: str, start_ts: str, end_ts: str) -> Optional[float]:
        """
        Compute max(value) - min(value) for tag in [start_ts, end_ts).
        Note: ClickHouse stores 'value' as String, so we cast to Float64.
        """
        query = """
            SELECT max(toFloat64OrNull(value)) - min(toFloat64OrNull(value)) AS delta
            FROM opcda_readings
            WHERE tag_id = {tag_id:String}
              AND reading_timestamp >= parseDateTimeBestEffort({start_ts:String})
              AND reading_timestamp < parseDateTimeBestEffort({end_ts:String})
              AND toFloat64OrNull(value) > 0
        """
        result = self.execute_native(query, {
            "tag_id": tag_id,
            "start_ts": start_ts,
            "end_ts": end_ts
        })

        if result and result[0].get("delta") is not None:
            return round(float(result[0]["delta"]), 2)
        return None

    def get_daily_rollup_energy(self, tag_id: str, date_str: str) -> Optional[float]:
        """
        Fetch energy from tag_daily_energy_rollup for single day.
        Note: ClickHouse uses 'day' column and AggregateFunction types.
        Energy = maxMerge(max_value) - minMerge(min_value)
        """
        query = """
            SELECT maxMerge(max_value) - minMerge(min_value) AS energy
            FROM tag_daily_energy_rollup
            WHERE tag_id = {tag_id:String} AND day = toDate({date_str:String})
            GROUP BY tag_id
        """
        result = self.execute_native(query, {
            "tag_id": tag_id,
            "date_str": date_str
        })

        if result and result[0].get("energy") is not None:
            return round(float(result[0]["energy"]), 2)
        return None

    def get_nearest_reading_before(self, tag_id: str, ts_str: str) -> Optional[float]:
        """Fetch nearest counter reading at or before ts_str."""
        query = """
            SELECT toFloat64OrNull(value) AS val
            FROM opcda_readings
            WHERE tag_id = {tag_id:String}
              AND reading_timestamp <= parseDateTimeBestEffort({ts_str:String})
              AND toFloat64OrNull(value) > 0
            ORDER BY reading_timestamp DESC
            LIMIT 1
        """
        result = self.execute_native(query, {
            "tag_id": tag_id,
            "ts_str": ts_str
        })

        if result and result[0].get("val") is not None:
            return float(result[0]["val"])
        return None

    def close(self):
        """Close the client connection for current thread."""
        client = getattr(self._local, "client", None)
        if client:
            try:
                client.close()
            except Exception:
                pass
            self._local.client = None

    def test_connection(self) -> bool:
        """Test if the connection is working."""
        try:
            client = self._get_client()
            result = client.query("SELECT 1")
            return True
        except Exception as e:
            print(f"ClickHouse connection test failed: {e}")
            return False

    def get_table_schema(self, table_name: str) -> List[Dict[str, Any]]:
        """Get schema information for a table."""
        query = f"DESCRIBE TABLE {table_name}"
        return self.execute_query(query)

    def list_tables(self) -> List[str]:
        """List all tables in the database."""
        query = "SHOW TABLES"
        rows = self.execute_query(query)
        return [r.get("name", r.get("table", list(r.values())[0])) for r in rows]


# Singleton instance - always uses ClickHouse
db_client = ClickHouseClient()
