"""
Equipments Telemetry Service (Tier 3: Manufacturing Machinery & Load Categories)
Handles 8 industrial equipment categories:
- Lighting, Molding, Compressor, Airconditioning, Dust_Collector, Paintshop, Production_Power, Others
Enforces mandatory exclusions (G0_144_Dust_Collector & PA_FA_Inspection_Box-AC per Section 11 & 15).
Provides category breakdowns, single-category energy, device-level instantaneous telemetry, and load curves.
"""

from typing import Any, Dict, List, Optional
from src.core.constants import (
    CATEGORY_EXCLUDED_TAGS,
    EQUIPMENT_WISE_CATEGORIES,
)
from src.services.telemetry.base import (
    BaseTelemetryService,
    TelemetryCapability,
)


class EquipmentsTelemetryService(BaseTelemetryService):
    """
    Tier 3: Equipment & Load Category Telemetry Service.
    Enforces category filtering, tag exclusions, and equipment-level telemetry aggregations.
    """

    def __init__(self):
        super().__init__(
            tier_name="equipments",
            supported_capabilities={
                TelemetryCapability.CUMULATIVE_ENERGY,
                TelemetryCapability.INSTANTANEOUS_POWER,
                TelemetryCapability.HOURLY_PROFILE,
            }
        )
        self.categories = EQUIPMENT_WISE_CATEGORIES
        self.excluded_tags = CATEGORY_EXCLUDED_TAGS

    def get_category_breakdown(self, date_str: str) -> Dict[str, Any]:
        """
        Compute energy for all 8 standard equipment categories (Section 12),
        applying the mandatory exclusions (G0_144_Dust_Collector & PA_FA_Inspection_Box-AC).
        """
        self.check_capability(TelemetryCapability.CUMULATIVE_ENERGY)
        clean_date = self.normalize_date(date_str)
        category_results = []
        total_kwh = 0.0
        excluded_list = ", ".join(f"'{t}'" for t in self.excluded_tags)

        for cat in self.categories:
            prefix = f"{cat}.%"
            q = f"""
                SELECT ROUND(SUM(tag_energy), 1) AS cat_energy
                FROM (
                    SELECT
                        tag_id,
                        maxMerge(max_value) - minMerge(min_value) as tag_energy
                    FROM tag_daily_energy_rollup
                    WHERE day = toDate({{date:String}})
                      AND tag_id LIKE {{prefix:String}}
                      AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                      AND tag_id NOT IN ({excluded_list})
                    GROUP BY tag_id
                );
            """
            rows = self.execute_query(q, {"date": clean_date, "prefix": prefix})
            val = round(float(rows[0]["cat_energy"]), 1) if (rows and rows[0]["cat_energy"] is not None) else 0.0
            total_kwh += val
            category_results.append({
                "category": cat,
                "energy_kwh": val
            })

        for item in category_results:
            pct = round((item["energy_kwh"] / total_kwh) * 100.0, 1) if total_kwh > 0 else 0.0
            item["percentage"] = pct

        return {
            "date": clean_date,
            "type": "equipment_wise",
            "categories_count": len(category_results),
            "total_kwh": round(total_kwh, 1),
            "categories": sorted(category_results, key=lambda x: x["energy_kwh"], reverse=True)
        }

    def get_category_energy(self, category: str, date_str: str) -> Dict[str, Any]:
        """Compute energy consumption for a specific equipment category."""
        self.check_capability(TelemetryCapability.CUMULATIVE_ENERGY)
        clean_date = self.normalize_date(date_str)

        matched_cat = None
        for cat in self.categories:
            if cat.lower() == category.strip().lower():
                matched_cat = cat
                break

        if not matched_cat:
            return {
                "error": f"Unknown equipment category: '{category}'. Valid categories: {', '.join(self.categories)}"
            }

        prefix = f"{matched_cat}.%"
        excluded_list = ", ".join(f"'{t}'" for t in self.excluded_tags)
        q = f"""
            SELECT
                tag_id,
                ROUND(maxMerge(max_value) - minMerge(min_value), 1) as tag_energy
            FROM tag_daily_energy_rollup
            WHERE day = toDate({{date:String}})
              AND tag_id LIKE {{prefix:String}}
              AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
              AND tag_id NOT IN ({excluded_list})
            GROUP BY tag_id
            ORDER BY tag_energy DESC;
        """
        rows = self.execute_query(q, {"date": clean_date, "prefix": prefix})
        devices = []
        total_kwh = 0.0
        for r in rows:
            energy = float(r["tag_energy"]) if r.get("tag_energy") is not None else 0.0
            if energy > 0:
                total_kwh += energy
                dev_name = r["tag_id"].split("/")[0] if "/" in r["tag_id"] else r["tag_id"]
                devices.append({
                    "device": dev_name,
                    "tag_id": r["tag_id"],
                    "energy_kwh": round(energy, 1)
                })

        return {
            "date": clean_date,
            "category": matched_cat,
            "total_energy_kwh": round(total_kwh, 1),
            "device_count": len(devices),
            "devices": devices
        }

    def get_category_hourly_profile(self, category: str, date_str: str) -> Dict[str, Any]:
        """Compute 24-hour hourly profile for an equipment category."""
        self.check_capability(TelemetryCapability.HOURLY_PROFILE)
        clean_date = self.normalize_date(date_str)

        matched_cat = None
        for cat in self.categories:
            if cat.lower() == category.strip().lower():
                matched_cat = cat
                break

        if not matched_cat:
            return {
                "error": f"Unknown equipment category: '{category}'. Valid categories: {', '.join(self.categories)}"
            }

        prefix = f"{matched_cat}.%"
        excluded_list = ", ".join(f"'{t}'" for t in self.excluded_tags)
        start_ts, end_ts = self.get_time_window(clean_date)

        q = f"""
            SELECT
                toHour(reading_timestamp) AS hour,
                ROUND(SUM(delta), 1) AS hourly_kwh
            FROM (
                SELECT
                    toHour(reading_timestamp) AS hour,
                    tag_id,
                    MAX(toFloat64OrNull(value)) - MIN(toFloat64OrNull(value)) AS delta
                FROM opcda_readings
                WHERE tag_id LIKE '{prefix}'
                  AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                  AND tag_id NOT IN ({excluded_list})
                  AND reading_timestamp >= parseDateTimeBestEffort('{start_ts}')
                  AND reading_timestamp <= parseDateTimeBestEffort('{end_ts}')
                  AND toFloat64OrNull(value) > 0
                GROUP BY hour, tag_id
            )
            GROUP BY hour
            ORDER BY hour;
        """
        rows = self.execute_query(q)
        hour_map = {int(r["hour"]): float(r["hourly_kwh"]) for r in rows}

        profile = [
            {
                "hour": f"{h:02d}:00",
                "energy_kwh": round(hour_map.get(h, 0.0), 1)
            }
            for h in range(24)
        ]
        total_kwh = sum(p["energy_kwh"] for p in profile)

        return {
            "date": clean_date,
            "category": matched_cat,
            "total_kwh": round(total_kwh, 1),
            "hourly_profile": profile
        }

    def get_device_telemetry(self, device_name: Optional[str] = None) -> Dict[str, Any]:
        """Get live real-time diagnostic telemetry snapshots for equipment machinery."""
        self.check_capability(TelemetryCapability.INSTANTANEOUS_POWER)
        from src.db.chat_history import chat_repo
        readings = chat_repo.get_live_device_telemetry(device_name)
        return {
            "status": "success",
            "device_filter": device_name,
            "count": len(readings),
            "telemetry": readings
        }
