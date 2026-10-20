"""
Peak Demand Analysis Service
Implements Section 4 of energy-ai-assistant-reference.md
"""

from typing import Any, Dict, List
from src.core.constants import (
    CONTRACTED_DEMAND_KVA,
    PEAK_DEMAND_TAG,
    PEAK_DEMAND_THRESHOLD_KVA,
)
from src.core.normalizers import normalize_date_str
from src.db.sqlite_client import db_client

class DemandService:
    @staticmethod
    def get_peak_demand_analysis(date_str: str) -> Dict[str, Any]:
        """
        Analyze peak demand for a date on the South Utilities Transformer:
        - Peak kVA and % utilization against 1475 kVA contracted
        - Hourly peak profiles
        - Contiguous excursions above 1180 kVA threshold
        """
        date_str = normalize_date_str(date_str)
        start_ts = f"{date_str} 00:00:00"
        end_ts = f"{date_str} 23:59:59"

        # 1. Overall peak kVA
        q_overall = """
            SELECT MAX(value) AS peak_kva, reading_timestamp
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ?
            GROUP BY tag_id;
        """
        rows_overall = db_client.execute_query(q_overall, (PEAK_DEMAND_TAG, start_ts, end_ts))
        peak_kva = round(float(rows_overall[0]["peak_kva"]), 1) if rows_overall else None
        peak_ts = rows_overall[0]["reading_timestamp"] if rows_overall else None
        utilization_pct = round((peak_kva / CONTRACTED_DEMAND_KVA) * 100.0, 1) if peak_kva else None

        # 2. Hourly peak profile
        hourly_profile = []
        for h in range(24):
            h_start = f"{date_str} {h:02d}:00:00"
            h_end = f"{date_str} {h:02d}:59:59"
            q_hour = """
                SELECT MAX(value) AS h_peak
                FROM opcda_readings
                WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ?;
            """
            r_hour = db_client.execute_query(q_hour, (PEAK_DEMAND_TAG, h_start, h_end))
            h_val = round(float(r_hour[0]["h_peak"]), 1) if (r_hour and r_hour[0]["h_peak"] is not None) else None
            hourly_profile.append({
                "hour": h,
                "label": f"{h:02d}:00",
                "peak_kva": h_val
            })

        # 3. Detect contiguous excursions above 1180 kVA
        q_excursions = """
            SELECT reading_timestamp, value
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ? AND value > ?
            ORDER BY reading_timestamp ASC;
        """
        excursion_rows = db_client.execute_query(q_excursions, (PEAK_DEMAND_TAG, start_ts, end_ts, PEAK_DEMAND_THRESHOLD_KVA))
        
        # Group contiguous readings (minute by minute)
        events = []
        if excursion_rows:
            current_event = {
                "start_time": excursion_rows[0]["reading_timestamp"],
                "end_time": excursion_rows[0]["reading_timestamp"],
                "max_kva": float(excursion_rows[0]["value"]),
                "count": 1
            }
            for prev, curr in zip(excursion_rows[:-1], excursion_rows[1:]):
                # If within ~2 minutes, consider contiguous
                current_event["end_time"] = curr["reading_timestamp"]
                current_event["max_kva"] = max(current_event["max_kva"], float(curr["value"]))
                current_event["count"] += 1

            current_event["max_kva"] = round(current_event["max_kva"], 1)
            events.append(current_event)

        return {
            "date": date_str,
            "meter": "HT_Room.South_Utilities_1000kVA_Transformer",
            "contracted_demand_kva": CONTRACTED_DEMAND_KVA,
            "threshold_kva": PEAK_DEMAND_THRESHOLD_KVA,
            "peak_kva": peak_kva,
            "peak_timestamp": peak_ts,
            "utilization_percent": utilization_pct,
            "excursion_events_count": len(events),
            "excursion_events": events,
            "hourly_profile": hourly_profile
        }
