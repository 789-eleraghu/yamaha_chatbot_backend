"""
Power Quality & Utilities Service
Implements Section 6 (THD), Section 7 (Reactive Energy), and Section 8 (Steam)
"""

from typing import Any, Dict, List
from src.core.constants import (
    CURRENT_THD_LIMIT_PERCENT,
    CURRENT_THD_TAGS,
    REACTIVE_ENERGY_TAGS,
    STEAM_FLOW_RATE_TAG,
    STEAM_PRESSURE_TAG,
    STEAM_TOTALIZER_TAG,
    VOLTAGE_THD_LIMIT_PERCENT,
    VOLTAGE_THD_TAGS,
)
from src.core.normalizers import normalize_date_str
from src.db.sqlite_client import db_client

class PowerQualityService:
    @staticmethod
    def get_thd_analysis(date_str: str) -> Dict[str, Any]:
        """
        Analyze Voltage and Current Harmonics (THD) for South Utilities Transformer.
        Limits: Voltage THD = 5%, Current THD = 8%
        """
        date_str = normalize_date_str(date_str)
        start_ts = f"{date_str} 00:00:00"
        end_ts = f"{date_str} 23:59:59"

        # 1. Voltage THD (L-N is representative)
        v_tag = VOLTAGE_THD_TAGS[3]  # L-N
        q_v = """
            SELECT AVG(value) AS avg_thd, MAX(value) AS max_thd
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ? AND value > 0;
        """
        r_v = db_client.execute_query(q_v, (v_tag, start_ts, end_ts))
        v_avg = round(float(r_v[0]["avg_thd"]), 2) if (r_v and r_v[0]["avg_thd"]) else None
        v_max = round(float(r_v[0]["max_thd"]), 2) if (r_v and r_v[0]["max_thd"]) else None

        # 2. Combined Current THD = average(A, B, C)
        q_c = f"""
            SELECT 
                AVG((a.value + b.value + c.value) / 3.0) AS avg_c_thd,
                MAX((a.value + b.value + c.value) / 3.0) AS max_c_thd
            FROM opcda_readings a
            JOIN opcda_readings b ON a.reading_timestamp = b.reading_timestamp AND b.tag_id = '{CURRENT_THD_TAGS[1]}'
            JOIN opcda_readings c ON a.reading_timestamp = c.reading_timestamp AND c.tag_id = '{CURRENT_THD_TAGS[2]}'
            WHERE a.tag_id = '{CURRENT_THD_TAGS[0]}' AND a.reading_timestamp >= ? AND a.reading_timestamp <= ?;
        """
        r_c = db_client.execute_query(q_c, (start_ts, end_ts))
        c_avg = round(float(r_c[0]["avg_c_thd"]), 2) if (r_c and r_c[0]["avg_c_thd"]) else None
        c_max = round(float(r_c[0]["max_c_thd"]), 2) if (r_c and r_c[0]["max_c_thd"]) else None

        return {
            "date": date_str,
            "meter": "HT_Room.South_Utilities_1000kVA_Transformer",
            "voltage_thd": {
                "tag": v_tag,
                "average_percent": v_avg,
                "max_percent": v_max,
                "limit_percent": VOLTAGE_THD_LIMIT_PERCENT,
                "exceeded": (v_max is not None and v_max > VOLTAGE_THD_LIMIT_PERCENT)
            },
            "current_thd": {
                "average_percent": c_avg,
                "max_percent": c_max,
                "limit_percent": CURRENT_THD_LIMIT_PERCENT,
                "exceeded": (c_max is not None and c_max > CURRENT_THD_LIMIT_PERCENT)
            }
        }

    @staticmethod
    def get_reactive_energy(date_str: str) -> Dict[str, Any]:
        """Calculate cumulative kVARh for the 2 trustworthy transformers."""
        date_str = normalize_date_str(date_str)
        start_ts = f"{date_str} 00:00:00"
        end_ts = f"{date_str} 23:59:59"

        results = {}
        for dev, tag in REACTIVE_ENERGY_TAGS.items():
            delta = db_client.get_tag_delta(tag, start_ts, end_ts)
            results[dev] = round(delta, 1) if delta is not None else None

        return {
            "date": date_str,
            "unit": "kVARh",
            "transformers": results
        }

    @staticmethod
    def get_steam_summary(date_str: str) -> Dict[str, Any]:
        """Get Steam flow rate snapshot, pressure, and steam consumed for date."""
        date_str = normalize_date_str(date_str)
        # Latest snapshot
        q_snap = """
            SELECT tag_id, value, reading_timestamp
            FROM opcda_readings
            WHERE tag_id IN (?, ?)
            ORDER BY reading_timestamp DESC
            LIMIT 2;
        """
        snap_rows = db_client.execute_query(q_snap, (STEAM_FLOW_RATE_TAG, STEAM_PRESSURE_TAG))
        flow_rate = None
        pressure = None
        ts = None
        for r in snap_rows:
            ts = r["reading_timestamp"]
            if r["tag_id"] == STEAM_FLOW_RATE_TAG:
                flow_rate = round(float(r["value"]), 1)
            elif r["tag_id"] == STEAM_PRESSURE_TAG:
                pressure = round(float(r["value"]), 2)

        # Steam consumed today = max(totalizer) - min(totalizer)
        start_ts = f"{date_str} 00:00:00"
        end_ts = f"{date_str} 23:59:59"
        steam_kgh = db_client.get_tag_delta(STEAM_TOTALIZER_TAG, start_ts, end_ts)

        return {
            "date": date_str,
            "device": "Flowmeter-Gate1.Blower_Room_Steam",
            "snapshot_timestamp": ts,
            "current_flow_rate_kgh": flow_rate,
            "current_pressure_bar": pressure,
            "steam_consumed_kg": round(steam_kgh, 1) if steam_kgh is not None else None
        }
