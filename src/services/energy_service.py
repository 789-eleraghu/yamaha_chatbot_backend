"""
Core Energy Calculation Service
Implements Section 1 & 2 of energy-ai-assistant-reference.md
"""

import datetime
from typing import Any, Dict, List, Optional
from src.core.constants import SHIFT_ENERGY_TAG
from src.core.normalizers import normalize_date_str
from src.db.sqlite_client import db_client

class EnergyService:
    @staticmethod
    def get_facility_daily_energy(date_str: str) -> Dict[str, Any]:
        """
        Calculate true daily consumption for the facility incomer for a given IST date.
        Uses tag_daily_energy_rollup if available, falls back to raw readings.
        """
        date_str = normalize_date_str(date_str)
        # Try daily rollup
        rollup_val = db_client.get_daily_rollup_energy(SHIFT_ENERGY_TAG, date_str)
        if rollup_val is not None:
            return {
                "date": date_str,
                "tag_id": SHIFT_ENERGY_TAG,
                "energy_kwh": round(rollup_val, 1),
                "source": "daily_rollup"
            }

        # Fallback to raw readings [00:00:00, next day 00:00:00)
        start_ts = f"{date_str} 00:00:00"
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        next_date_str = (dt + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        end_ts = f"{next_date_str} 00:00:00"

        raw_delta = db_client.get_tag_delta(SHIFT_ENERGY_TAG, start_ts, end_ts)
        return {
            "date": date_str,
            "tag_id": SHIFT_ENERGY_TAG,
            "energy_kwh": round(raw_delta, 1) if raw_delta is not None else None,
            "source": "raw_readings"
        }

    @staticmethod
    def get_tag_energy_in_window(tag_id: str, start_ts: str, end_ts: str) -> Optional[float]:
        """Calculate max(counter) - min(counter) for any tag in a custom window."""
        delta = db_client.get_tag_delta(tag_id, start_ts, end_ts)
        return round(delta, 1) if delta is not None else None

    @staticmethod
    def get_multi_day_energy(start_date: str, end_date: str, tag_id: str = SHIFT_ENERGY_TAG) -> Dict[str, Any]:
        """Fetch daily energy values across a date range."""
        query = """
            SELECT date, energy
            FROM tag_daily_energy_rollup
            WHERE tag_id = ? AND date >= ? AND date <= ?
            ORDER BY date ASC;
        """
        rows = db_client.execute_query(query, (tag_id, start_date, end_date))
        daily_records = [{"date": r["date"], "energy_kwh": round(float(r["energy"]), 1)} for r in rows]
        total_kwh = sum(r["energy_kwh"] for r in daily_records)

        return {
            "start_date": start_date,
            "end_date": end_date,
            "tag_id": tag_id,
            "total_kwh": round(total_kwh, 1),
            "daily_records": daily_records
        }
