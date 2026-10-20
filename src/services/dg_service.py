"""
Diesel Generator (DG) Operations Service
Implements Section 5 of energy-ai-assistant-reference.md
"""

from typing import Any, Dict, List, Optional
from src.core.constants import (
    DG_ENERGY_TAG,
    DG_POWER_TAG,
    DG_RUN_THRESHOLD_KW,
)
from src.db.sqlite_client import db_client

class DGService:
    @staticmethod
    def get_dg_monthly_metrics(month_str: str) -> Dict[str, Any]:
        """
        Calculate DG metrics for a given month (YYYY-MM):
        - Total runtime minutes (real power > 1.0 kW)
        - Energy generated (cumulative counter delta)
        - Starts count, stops count
        - Last completed run
        """
        start_ts = f"{month_str}-01 00:00:00"
        # Last day of month
        end_ts = f"{month_str}-31 23:59:59"

        # 1. Total energy generated in month
        q_energy = """
            SELECT MAX(value) - MIN(value) AS energy_kwh
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ? AND value > 0;
        """
        r_energy = db_client.execute_query(q_energy, (DG_ENERGY_TAG, start_ts, end_ts))
        energy_kwh = round(float(r_energy[0]["energy_kwh"]), 1) if (r_energy and r_energy[0]["energy_kwh"] is not None) else 0.0

        # 2. Query power readings > 1.0 kW to detect runs
        q_runs = """
            SELECT reading_timestamp, value
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ? AND value > ?
            ORDER BY reading_timestamp ASC;
        """
        power_rows = db_client.execute_query(q_runs, (DG_POWER_TAG, start_ts, end_ts, DG_RUN_THRESHOLD_KW))
        runtime_minutes = len(power_rows)

        # Segment into discrete runs
        runs = []
        if power_rows:
            current_run = {
                "start": power_rows[0]["reading_timestamp"],
                "stop": power_rows[0]["reading_timestamp"],
                "minutes": 1,
                "peak_kw": float(power_rows[0]["value"])
            }
            for i in range(1, len(power_rows)):
                curr_row = power_rows[i]
                current_run["stop"] = curr_row["reading_timestamp"]
                current_run["minutes"] += 1
                current_run["peak_kw"] = max(current_run["peak_kw"], float(curr_row["value"]))

            current_run["peak_kw"] = round(current_run["peak_kw"], 1)
            runs.append(current_run)

        # 3. Last completed run overall
        q_last_run = """
            SELECT reading_timestamp, value
            FROM opcda_readings
            WHERE tag_id = ? AND value > ?
            ORDER BY reading_timestamp DESC
            LIMIT 1;
        """
        r_last = db_client.execute_query(q_last_run, (DG_POWER_TAG, DG_RUN_THRESHOLD_KW))
        last_active_ts = r_last[0]["reading_timestamp"] if r_last else None

        return {
            "month": month_str,
            "device": "Incomer.DG_Incomer_300kVA",
            "runtime_minutes": runtime_minutes,
            "runtime_hours": round(runtime_minutes / 60.0, 1),
            "energy_generated_kwh": energy_kwh,
            "starts_count": len(runs),
            "stops_count": len(runs),
            "last_active_timestamp": last_active_ts,
            "runs": runs
        }
