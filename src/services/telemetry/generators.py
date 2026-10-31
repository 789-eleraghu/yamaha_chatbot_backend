"""
Generators Telemetry Service (Tier 2: Backup Generation & Captive Power)
Handles Diesel Generator (DG) operational status, captive power generation,
runtime minutes (real power > 1.0 kW threshold), start/stop cycles, and load profile.

Enforces capability gating: DG does not run on factory shifts, has no utility contract kVA,
and does not measure steam or power quality harmonics.
"""

from typing import Any, Dict, List, Optional
from src.core.constants import (
    DG_ENERGY_TAG,
    DG_POWER_TAG,
    DG_RUN_THRESHOLD_KW,
)
from src.services.telemetry.base import (
    BaseTelemetryService,
    TelemetryCapability,
)


class GeneratorsTelemetryService(BaseTelemetryService):
    """
    Tier 2: Captive Generation Telemetry Service.
    Enforces real-power threshold detection for operational runs and start/stop tracking.
    """

    def __init__(self):
        super().__init__(
            tier_name="generators",
            supported_capabilities={
                TelemetryCapability.CUMULATIVE_ENERGY,
                TelemetryCapability.INSTANTANEOUS_POWER,
                TelemetryCapability.RUN_DETECTION,
                TelemetryCapability.HOURLY_PROFILE,
            }
        )

    def get_monthly_metrics(self, month_str: str) -> Dict[str, Any]:
        """
        Calculate Diesel Generator operational metrics for a given month (YYYY-MM):
        - Total runtime minutes (real power > 1.0 kW)
        - Energy generated (cumulative counter delta kWh)
        - Starts count, stops count
        - Active run details and last active timestamp
        """
        self.check_capability(TelemetryCapability.RUN_DETECTION)
        self.check_capability(TelemetryCapability.CUMULATIVE_ENERGY)

        clean_month = month_str.strip()[:7]
        start_ts = f"{clean_month}-01 00:00:00"
        end_ts = f"{clean_month}-31 23:59:59"

        # 1. Total energy generated in month using BaseTelemetry calculation
        energy_kwh = self.calculate_cumulative([DG_ENERGY_TAG], start_ts, end_ts)

        # 2. Query power readings > 1.0 kW to detect runs
        q_runs = """
            SELECT reading_timestamp, toFloat64OrNull(value) as value
            FROM opcda_readings
            WHERE tag_id = {tag_id:String}
              AND reading_timestamp >= parseDateTimeBestEffort({start_ts:String})
              AND reading_timestamp <= parseDateTimeBestEffort({end_ts:String})
              AND value > {threshold:Float64}
            ORDER BY reading_timestamp ASC;
        """
        power_rows = self.execute_query(q_runs, {
            "tag_id": DG_POWER_TAG,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "threshold": DG_RUN_THRESHOLD_KW
        })
        runtime_minutes = len(power_rows)

        # Segment into discrete runs
        runs: List[Dict[str, Any]] = []
        if power_rows:
            current_run = {
                "start": str(power_rows[0]["reading_timestamp"]),
                "stop": str(power_rows[0]["reading_timestamp"]),
                "minutes": 1,
                "peak_kw": float(power_rows[0]["value"])
            }
            for i in range(1, len(power_rows)):
                curr_row = power_rows[i]
                current_run["stop"] = str(curr_row["reading_timestamp"])
                current_run["minutes"] += 1
                current_run["peak_kw"] = max(current_run["peak_kw"], float(curr_row["value"]))

            current_run["peak_kw"] = round(current_run["peak_kw"], 1)
            runs.append(current_run)

        # 3. Last completed run overall
        q_last_run = """
            SELECT reading_timestamp, toFloat64OrNull(value) as value
            FROM opcda_readings
            WHERE tag_id = {tag_id:String}
              AND value > {threshold:Float64}
            ORDER BY reading_timestamp DESC
            LIMIT 1;
        """
        r_last = self.execute_query(q_last_run, {
            "tag_id": DG_POWER_TAG,
            "threshold": DG_RUN_THRESHOLD_KW
        })
        last_active_ts = str(r_last[0]["reading_timestamp"]) if r_last else None

        return {
            "month": clean_month,
            "generator": "Incomer.DG_Incomer_300kVA",
            "capacity_kva": 300.0,
            "runtime_minutes": runtime_minutes,
            "runtime_hours": round(runtime_minutes / 60.0, 1),
            "energy_generated_kwh": energy_kwh,
            "starts_count": len(runs),
            "stops_count": len(runs),
            "active_runs": runs,
            "last_active_timestamp": last_active_ts,
            "run_threshold_kw": DG_RUN_THRESHOLD_KW
        }

    def get_daily_metrics(self, date_str: str) -> Dict[str, Any]:
        """Calculate DG operational metrics for a single date (YYYY-MM-DD)."""
        self.check_capability(TelemetryCapability.RUN_DETECTION)
        clean_date = self.normalize_date(date_str)
        start_ts, end_ts = self.get_time_window(clean_date)

        energy_kwh = self.calculate_cumulative([DG_ENERGY_TAG], start_ts, end_ts)

        q_runs = """
            SELECT reading_timestamp, toFloat64OrNull(value) as value
            FROM opcda_readings
            WHERE tag_id = {tag_id:String}
              AND reading_timestamp >= parseDateTimeBestEffort({start_ts:String})
              AND reading_timestamp <= parseDateTimeBestEffort({end_ts:String})
              AND value > {threshold:Float64}
            ORDER BY reading_timestamp ASC;
        """
        power_rows = self.execute_query(q_runs, {
            "tag_id": DG_POWER_TAG,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "threshold": DG_RUN_THRESHOLD_KW
        })
        runtime_minutes = len(power_rows)

        runs: List[Dict[str, Any]] = []
        if power_rows:
            current_run = {
                "start": str(power_rows[0]["reading_timestamp"]),
                "stop": str(power_rows[0]["reading_timestamp"]),
                "minutes": 1,
                "peak_kw": float(power_rows[0]["value"])
            }
            for i in range(1, len(power_rows)):
                curr_row = power_rows[i]
                current_run["stop"] = str(curr_row["reading_timestamp"])
                current_run["minutes"] += 1
                current_run["peak_kw"] = max(current_run["peak_kw"], float(curr_row["value"]))

            current_run["peak_kw"] = round(current_run["peak_kw"], 1)
            runs.append(current_run)

        return {
            "date": clean_date,
            "generator": "Incomer.DG_Incomer_300kVA",
            "capacity_kva": 300.0,
            "runtime_minutes": runtime_minutes,
            "runtime_hours": round(runtime_minutes / 60.0, 1),
            "energy_generated_kwh": energy_kwh,
            "starts_count": len(runs),
            "stops_count": len(runs),
            "active_runs": runs,
            "run_threshold_kw": DG_RUN_THRESHOLD_KW
        }
