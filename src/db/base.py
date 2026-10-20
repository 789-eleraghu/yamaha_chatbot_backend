"""
Base Database Interface
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

class DatabaseClient(ABC):
    @abstractmethod
    def execute_query(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return list of row dictionaries."""
        pass

    @abstractmethod
    def get_tag_delta(self, tag_id: str, start_ts: str, end_ts: str) -> Optional[float]:
        """Compute max(value) - min(value) for tag in [start_ts, end_ts)."""
        pass

    @abstractmethod
    def get_daily_rollup_energy(self, tag_id: str, date_str: str) -> Optional[float]:
        """Fetch energy or max - min from tag_daily_energy_rollup."""
        pass

    @abstractmethod
    def get_nearest_reading_before(self, tag_id: str, ts_str: str) -> Optional[float]:
        """Fetch nearest counter reading at or before ts_str."""
        pass
