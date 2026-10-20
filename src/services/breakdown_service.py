"""
Breakdown Service: Equipment-Wise Categories vs Zone-Wise Cost Centers
Implements Section 10, 11, 12 & 13 of energy-ai-assistant-reference.md
"""

from typing import Any, Dict, List
from src.core.constants import CATEGORY_EXCLUDED_TAGS, EQUIPMENT_WISE_CATEGORIES
from src.core.normalizers import normalize_date_str
from src.db.sqlite_client import db_client
from src.db.tag_catalog import COST_CENTER_MAPPINGS

class BreakdownService:
    @staticmethod
    def get_equipment_wise_breakdown(date_str: str) -> Dict[str, Any]:
        """
        Compute energy for the 8 standard equipment categories (Section 12),
        applying the mandatory exclusions (G0_144_Dust_Collector & PA_FA_Inspection_Box-AC).
        """
        date_str = normalize_date_str(date_str)
        category_results = []
        total_kwh = 0.0

        for cat in EQUIPMENT_WISE_CATEGORIES:
            prefix = f"{cat}."
            # Exclude specific devices from category rollups (Section 11)
            q = f"""
                SELECT SUM(energy) AS cat_energy
                FROM tag_daily_energy_rollup
                WHERE date = ? 
                  AND tag_id LIKE '{prefix}%'
                  AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                  AND tag_id NOT IN ('{"', '".join(CATEGORY_EXCLUDED_TAGS)}');
            """
            rows = db_client.execute_query(q, (date_str,))
            val = round(float(rows[0]["cat_energy"]), 1) if (rows and rows[0]["cat_energy"] is not None) else 0.0
            total_kwh += val
            category_results.append({
                "category": cat,
                "energy_kwh": val
            })

        # Calculate percentages
        for item in category_results:
            pct = round((item["energy_kwh"] / total_kwh) * 100.0, 1) if total_kwh > 0 else 0.0
            item["percentage"] = pct

        return {
            "date": date_str,
            "type": "equipment_wise",
            "categories_count": len(category_results),
            "total_kwh": round(total_kwh, 1),
            "categories": sorted(category_results, key=lambda x: x["energy_kwh"], reverse=True)
        }

    @staticmethod
    def get_zone_wise_cost_centers(date_str: str) -> Dict[str, Any]:
        """
        Compute energy for the 17 organizational cost centers (Section 13)
        using exact mapped tag lists.
        """
        date_str = normalize_date_str(date_str)
        cost_centers = []
        total_kwh = 0.0

        for cc_name, tags in COST_CENTER_MAPPINGS.items():
            placeholders = ",".join("?" for _ in tags)
            q = f"""
                SELECT SUM(energy) AS cc_energy
                FROM tag_daily_energy_rollup
                WHERE date = ? AND tag_id IN ({placeholders});
            """
            rows = db_client.execute_query(q, [date_str] + tags)
            val = round(float(rows[0]["cc_energy"]), 1) if (rows and rows[0]["cc_energy"] is not None) else 0.0
            total_kwh += val
            cost_centers.append({
                "cost_center": cc_name,
                "energy_kwh": val,
                "tag_count": len(tags)
            })

        for item in cost_centers:
            pct = round((item["energy_kwh"] / total_kwh) * 100.0, 1) if total_kwh > 0 else 0.0
            item["percentage"] = pct

        return {
            "date": date_str,
            "type": "zone_wise_cost_centers",
            "cost_centers_count": len(cost_centers),
            "total_kwh": round(total_kwh, 1),
            "cost_centers": sorted(cost_centers, key=lambda x: x["energy_kwh"], reverse=True)
        }
