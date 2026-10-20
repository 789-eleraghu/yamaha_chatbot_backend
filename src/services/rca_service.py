"""
Root Cause Analysis (RCA) & Anomaly Detection Service
Answers 'Why was consumption high?' and 'What went wrong?'
"""

import datetime
from typing import Any, Dict, List
from src.core.constants import SHIFT_ENERGY_TAG
from src.db.sqlite_client import db_client
from src.services.breakdown_service import BreakdownService
from src.services.demand_service import DemandService
from src.services.energy_service import EnergyService
from src.services.shift_service import ShiftService

class RCAService:
    @staticmethod
    def diagnose_day(date_str: str) -> Dict[str, Any]:
        """
        Diagnose anomalous consumption on date_str:
        1. Compare against 30-day baseline for the same day-of-week
        2. Identify top variance drivers across Equipment Categories
        3. Check for night shift (Shift C) baseload inflation
        4. Cross-reference peak demand excursions
        """
        target_energy = EnergyService.get_facility_daily_energy(date_str)
        day_kwh = target_energy.get("energy_kwh") or 0.0

        # Calculate 30-day baseline
        target_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        weekday = target_dt.weekday()

        # Query past days
        q_history = """
            SELECT date, energy
            FROM tag_daily_energy_rollup
            WHERE tag_id = ? AND date < ?
            ORDER BY date DESC
            LIMIT 30;
        """
        history_rows = db_client.execute_query(q_history, (SHIFT_ENERGY_TAG, date_str))
        
        # Same weekday average
        same_day_vals = [
            float(r["energy"]) for r in history_rows 
            if datetime.datetime.strptime(r["date"], "%Y-%m-%d").date().weekday() == weekday
        ]
        baseline_kwh = round(sum(same_day_vals) / len(same_day_vals), 1) if same_day_vals else day_kwh
        variance_kwh = round(day_kwh - baseline_kwh, 1)
        variance_pct = round((variance_kwh / baseline_kwh) * 100.0, 1) if baseline_kwh > 0 else 0.0

        # Category breakdown
        equipment_breakdown = BreakdownService.get_equipment_wise_breakdown(date_str)
        cost_center_breakdown = BreakdownService.get_zone_wise_cost_centers(date_str)

        # Shift analysis
        shift_data = ShiftService.get_shift_consumption(date_str)

        # Peak demand check
        demand_data = DemandService.get_peak_demand_analysis(date_str)

        # Drivers summary
        top_categories = equipment_breakdown.get("categories", [])[:3]
        top_cost_centers = cost_center_breakdown.get("cost_centers", [])[:3]

        return {
            "target_date": date_str,
            "actual_consumption_kwh": day_kwh,
            "baseline_consumption_kwh": baseline_kwh,
            "variance_kwh": variance_kwh,
            "variance_percent": variance_pct,
            "is_anomaly": variance_pct > 10.0,
            "shift_distribution": {
                "shift_a_kwh": shift_data.get("shift_a_kwh"),
                "shift_b_kwh": shift_data.get("shift_b_kwh"),
                "shift_c_kwh": shift_data.get("shift_c_kwh"),
            },
            "peak_demand": {
                "peak_kva": demand_data.get("peak_kva"),
                "utilization_percent": demand_data.get("utilization_percent"),
                "excursions_above_1180kva": demand_data.get("excursion_events_count", 0)
            },
            "top_consuming_categories": top_categories,
            "top_consuming_cost_centers": top_cost_centers
        }
