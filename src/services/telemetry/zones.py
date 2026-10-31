"""
Zones Telemetry Service (Tier 4: Organizational Cost Centers & Departments)
Handles 17 factory cost centers (Section 13):
- General Admin, Information System, AG KILN Dry, AG WP Process, AG Painting,
  AG Assy, Guitar Upstream Process, Guitar Painting, Guitar Assy, Packaging,
  Engine Machining, Engine Assy, Frame Machining, South Utility, North Utility,
  Waste Water Treatment, Guard House.

Enforces capability gating: Organizational cost centers support cumulative energy
and hourly profiles. Summing instantaneous power or calculating grid harmonics/steam
is prohibited at the organizational zone level.
"""

from typing import Any, Dict, List, Optional
from src.db.tag_catalog import COST_CENTER_MAPPINGS
from src.services.telemetry.base import (
    BaseTelemetryService,
    TelemetryCapability,
)


class ZonesTelemetryService(BaseTelemetryService):
    """
    Tier 4: Organizational Cost Center / Zone Telemetry Service.
    Enforces cost center tag mappings, aggregation rules, and zone ranking.
    """

    def __init__(self):
        super().__init__(
            tier_name="zones",
            supported_capabilities={
                TelemetryCapability.CUMULATIVE_ENERGY,
                TelemetryCapability.HOURLY_PROFILE,
            }
        )
        self.mappings = COST_CENTER_MAPPINGS

    def list_zones(self) -> List[str]:
        """Returns the list of all 17 configured organizational cost centers."""
        return list(self.mappings.keys())

    def get_zone_breakdown(self, date_str: str) -> Dict[str, Any]:
        """
        Compute energy for all 17 organizational cost centers (Section 13)
        using exact mapped tag lists.
        """
        self.check_capability(TelemetryCapability.CUMULATIVE_ENERGY)
        clean_date = self.normalize_date(date_str)
        cost_centers = []
        total_kwh = 0.0

        for cc_name, tags in self.mappings.items():
            tag_list = ", ".join(f"'{t}'" for t in tags)
            q = f"""
                SELECT ROUND(SUM(tag_energy), 1) AS cc_energy
                FROM (
                    SELECT
                        tag_id,
                        maxMerge(max_value) - minMerge(min_value) as tag_energy
                    FROM tag_daily_energy_rollup
                    WHERE day = toDate({{date:String}})
                      AND tag_id IN ({tag_list})
                    GROUP BY tag_id
                );
            """
            rows = self.execute_query(q, {"date": clean_date})
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
            "date": clean_date,
            "type": "zone_wise_cost_centers",
            "cost_centers_count": len(cost_centers),
            "total_kwh": round(total_kwh, 1),
            "cost_centers": sorted(cost_centers, key=lambda x: x["energy_kwh"], reverse=True)
        }

    def get_cost_center_energy(self, cost_center: str, date_str: str) -> Dict[str, Any]:
        """Compute energy consumption and meter-level breakdown for a specific cost center."""
        self.check_capability(TelemetryCapability.CUMULATIVE_ENERGY)
        clean_date = self.normalize_date(date_str)

        matched_cc = None
        for cc in self.mappings.keys():
            if cc.lower() == cost_center.strip().lower():
                matched_cc = cc
                break

        if not matched_cc:
            return {
                "error": f"Unknown cost center: '{cost_center}'. Available: {', '.join(self.mappings.keys())}"
            }

        tags = self.mappings[matched_cc]
        tag_list = ", ".join(f"'{t}'" for t in tags)
        q = f"""
            SELECT
                tag_id,
                ROUND(maxMerge(max_value) - minMerge(min_value), 1) as tag_energy
            FROM tag_daily_energy_rollup
            WHERE day = toDate({{date:String}})
              AND tag_id IN ({tag_list})
            GROUP BY tag_id
            ORDER BY tag_energy DESC;
        """
        rows = self.execute_query(q, {"date": clean_date})
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
            "cost_center": matched_cc,
            "total_energy_kwh": round(total_kwh, 1),
            "active_meters_count": len(devices),
            "total_configured_meters": len(tags),
            "meters": devices
        }

    def get_cost_center_hourly_profile(self, cost_center: str, date_str: str) -> Dict[str, Any]:
        """Compute 24-hour hourly profile for a specific cost center."""
        self.check_capability(TelemetryCapability.HOURLY_PROFILE)
        clean_date = self.normalize_date(date_str)

        matched_cc = None
        for cc in self.mappings.keys():
            if cc.lower() == cost_center.strip().lower():
                matched_cc = cc
                break

        if not matched_cc:
            return {
                "error": f"Unknown cost center: '{cost_center}'. Available: {', '.join(self.mappings.keys())}"
            }

        tags = self.mappings[matched_cc]
        start_ts, end_ts = self.get_time_window(clean_date)
        tag_list = ", ".join(f"'{t}'" for t in tags)

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
                WHERE tag_id IN ({tag_list})
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
            "cost_center": matched_cc,
            "total_kwh": round(total_kwh, 1),
            "hourly_profile": profile
        }
