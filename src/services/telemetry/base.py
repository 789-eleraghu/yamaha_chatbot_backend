"""
Base Telemetry Service & Industrial Calculation Engine
Single point of edit for all industrial EMS telemetry calculations.
Encapsulates cumulative counter deltas, instantaneous metrics, hourly profiles,
shift boundaries (Section 9 00:40 Rule), and capability gating.
"""

import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from src.core.config import settings
from src.core.constants import TIMEZONE
from src.core.normalizers import normalize_date_str
from src.db.client import db_client

IST = ZoneInfo(TIMEZONE)


class TelemetryCapability(Enum):
    """Supported telemetry capabilities across tiers."""
    CUMULATIVE_ENERGY = "cumulative_energy"
    INSTANTANEOUS_POWER = "instantaneous_power"
    HOURLY_PROFILE = "hourly_profile"
    SHIFT_BREAKDOWN = "shift_breakdown"
    POWER_QUALITY = "power_quality"
    THRESHOLD_MONITORING = "threshold_monitoring"
    RUN_DETECTION = "run_detection"
    UTILITIES_STEAM = "utilities_steam"


class UnsupportedCapabilityError(Exception):
    """Raised when an operation is requested that is not supported by this telemetry tier."""
    def __init__(self, tier_name: str, capability: TelemetryCapability, reason: Optional[str] = None):
        msg = f"Telemetry tier '{tier_name}' does not support '{capability.value}'."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(msg)
        self.tier_name = tier_name
        self.capability = capability
        self.reason = reason


class BaseTelemetryService:
    """
    Authoritative Base Telemetry Class.
    All industrial physics and calculation formulas reside here:
    1. Cumulative Parameter: Energy Delta = max(counter) - min(counter)
    2. Instantaneous Parameter: Statistical avg, min, max, peak
    3. Shift Breakdown: Section 9 (Shift A, Shift B with 00:40 rollover, Shift C)
    4. Hourly Profiles: 24-hour hour-by-hour time series
    """

    def __init__(
        self,
        tier_name: str,
        supported_capabilities: Set[TelemetryCapability]
    ):
        self.tier_name = tier_name
        self.supported_capabilities = supported_capabilities

    def check_capability(self, capability: TelemetryCapability, reason: Optional[str] = None):
        """Enforce capability gating. If tier does not support, raises error."""
        if capability not in self.supported_capabilities:
            raise UnsupportedCapabilityError(self.tier_name, capability, reason)

    def normalize_date(self, date_input: str) -> str:
        """Single point date normalizer supporting 'today', 'yesterday', or 'YYYY-MM-DD'."""
        return normalize_date_str(date_input)

    def get_time_window(self, date_str: str) -> Tuple[str, str]:
        """Returns standard IST [00:00:00, 23:59:59] boundaries for date."""
        clean_date = self.normalize_date(date_str)
        return f"{clean_date} 00:00:00", f"{clean_date} 23:59:59"

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Single point database execution against ClickHouse / SQLite."""
        return db_client.execute_query(query, params)

    # --------------------------------------------------------------------------
    # 1. Cumulative Calculation: max(counter) - min(counter)
    # --------------------------------------------------------------------------
    def calculate_cumulative(
        self,
        tag_ids: List[str],
        start_ts: str,
        end_ts: str,
        round_digits: int = 1
    ) -> float:
        """
        Calculate cumulative counter delta: sum(max(value) - min(value)) across given tags.
        Enforces Section 1: Never sum instantaneous readings.
        """
        self.check_capability(TelemetryCapability.CUMULATIVE_ENERGY)
        if not tag_ids:
            return 0.0

        total_delta = 0.0
        # Use single batch query for ClickHouse efficiency
        tag_list_str = ", ".join(f"'{t}'" for t in tag_ids)
        query = f"""
            SELECT
                tag_id,
                MAX(toFloat64OrNull(value)) AS max_val,
                MIN(toFloat64OrNull(value)) AS min_val
            FROM opcda_readings
            WHERE tag_id IN ({tag_list_str})
              AND reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
              AND reading_timestamp <= parseDateTimeBestEffort({{end_ts:String}})
              AND toFloat64OrNull(value) > 0
            GROUP BY tag_id;
        """
        rows = self.execute_query(query, {"start_ts": start_ts, "end_ts": end_ts})
        for r in rows:
            max_v = r.get("max_val")
            min_v = r.get("min_val")
            if max_v is not None and min_v is not None and max_v >= min_v:
                total_delta += (max_v - min_v)

        return round(total_delta, round_digits)

    # --------------------------------------------------------------------------
    # 2. Instantaneous Calculation: avg, min, max, peak
    # --------------------------------------------------------------------------
    def calculate_instantaneous(
        self,
        tag_ids: List[str],
        start_ts: str,
        end_ts: str,
        scale_divisor: float = 1.0,
        round_digits: int = 2
    ) -> Dict[str, Optional[float]]:
        """
        Calculate statistical aggregations (avg, min, max) for instantaneous variables.
        scale_divisor: e.g. 100.0 for Power Factor 0-100 scale normalization.
        """
        self.check_capability(TelemetryCapability.INSTANTANEOUS_POWER)
        if not tag_ids:
            return {"avg": None, "min": None, "max": None, "count": 0}

        tag_list_str = ", ".join(f"'{t}'" for t in tag_ids)
        query = f"""
            SELECT
                AVG(toFloat64OrNull(value)) AS avg_val,
                MIN(toFloat64OrNull(value)) AS min_val,
                MAX(toFloat64OrNull(value)) AS max_val,
                COUNT(value) AS cnt
            FROM opcda_readings
            WHERE tag_id IN ({tag_list_str})
              AND reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
              AND reading_timestamp <= parseDateTimeBestEffort({{end_ts:String}})
              AND toFloat64OrNull(value) > 0;
        """
        rows = self.execute_query(query, {"start_ts": start_ts, "end_ts": end_ts})
        if not rows or rows[0].get("cnt", 0) == 0:
            return {"avg": None, "min": None, "max": None, "count": 0}

        row = rows[0]
        avg_v = row.get("avg_val")
        min_v = row.get("min_val")
        max_v = row.get("max_val")

        return {
            "avg": round(float(avg_v) / scale_divisor, round_digits) if avg_v is not None else None,
            "min": round(float(min_v) / scale_divisor, round_digits) if min_v is not None else None,
            "max": round(float(max_v) / scale_divisor, round_digits) if max_v is not None else None,
            "count": int(row.get("cnt", 0))
        }

    # --------------------------------------------------------------------------
    # 3. 24-Hour Hourly Profile
    # --------------------------------------------------------------------------
    def calculate_hourly_profile(
        self,
        tag_ids: List[str],
        date_str: str,
        metric_type: Literal["cumulative", "instantaneous"] = "cumulative",
        scale_divisor: float = 1.0,
        round_digits: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Generate 24-hour hour-by-hour (00:00 to 23:00) profile.
        - cumulative: hourly delta max - min
        - instantaneous: hourly average and max peak
        """
        self.check_capability(TelemetryCapability.HOURLY_PROFILE)
        clean_date = self.normalize_date(date_str)
        start_ts, end_ts = self.get_time_window(clean_date)
        tag_list_str = ", ".join(f"'{t}'" for t in tag_ids)

        if metric_type == "cumulative":
            query = f"""
                SELECT
                    toHour(reading_timestamp) AS hour,
                    tag_id,
                    MAX(toFloat64OrNull(value)) AS max_val,
                    MIN(toFloat64OrNull(value)) AS min_val
                FROM opcda_readings
                WHERE tag_id IN ({tag_list_str})
                  AND reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
                  AND reading_timestamp <= parseDateTimeBestEffort({{end_ts:String}})
                  AND toFloat64OrNull(value) > 0
                GROUP BY hour, tag_id
                ORDER BY hour;
            """
            rows = self.execute_query(query, {"start_ts": start_ts, "end_ts": end_ts})
            hourly_map: Dict[int, float] = {h: 0.0 for h in range(24)}
            for r in rows:
                h = int(r["hour"])
                mx = r.get("max_val")
                mn = r.get("min_val")
                if mx is not None and mn is not None and mx >= mn:
                    hourly_map[h] += (mx - mn)

            return [
                {
                    "hour": f"{h:02d}:00",
                    "hour_int": h,
                    "value": round(hourly_map[h] / scale_divisor, round_digits)
                }
                for h in range(24)
            ]
        else:
            query = f"""
                SELECT
                    toHour(reading_timestamp) AS hour,
                    AVG(toFloat64OrNull(value)) AS avg_val,
                    MAX(toFloat64OrNull(value)) AS max_val
                FROM opcda_readings
                WHERE tag_id IN ({tag_list_str})
                  AND reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
                  AND reading_timestamp <= parseDateTimeBestEffort({{end_ts:String}})
                  AND toFloat64OrNull(value) > 0
                GROUP BY hour
                ORDER BY hour;
            """
            rows = self.execute_query(query, {"start_ts": start_ts, "end_ts": end_ts})
            row_map = {int(r["hour"]): r for r in rows}
            return [
                {
                    "hour": f"{h:02d}:00",
                    "hour_int": h,
                    "avg_value": round(float(row_map[h]["avg_val"]) / scale_divisor, round_digits) if h in row_map and row_map[h]["avg_val"] else None,
                    "peak_value": round(float(row_map[h]["max_val"]) / scale_divisor, round_digits) if h in row_map and row_map[h]["max_val"] else None,
                }
                for h in range(24)
            ]

    # --------------------------------------------------------------------------
    # 4. Manufacturing Shift Breakdown (Section 9)
    # --------------------------------------------------------------------------
    def calculate_shift_breakdown(
        self,
        tag_id: str,
        date_str: str,
        round_digits: int = 1
    ) -> Dict[str, Any]:
        """
        Calculate shift-wise consumption using Section 9 00:40 Rule:
        - Shift A: D 08:00:00 to D 17:00:00
        - Shift B: D 17:00:00 to D+1 00:40:00 (spans midnight into next day)
        - Shift C: D 00:40:00 to D 08:00:00
        """
        self.check_capability(TelemetryCapability.SHIFT_BREAKDOWN)
        clean_date = self.normalize_date(date_str)
        dt = datetime.datetime.strptime(clean_date, "%Y-%m-%d").date()
        next_dt = dt + datetime.timedelta(days=1)
        next_date_str = next_dt.strftime("%Y-%m-%d")

        def _get_boundary_reading(ts_str: str) -> Optional[float]:
            q = """
                SELECT toFloat64OrNull(value) as val
                FROM opcda_readings
                WHERE tag_id = {tag_id:String}
                  AND reading_timestamp <= parseDateTimeBestEffort({ts:String})
                  AND toFloat64OrNull(value) > 0
                ORDER BY reading_timestamp DESC
                LIMIT 1;
            """
            r = self.execute_query(q, {"tag_id": tag_id, "ts": ts_str})
            return float(r[0]["val"]) if (r and r[0].get("val") is not None) else None

        r_c_start = _get_boundary_reading(f"{clean_date} 00:40:00")
        r_c_end = _get_boundary_reading(f"{clean_date} 08:00:00")
        r_a_end = _get_boundary_reading(f"{clean_date} 17:00:00")
        r_b_end = _get_boundary_reading(f"{next_date_str} 00:40:00")

        shift_c = round(r_c_end - r_c_start, round_digits) if (r_c_end and r_c_start and r_c_end >= r_c_start) else 0.0
        shift_a = round(r_a_end - r_c_end, round_digits) if (r_a_end and r_c_end and r_a_end >= r_c_end) else 0.0
        shift_b = round(r_b_end - r_a_end, round_digits) if (r_b_end and r_a_end and r_b_end >= r_a_end) else 0.0

        total_shifts = round(shift_a + shift_b + shift_c, round_digits)

        return {
            "date": clean_date,
            "meter": "HT_Room.11kV_Main_Incomer",
            "meter_tag": tag_id,
            "shift_a_kwh": shift_a,
            "shift_b_kwh": shift_b,
            "shift_c_kwh": shift_c,
            "total_shifts_kwh": total_shifts,
            "windows": {
                "shift_a": "08:00 - 17:00",
                "shift_b": f"17:00 - {next_date_str} 00:40",
                "shift_c": "00:40 - 08:00"
            },
            "shifts": {
                "Shift A": {
                    "energy_kwh": shift_a,
                    "window": "08:00 - 17:00",
                    "percentage": round((shift_a / total_shifts) * 100, 1) if total_shifts > 0 else 0.0
                },
                "Shift B": {
                    "energy_kwh": shift_b,
                    "window": f"17:00 - {next_date_str} 00:40",
                    "percentage": round((shift_b / total_shifts) * 100, 1) if total_shifts > 0 else 0.0
                },
                "Shift C": {
                    "energy_kwh": shift_c,
                    "window": "00:40 - 08:00",
                    "percentage": round((shift_c / total_shifts) * 100, 1) if total_shifts > 0 else 0.0
                }
            },
            "rule": "Section 9: 00:00-00:40 belongs to previous day Shift B"
        }
