"""
Shift-Wise Consumption Service
Implements Section 9 of energy-ai-assistant-reference.md
"""

import datetime
from typing import Any, Dict, Optional
from src.core.constants import SHIFT_ENERGY_TAG
from src.core.normalizers import normalize_date_str
from src.db.sqlite_client import db_client

class ShiftService:
    @staticmethod
    def get_shift_consumption(date_str: str) -> Dict[str, Any]:
        """
        Calculate shift-wise consumption for calendar day D:
        - Shift C: D 00:40 -> D 08:00
        - Shift A: D 08:00 -> D 17:00
        - Shift B: D 17:00 -> D+1 00:40
        """
        date_str = normalize_date_str(date_str)
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        next_dt = dt + datetime.timedelta(days=1)
        next_date_str = next_dt.strftime("%Y-%m-%d")

        # Boundary timestamps
        ts_c_start = f"{date_str} 00:40:00"
        ts_c_end = f"{date_str} 08:00:00"
        ts_a_start = f"{date_str} 08:00:00"
        ts_a_end = f"{date_str} 17:00:00"
        ts_b_start = f"{date_str} 17:00:00"
        ts_b_end = f"{next_date_str} 00:40:00"

        c_start_val = db_client.get_nearest_reading_before(SHIFT_ENERGY_TAG, ts_c_start)
        c_end_val = db_client.get_nearest_reading_before(SHIFT_ENERGY_TAG, ts_c_end)
        a_end_val = db_client.get_nearest_reading_before(SHIFT_ENERGY_TAG, ts_a_end)
        b_end_val = db_client.get_nearest_reading_before(SHIFT_ENERGY_TAG, ts_b_end)

        shift_c = round(c_end_val - c_start_val, 1) if (c_start_val is not None and c_end_val is not None) else None
        shift_a = round(a_end_val - c_end_val, 1) if (c_end_val is not None and a_end_val is not None) else None
        shift_b = round(b_end_val - a_end_val, 1) if (a_end_val is not None and b_end_val is not None) else None

        valid_shifts = [s for s in [shift_a, shift_b, shift_c] if s is not None]
        total_shifts = round(sum(valid_shifts), 1) if valid_shifts else None

        return {
            "date": date_str,
            "meter": "HT_Room.11kV_Main_Incomer",
            "shift_a_kwh": shift_a,
            "shift_b_kwh": shift_b,
            "shift_c_kwh": shift_c,
            "total_shifts_kwh": total_shifts,
            "windows": {
                "shift_a": "08:00 - 17:00",
                "shift_b": f"17:00 - {next_date_str} 00:40",
                "shift_c": "00:40 - 08:00"
            }
        }
