"""
Tool Result Cache
LRU cache with TTL for expensive tool executions.
Reduces redundant database queries and API calls.
"""

import hashlib
import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, Optional, Tuple

# Cache configuration
DEFAULT_TTL_SECONDS = 300  # 5 minutes
MAX_CACHE_SIZE = 500
CACHEABLE_TOOLS = {
    # Tool name -> TTL in seconds
    "get_energy_consumption": 300,
    "get_shift_wise_consumption": 300,
    "get_cost_and_tariff": 300,
    "get_peak_demand_analysis": 300,
    "get_breakdown_summary": 300,
    "get_dg_generator_status": 600,  # DG data changes less frequently
    "get_power_quality_and_utilities": 300,
    "diagnose_high_consumption": 600,
    "diagnose_spikes_and_anomalies": 600,
    "explain_hourly_anomaly": 600,
    "search_ems_knowledge_base": 3600,  # KB rarely changes
    # Chart tools - cache the data, not the config
    "aggregate_energy_telemetry": 300,
    "create_breakdown_chart": 300,
    "create_time_series_chart": 300,
    "create_shift_comparison_chart": 300,
    "create_demand_utilization_gauge": 300,
    "create_correlation_scatter_plot": 300,
    "create_load_heatmap": 600,
}

# Tools that should NEVER be cached
NON_CACHEABLE_TOOLS = {
    "get_realtime_device_telemetry",  # Real-time data
    "execute_custom_sql",  # Arbitrary queries
}


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    value: Any
    created_at: float
    ttl: float
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl


class ToolResultCache:
    """
    Thread-safe LRU cache with TTL for tool results.
    Keyed by (tool_name, args_hash).
    """

    def __init__(self, max_size: int = MAX_CACHE_SIZE):
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._lock = Lock()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}

    @staticmethod
    def _make_key(tool_name: str, args: Dict[str, Any]) -> str:
        """Generate cache key from tool name and args."""
        # Normalize args (sort keys, handle None)
        normalized = json.dumps(args, sort_keys=True, default=str)
        args_hash = hashlib.md5(normalized.encode()).hexdigest()[:12]
        return f"{tool_name}:{args_hash}"

    def get(self, tool_name: str, args: Dict[str, Any]) -> Tuple[Optional[Any], bool]:
        """
        Get cached result if exists and not expired.
        Returns (result, cache_hit).
        """
        if tool_name in NON_CACHEABLE_TOOLS:
            return None, False

        if tool_name not in CACHEABLE_TOOLS:
            return None, False

        key = self._make_key(tool_name, args)

        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._stats["misses"] += 1
                return None, False

            if entry.is_expired:
                # Remove expired entry
                del self._cache[key]
                self._stats["misses"] += 1
                return None, False

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.hit_count += 1
            self._stats["hits"] += 1

            return entry.value, True

    def set(self, tool_name: str, args: Dict[str, Any], result: Any) -> None:
        """Store result in cache."""
        if tool_name in NON_CACHEABLE_TOOLS:
            return

        if tool_name not in CACHEABLE_TOOLS:
            return

        # Don't cache errors
        if isinstance(result, dict) and "error" in result:
            return

        key = self._make_key(tool_name, args)
        ttl = CACHEABLE_TOOLS.get(tool_name, DEFAULT_TTL_SECONDS)

        with self._lock:
            # Evict oldest if at capacity
            while len(self._cache) >= self._max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                self._stats["evictions"] += 1

            self._cache[key] = CacheEntry(
                value=result,
                created_at=time.time(),
                ttl=ttl
            )

    def invalidate(self, tool_name: Optional[str] = None, args: Optional[Dict[str, Any]] = None) -> int:
        """
        Invalidate cache entries.
        - No args: clear all
        - tool_name only: clear all entries for that tool
        - Both: clear specific entry
        Returns count of invalidated entries.
        """
        with self._lock:
            if tool_name is None:
                count = len(self._cache)
                self._cache.clear()
                return count

            if args is not None:
                key = self._make_key(tool_name, args)
                if key in self._cache:
                    del self._cache[key]
                    return 1
                return 0

            # Clear all entries for tool
            keys_to_remove = [k for k in self._cache if k.startswith(f"{tool_name}:")]
            for key in keys_to_remove:
                del self._cache[key]
            return len(keys_to_remove)

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)

    @property
    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        with self._lock:
            total_requests = self._stats["hits"] + self._stats["misses"]
            hit_rate = self._stats["hits"] / total_requests if total_requests > 0 else 0
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "evictions": self._stats["evictions"],
                "hit_rate": round(hit_rate, 3),
            }


# Global singleton
tool_cache = ToolResultCache()


def cached_tool_execute(tool_fn, args: Dict[str, Any]) -> Any:
    """
    Execute tool with caching.
    Wraps tool.invoke() with cache check.
    """
    tool_name = tool_fn.name

    # Check cache first
    cached_result, cache_hit = tool_cache.get(tool_name, args)
    if cache_hit:
        return cached_result

    # Execute tool
    result = tool_fn.invoke(args)

    # Cache result
    tool_cache.set(tool_name, args, result)

    return result
