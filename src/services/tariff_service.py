"""
TOD Tariff & Cost Calculation Service
Implements Section 3 of energy-ai-assistant-reference.md
"""

from typing import Any, Dict, List
from src.core.constants import HOURLY_TARIFF_RATES, SHIFT_ENERGY_TAG
from src.db.sqlite_client import db_client
from src.services.energy_service import EnergyService

class TariffService:
    @staticmethod
    def calculate_daily_cost(date_str: str) -> Dict[str, Any]:
        """
        Calculate daily electricity cost under Tariff HT_1 using the exact rescaling rule:
        1. Calculate true daily kWh
        2. Calculate raw hourly deltas
        3. scale = true_daily_kWh / sum(hourly_kWh)
        4. rescaled_hour = hourly_kWh * scale
        5. cost = sum(rescaled_hour * rate)
        """
        # 1. True daily kWh
        daily_info = EnergyService.get_facility_daily_energy(date_str)
        true_daily_kwh = daily_info.get("energy_kwh")
        if true_daily_kwh is None or true_daily_kwh <= 0:
            return {"date": date_str, "error": "No valid consumption data for date"}

        # 2. Hourly kWh deltas from opcda_readings
        hourly_records = []
        for hour in range(24):
            start_ts = f"{date_str} {hour:02d}:00:00"
            end_ts = f"{date_str} {hour:02d}:59:59"
            h_delta = db_client.get_tag_delta(SHIFT_ENERGY_TAG, start_ts, end_ts) or 0.0
            hourly_records.append({
                "hour": hour,
                "hour_label": f"{hour:02d}:00",
                "raw_kwh": h_delta,
                "rate": HOURLY_TARIFF_RATES[hour]
            })

        sum_hourly_raw = sum(r["raw_kwh"] for r in hourly_records)
        scale_factor = (true_daily_kwh / sum_hourly_raw) if sum_hourly_raw > 0 else 1.0

        # 3 & 4. Rescale and compute cost
        band_summary = {
            "Off-Peak": {"kwh": 0.0, "cost": 0.0, "rate": 7.125},
            "Normal": {"kwh": 0.0, "cost": 0.0, "rate": 7.500},
            "Peak": {"kwh": 0.0, "cost": 0.0, "rate": 9.375},
        }

        total_cost = 0.0
        for r in hourly_records:
            rescaled_kwh = r["raw_kwh"] * scale_factor
            r["rescaled_kwh"] = round(rescaled_kwh, 1)
            hour_cost = rescaled_kwh * r["rate"]
            r["cost_inr"] = round(hour_cost, 2)
            total_cost += hour_cost

            # Band grouping
            if r["rate"] == 7.125:
                band_summary["Off-Peak"]["kwh"] += rescaled_kwh
                band_summary["Off-Peak"]["cost"] += hour_cost
            elif r["rate"] == 7.500:
                band_summary["Normal"]["kwh"] += rescaled_kwh
                band_summary["Normal"]["cost"] += hour_cost
            else:
                band_summary["Peak"]["kwh"] += rescaled_kwh
                band_summary["Peak"]["cost"] += hour_cost

        # Round band results
        for b in band_summary.values():
            b["kwh"] = round(b["kwh"], 1)
            b["cost"] = round(b["cost"], 2)

        return {
            "date": date_str,
            "tariff": "HT_1",
            "true_daily_kwh": round(true_daily_kwh, 1),
            "sum_hourly_raw_kwh": round(sum_hourly_raw, 1),
            "rescaling_factor": round(scale_factor, 4),
            "total_cost_inr": round(total_cost, 2),
            "band_summary": band_summary,
            "hourly_breakdown": hourly_records
        }
