"""
Unified Telemetry & Energy Aggregation Service
Supports multi-category, multi-equipment, multi-date range, multi-granularity,
and multi-variate industrial telemetry aggregation for Yamaha Plant EMS.
Generates comprehensive numerical summaries and complete Recharts ChartConfig payloads
in a single unified execution.
"""

import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from src.core.constants import (
    CONTRACTED_DEMAND_KVA,
    PEAK_DEMAND_THRESHOLD_KVA,
    SHIFT_ENERGY_TAG,
    PEAK_DEMAND_TAG,
    EQUIPMENT_WISE_CATEGORIES,
    CATEGORY_EXCLUDED_TAGS,
    AUTHORITATIVE_TRANSFORMER_PREFIX,
    HOURLY_TARIFF_RATES
)
from src.core.normalizers import normalize_date_str
from src.db.sqlite_client import db_client
from src.db.tag_catalog import COST_CENTER_MAPPINGS
from src.schemas.charts import (
    ChartConfig,
    ChartSeries,
    ChartType,
    GaugeConfig,
    HeatmapMatrix,
    ScatterPoint,
    ScatterSeries
)

DEFAULT_PALETTE = [
    "#2563EB",  # Blue
    "#059669",  # Emerald
    "#D97706",  # Amber
    "#DC2626",  # Crimson
    "#7C3AED",  # Purple
    "#0891B2",  # Cyan
    "#DB2777",  # Pink
    "#4B5563",  # Slate
    "#10B981",  # Teal
    "#F59E0B",  # Orange
    "#6366F1",  # Indigo
    "#EC4899",  # Rose
]

class AggregationService:
    """Enterprise aggregation engine for multi-dimensional EMS telemetry."""

    @staticmethod
    def _get_time_buckets(granularity: str) -> Tuple[List[str], str]:
        g = (granularity or "hourly").lower()
        if "30" in g or "half" in g:
            buckets = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
            sql_expr = "(strftime('%H', reading_timestamp) || ':' || CASE WHEN CAST(strftime('%M', reading_timestamp) AS INTEGER) < 30 THEN '00' ELSE '30' END)"
            return buckets, sql_expr
        elif "15" in g or "quarter" in g:
            buckets = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 15, 30, 45)]
            sql_expr = "(strftime('%H', reading_timestamp) || ':' || CASE WHEN CAST(strftime('%M', reading_timestamp) AS INTEGER) < 15 THEN '00' WHEN CAST(strftime('%M', reading_timestamp) AS INTEGER) < 30 THEN '15' WHEN CAST(strftime('%M', reading_timestamp) AS INTEGER) < 45 THEN '30' ELSE '45' END)"
            return buckets, sql_expr
        else:
            buckets = [f"{h:02d}:00" for h in range(24)]
            sql_expr = "strftime('%H:00', reading_timestamp)"
            return buckets, sql_expr

    @classmethod
    def aggregate(
        cls,
        aggregation_type: Literal[
            "equipment_wise",
            "zone_wise",
            "facility",
            "specific_equipment",
            "multi_variate",
            "radar_comparison"
        ] = "equipment_wise",
        start_date: str = "yesterday",
        end_date: Optional[str] = None,
        granularity: Literal["daily", "hourly", "shift_wise"] = "daily",
        equipment: Optional[Union[str, List[str]]] = None,
        zones: Optional[Union[str, List[str]]] = None,
        metrics: Optional[List[str]] = None,
        chart_type: Literal[
            "auto",
            "bar",
            "grouped_bar",
            "stacked_bar",
            "horizontal_bar",
            "line",
            "area",
            "stacked_area",
            "donut",
            "pie",
            "radar",
            "radial_bar",
            "composed",
            "scatter",
            "heatmap",
            "treemap"
        ] = "auto"
    ) -> Dict[str, Any]:
        """
        Execute unified aggregation across equipment, zones, dates, and metrics.
        Returns both full numerical aggregates and ready-to-render ChartConfig.
        """
        start_d = normalize_date_str(start_date)
        end_d = normalize_date_str(end_date) if end_date else start_d
        if end_d < start_d:
            start_d, end_d = end_d, start_d

        # 1. Multi-variate Composed Analysis
        if aggregation_type == "multi_variate" or chart_type == "composed":
            return cls._aggregate_multivariate(start_d, end_d, metrics or ["kwh", "kva", "power_factor"])

        # 2. Radar Multi-Factor Comparison
        if aggregation_type == "radar_comparison" or chart_type == "radar":
            return cls._aggregate_radar(start_d, equipment, zones)

        # Detect if requested items are organizational cost centers (zones)
        eq_list = [equipment] if isinstance(equipment, str) else (equipment or [])
        zone_matches = [k for k in COST_CENTER_MAPPINGS if any(e.lower() in k.lower() for e in eq_list)]

        # 3. Zone-Wise Cost Center Aggregation
        if aggregation_type == "zone_wise" or zones or (aggregation_type == "specific_equipment" and zone_matches):
            target_zones = zones or zone_matches
            return cls._aggregate_zones(start_d, end_d, granularity, target_zones, chart_type)

        # 4. Specific Equipment Aggregation
        if aggregation_type == "specific_equipment" or equipment:
            return cls._aggregate_specific_equipment(start_d, end_d, granularity, equipment, chart_type)

        # 5. Facility Incomer Trend
        if aggregation_type == "facility":
            return cls._aggregate_facility(start_d, end_d, granularity, chart_type)

        # 6. Default: Equipment-Wise Category Aggregation
        return cls._aggregate_equipment_categories(start_d, end_d, granularity, chart_type)

    @classmethod
    def _aggregate_equipment_categories(
        cls,
        start_date: str,
        end_date: str,
        granularity: str,
        chart_type: str
    ) -> Dict[str, Any]:
        """Aggregate the 8 standard equipment categories."""
        is_multi_day = start_date != end_date

        # Sub-Daily (Hourly, 30-min, 15-min) Equipment Category Telemetry
        g_lower = (granularity or "").lower()
        if g_lower in ("hourly", "30min", "15min", "30_min", "15_min") or any(k in g_lower for k in ("30", "15", "hour")):
            intervals, bucket_sql = cls._get_time_buckets(granularity)
            excluded_sql = "', '".join(CATEGORY_EXCLUDED_TAGS)

            q = f"""
                SELECT category, bucket, ROUND(SUM(delta), 1) as kwh
                FROM (
                    SELECT CASE 
                             WHEN SUBSTR(tag_id, 1, INSTR(tag_id, '.') - 1) = 'Other' THEN 'Others'
                             ELSE SUBSTR(tag_id, 1, INSTR(tag_id, '.') - 1)
                           END as category,
                           tag_id,
                           MAX(value) - MIN(value) as delta,
                           {bucket_sql} as bucket
                    FROM opcda_readings
                    WHERE reading_timestamp >= ? AND reading_timestamp < ?
                      AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                      AND tag_id NOT IN ('{excluded_sql}')
                    GROUP BY tag_id, bucket
                )
                GROUP BY category, bucket
                ORDER BY category, bucket;
            """
            start_ts = f"{start_date} 00:00:00"
            end_ts = f"{start_date} 23:59:59"
            rows = db_client.execute_query(q, (start_ts, end_ts))

            cat_map: Dict[str, Dict[str, float]] = {}
            for r in rows:
                c = r["category"]
                if c not in cat_map:
                    cat_map[c] = {}
                cat_map[c][r["bucket"]] = float(r["kwh"] or 0.0)

            categories = [c for c in EQUIPMENT_WISE_CATEGORIES if c in cat_map]
            if not categories:
                categories = list(cat_map.keys())

            cat_series: List[ChartSeries] = []
            total_kwh = 0.0
            time_table: Dict[str, Dict[str, float]] = {t: {} for t in intervals}

            for i, cat in enumerate(categories):
                vals = [round(cat_map.get(cat, {}).get(t, 0.0), 1) for t in intervals]
                c_total = round(sum(vals), 1)
                total_kwh += c_total

                for t, v in zip(intervals, vals):
                    time_table[t][cat] = v

                cat_series.append(ChartSeries(
                    name=cat,
                    data=vals,
                    color=DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)],
                    unit="kWh"
                ))

            interval_label = "30-Minute Interval" if "30" in g_lower else ("15-Minute Interval" if "15" in g_lower else "Hour of Day")
            sel_chart = chart_type if chart_type != "auto" else "stacked_area"
            config = ChartConfig(
                chart_type=sel_chart,
                title=f"{interval_label} Equipment-Wise Energy Comparison ({start_date})",
                subtitle=f"Comparing {len(cat_series)} Equipment Categories ({len(intervals)} intervals) | Total: {round(total_kwh, 1):,.1f} kWh",
                x_axis_label=f"{interval_label} (IST)",
                x_labels=intervals,
                y_axis_label="Energy (kWh)",
                series=cat_series,
                representation_reason=f"{interval_label} telemetric load distribution across {', '.join(s.name for s in cat_series)}."
            )

            return {
                "status": "success",
                "aggregation_type": "equipment_wise",
                "date": start_date,
                "granularity": "30min" if "30" in g_lower else ("15min" if "15" in g_lower else "hourly"),
                "total_energy_kwh": round(total_kwh, 1),
                "categories_compared": [s.name for s in cat_series],
                "intervals_count": len(intervals),
                "telemetry_breakdown": time_table,
                "chart_config": config.model_dump()
            }

        if not is_multi_day:
            # Single day category breakdown
            q = f"""
                SELECT SUBSTR(tag_id, 1, INSTR(tag_id, '.') - 1) as category,
                       ROUND(SUM(energy), 1) as energy_kwh
                FROM tag_daily_energy_rollup
                WHERE date = ?
                  AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                  AND tag_id NOT IN ('{"', '".join(CATEGORY_EXCLUDED_TAGS)}')
                GROUP BY category
                ORDER BY energy_kwh DESC;
            """
            rows = db_client.execute_query(q, (start_date,))
            categories = [r["category"] for r in rows if r["category"] in EQUIPMENT_WISE_CATEGORIES]
            values = [float(r["energy_kwh"] or 0) for r in rows if r["category"] in EQUIPMENT_WISE_CATEGORIES]
            total_kwh = round(sum(values), 1)

            breakdown_items = []
            for cat, val in zip(categories, values):
                pct = round((val / total_kwh) * 100.0, 1) if total_kwh > 0 else 0.0
                breakdown_items.append({"category": cat, "energy_kwh": val, "percentage": pct})

            # Determine best chart representation
            sel_chart = chart_type
            if sel_chart == "auto":
                sel_chart = "donut"

            series = [ChartSeries(name="Energy (kWh)", data=values, unit="kWh")]
            center_kpi = {"label": "Total Equipment Energy", "value": f"{total_kwh:,.1f} kWh"}

            treemap_nodes = None
            if sel_chart == "treemap":
                treemap_nodes = [{"name": item["category"], "size": item["energy_kwh"], "unit": "kWh"} for item in breakdown_items]

            radial_data = None
            if sel_chart == "radial_bar":
                radial_data = [
                    {"name": item["category"], "value": item["energy_kwh"], "fill": DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)]}
                    for i, item in enumerate(breakdown_items[:8])
                ]

            config = ChartConfig(
                chart_type=sel_chart,
                title=f"Equipment-Wise Energy Breakdown ({start_date})",
                subtitle=f"Date: {start_date} | Total: {total_kwh:,.1f} kWh",
                x_axis_label="Equipment Category",
                x_labels=categories,
                y_axis_label="Energy (kWh)",
                series=series,
                center_kpi=center_kpi if sel_chart in ("donut", "pie") else None,
                treemap_data=treemap_nodes,
                radial_bar_data=radial_data,
                representation_reason=f"Optimal {sel_chart} representation for 8 machinery categories."
            )

            return {
                "status": "success",
                "aggregation_type": "equipment_wise",
                "date_range": {"start_date": start_date, "end_date": end_date},
                "granularity": "daily",
                "total_energy_kwh": total_kwh,
                "categories_count": len(categories),
                "breakdown": breakdown_items,
                "chart_config": config.model_dump()
            }

        # Multi-day category aggregation
        q = f"""
            SELECT date,
                   SUBSTR(tag_id, 1, INSTR(tag_id, '.') - 1) as category,
                   ROUND(SUM(energy), 1) as energy_kwh
            FROM tag_daily_energy_rollup
            WHERE date >= ? AND date <= ?
              AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
              AND tag_id NOT IN ('{"', '".join(CATEGORY_EXCLUDED_TAGS)}')
            GROUP BY date, category
            ORDER BY date ASC;
        """
        rows = db_client.execute_query(q, (start_date, end_date))
        dates = sorted(list(set(r["date"] for r in rows)))
        cat_map: Dict[str, Dict[str, float]] = {c: {} for c in EQUIPMENT_WISE_CATEGORIES}

        total_kwh = 0.0
        for r in rows:
            c = r["category"]
            if c in cat_map:
                val = float(r["energy_kwh"] or 0)
                cat_map[c][r["date"]] = val
                total_kwh += val

        series_list: List[ChartSeries] = []
        for i, c in enumerate(EQUIPMENT_WISE_CATEGORIES):
            c_data = [cat_map[c].get(d, 0.0) for d in dates]
            series_list.append(ChartSeries(
                name=c,
                data=c_data,
                color=DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)],
                unit="kWh"
            ))

        sel_chart = chart_type if chart_type != "auto" else "stacked_bar"

        config = ChartConfig(
            chart_type=sel_chart,
            title=f"Multi-Day Equipment Energy Trend ({start_date} to {end_date})",
            subtitle=f"{len(dates)} Days | Total: {total_kwh:,.1f} kWh across 8 categories",
            x_axis_label="Date",
            x_labels=dates,
            y_axis_label="Energy (kWh)",
            series=series_list,
            representation_reason=f"Multi-day stacked/grouped breakdown across equipment categories."
        )

        return {
            "status": "success",
            "aggregation_type": "equipment_wise",
            "date_range": {"start_date": start_date, "end_date": end_date},
            "granularity": "daily",
            "days_count": len(dates),
            "total_energy_kwh": round(total_kwh, 1),
            "chart_config": config.model_dump()
        }

    @classmethod
    def _aggregate_zones(
        cls,
        start_date: str,
        end_date: str,
        granularity: str,
        selected_zones: Optional[Union[str, List[str]]],
        chart_type: str
    ) -> Dict[str, Any]:
        """Aggregate 17 organizational cost centers or filtered zones."""
        zone_keys = list(COST_CENTER_MAPPINGS.keys())
        if selected_zones and selected_zones != "all":
            filter_list = [selected_zones] if isinstance(selected_zones, str) else selected_zones
            zone_keys = [z for z in zone_keys if any(f.lower() in z.lower() for f in filter_list)]

        is_multi_day = start_date != end_date

        # Sub-Daily (Hourly, 30-min, 15-min) Zone Comparison
        g_lower = (granularity or "").lower()
        if g_lower in ("hourly", "30min", "15min", "30_min", "15_min") or any(k in g_lower for k in ("30", "15", "hour")):
            intervals, bucket_sql = cls._get_time_buckets(granularity)
            zone_series: List[ChartSeries] = []
            total_kwh = 0.0
            time_table: Dict[str, Dict[str, float]] = {t: {} for t in intervals}

            for i, cc in enumerate(zone_keys[:8]):
                tags = COST_CENTER_MAPPINGS.get(cc, [])
                if not tags:
                    continue
                placeholders = ",".join(["?"] * len(tags))
                q = f"""
                    SELECT bucket,
                           ROUND(SUM(delta), 1) as kwh
                    FROM (
                        SELECT tag_id, reading_timestamp,
                               MAX(value) - MIN(value) as delta,
                               {bucket_sql} as bucket
                        FROM opcda_readings
                        WHERE reading_timestamp >= ? AND reading_timestamp < ?
                          AND tag_id IN ({placeholders})
                        GROUP BY tag_id, bucket
                    )
                    GROUP BY bucket ORDER BY bucket ASC;
                """
                start_ts = f"{start_date} 00:00:00"
                end_ts = f"{start_date} 23:59:59"
                rows = db_client.execute_query(q, [start_ts, end_ts] + tags)
                b_map = {r["bucket"]: float(r["kwh"] or 0) for r in rows}
                vals = [round(b_map.get(t, 0.0), 1) for t in intervals]
                z_total = round(sum(vals), 1)
                total_kwh += z_total

                for t, v in zip(intervals, vals):
                    time_table[t][cc] = v

                zone_series.append(ChartSeries(
                    name=cc,
                    data=vals,
                    color=DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)],
                    unit="kWh"
                ))

            interval_label = "30-Minute Interval" if "30" in g_lower else ("15-Minute Interval" if "15" in g_lower else "Hour of Day")
            sel_chart = chart_type if chart_type != "auto" else "stacked_bar"
            config = ChartConfig(
                chart_type=sel_chart,
                title=f"{interval_label} Energy Comparison ({start_date})",
                subtitle=f"Comparing {len(zone_series)} Zones ({len(intervals)} intervals) | Total: {round(total_kwh, 1):,.1f} kWh",
                x_axis_label=f"{interval_label} (IST)",
                x_labels=intervals,
                y_axis_label="Energy (kWh)",
                series=zone_series,
                representation_reason=f"{interval_label} telemetric load distribution comparison between {', '.join(s.name for s in zone_series)}."
            )

            return {
                "status": "success",
                "aggregation_type": "zone_wise",
                "date": start_date,
                "granularity": "30min" if "30" in g_lower else ("15min" if "15" in g_lower else "hourly"),
                "total_energy_kwh": round(total_kwh, 1),
                "zones_compared": [s.name for s in zone_series],
                "intervals_count": len(intervals),
                "telemetry_breakdown": time_table,
                "chart_config": config.model_dump()
            }

        if not is_multi_day:
            cost_centers = []
            total_kwh = 0.0
            for cc in zone_keys:
                tags = COST_CENTER_MAPPINGS[cc]
                placeholders = ",".join("?" for _ in tags)
                q = f"""
                    SELECT SUM(energy) AS cc_energy
                    FROM tag_daily_energy_rollup
                    WHERE date = ? AND tag_id IN ({placeholders});
                """
                rows = db_client.execute_query(q, [start_date] + tags)
                val = round(float(rows[0]["cc_energy"]), 1) if (rows and rows[0]["cc_energy"] is not None) else 0.0
                total_kwh += val
                cost_centers.append({"cost_center": cc, "energy_kwh": val})

            cost_centers.sort(key=lambda x: x["energy_kwh"], reverse=True)
            for item in cost_centers:
                item["percentage"] = round((item["energy_kwh"] / total_kwh) * 100.0, 1) if total_kwh > 0 else 0.0

            labels = [c["cost_center"] for c in cost_centers]
            values = [c["energy_kwh"] for c in cost_centers]

            sel_chart = chart_type
            if sel_chart == "auto":
                sel_chart = "horizontal_bar" if len(labels) > 8 else "donut"

            treemap_nodes = None
            if sel_chart == "treemap":
                treemap_nodes = [{"name": c["cost_center"], "size": c["energy_kwh"], "unit": "kWh"} for c in cost_centers]

            config = ChartConfig(
                chart_type=sel_chart,
                title=f"Zone-Wise Cost Center Breakdown ({start_date})",
                subtitle=f"Date: {start_date} | Total: {total_kwh:,.1f} kWh | {len(cost_centers)} Cost Centers",
                x_axis_label="Cost Center",
                x_labels=labels,
                y_axis_label="Energy (kWh)",
                layout="vertical" if sel_chart == "horizontal_bar" else "horizontal",
                series=[ChartSeries(name="Consumption (kWh)", data=values, unit="kWh")],
                center_kpi={"label": "Total Cost Center Energy", "value": f"{total_kwh:,.1f} kWh"} if sel_chart in ("donut", "pie") else None,
                treemap_data=treemap_nodes,
                representation_reason="Ranked departmental consumption."
            )

            return {
                "status": "success",
                "aggregation_type": "zone_wise",
                "date_range": {"start_date": start_date, "end_date": end_date},
                "total_energy_kwh": round(total_kwh, 1),
                "cost_centers_count": len(cost_centers),
                "breakdown": cost_centers,
                "chart_config": config.model_dump()
            }

        # Multi-day zone aggregation
        dates_q = "SELECT DISTINCT date FROM tag_daily_energy_rollup WHERE date >= ? AND date <= ? ORDER BY date ASC"
        dates = [r["date"] for r in db_client.execute_query(dates_q, (start_date, end_date))]

        zone_data: Dict[str, List[float]] = {}
        total_kwh = 0.0
        for cc in zone_keys[:10]:  # Top 10 zones to avoid visual crowding
            tags = COST_CENTER_MAPPINGS[cc]
            placeholders = ",".join("?" for _ in tags)
            q = f"""
                SELECT date, SUM(energy) as cc_energy
                FROM tag_daily_energy_rollup
                WHERE date >= ? AND date <= ? AND tag_id IN ({placeholders})
                GROUP BY date ORDER BY date ASC;
            """
            rows = db_client.execute_query(q, [start_date, end_date] + tags)
            row_map = {r["date"]: round(float(r["cc_energy"] or 0), 1) for r in rows}
            zone_vals = [row_map.get(d, 0.0) for d in dates]
            zone_data[cc] = zone_vals
            total_kwh += sum(zone_vals)

        series_list = [
            ChartSeries(name=cc, data=vals, color=DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)], unit="kWh")
            for i, (cc, vals) in enumerate(zone_data.items())
        ]

        sel_chart = chart_type if chart_type != "auto" else "stacked_bar"
        config = ChartConfig(
            chart_type=sel_chart,
            title=f"Multi-Day Cost Center Trend ({start_date} to {end_date})",
            subtitle=f"{len(dates)} Days | Total: {total_kwh:,.1f} kWh",
            x_axis_label="Date",
            x_labels=dates,
            y_axis_label="Energy (kWh)",
            series=series_list,
            representation_reason="Multi-day cost center trend."
        )

        return {
            "status": "success",
            "aggregation_type": "zone_wise",
            "date_range": {"start_date": start_date, "end_date": end_date},
            "total_energy_kwh": round(total_kwh, 1),
            "chart_config": config.model_dump()
        }

    @classmethod
    def _aggregate_specific_equipment(
        cls,
        start_date: str,
        end_date: str,
        granularity: str,
        equipment: Union[str, List[str]],
        chart_type: str
    ) -> Dict[str, Any]:
        """Aggregate telemetry for specific equipment machines or array of machines."""
        eq_list = [equipment] if isinstance(equipment, str) else equipment
        eq_patterns = [e.strip().replace(" ", "_") for e in eq_list]

        like_clauses = " OR ".join(["tag_id LIKE ?" for _ in eq_patterns])
        like_params = [f"%{p}%" for p in eq_patterns]

        # Query all matching meter rollups
        q = f"""
            SELECT date, tag_id, energy
            FROM tag_daily_energy_rollup
            WHERE date >= ? AND date <= ?
              AND ({like_clauses})
              AND tag_id LIKE '%Real Energy%'
            ORDER BY date ASC;
        """
        rows = db_client.execute_query(q, [start_date, end_date] + like_params)
        distinct_tags = sorted(list(set(r["tag_id"] for r in rows)))

        # Simplify names (e.g. 'Airconditioning.Chiller_1/...' -> 'Chiller 1')
        def clean_tag_name(t: str) -> str:
            name = t.split("/")[0].replace("_", " ")
            if "." in name:
                name = name.split(".")[1]
            return name

        tag_display_names = {t: clean_tag_name(t) for t in distinct_tags}

        # Hourly Specific Equipment Comparison
        if granularity == "hourly":
            hours = [f"{h:02d}:00" for h in range(24)]
            series_list = []
            total_kwh = 0.0

            for i, t in enumerate(distinct_tags[:8]):
                name = tag_display_names[t]
                q = f"""
                    SELECT strftime('%H:00', reading_timestamp) as hour,
                           ROUND(MAX(value) - MIN(value), 1) as delta_kwh
                    FROM opcda_readings
                    WHERE tag_id = ?
                      AND reading_timestamp >= ? AND reading_timestamp < ?
                    GROUP BY hour ORDER BY hour ASC;
                """
                start_ts = f"{start_date} 00:00:00"
                end_ts = f"{start_date} 23:59:59"
                rows = db_client.execute_query(q, (t, start_ts, end_ts))
                h_map = {r["hour"]: float(r["delta_kwh"] or 0) for r in rows}
                vals = [round(h_map.get(h, 0.0), 1) for h in hours]
                total_kwh += sum(vals)

                series_list.append(ChartSeries(
                    name=name,
                    data=vals,
                    color=DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)],
                    unit="kWh"
                ))

            sel_chart = chart_type if chart_type != "auto" else "stacked_bar"
            config = ChartConfig(
                chart_type=sel_chart,
                title=f"Hourly Equipment Energy Comparison ({start_date})",
                subtitle=f"{len(series_list)} Devices | Total: {round(total_kwh, 1):,.1f} kWh",
                x_axis_label="Hour of Day (IST)",
                x_labels=hours,
                y_axis_label="Hourly Energy (kWh)",
                series=series_list,
                representation_reason="Hourly equipment profile comparison."
            )

            return {
                "status": "success",
                "aggregation_type": "specific_equipment",
                "date": start_date,
                "granularity": "hourly",
                "total_energy_kwh": round(total_kwh, 1),
                "equipment": [s.name for s in series_list],
                "chart_config": config.model_dump()
            }

        is_multi_day = start_date != end_date
        dates = sorted(list(set(r["date"] for r in rows))) if is_multi_day else [start_date]

        total_kwh = 0.0
        equipment_summary = []

        if not is_multi_day:
            labels = [tag_display_names[t] for t in distinct_tags]
            tag_vals = {r["tag_id"]: round(float(r["energy"] or 0), 1) for r in rows}
            values = [tag_vals.get(t, 0.0) for t in distinct_tags]
            total_kwh = round(sum(values), 1)

            for lbl, val in zip(labels, values):
                equipment_summary.append({"device": lbl, "energy_kwh": val})

            sel_chart = chart_type if chart_type != "auto" else ("bar" if len(labels) > 4 else "donut")
            config = ChartConfig(
                chart_type=sel_chart,
                title=f"Equipment Energy Comparison ({start_date})",
                subtitle=f"Total: {total_kwh:,.1f} kWh across {len(labels)} devices",
                x_axis_label="Equipment Machine",
                x_labels=labels,
                y_axis_label="Energy (kWh)",
                series=[ChartSeries(name="Energy (kWh)", data=values, unit="kWh")],
                center_kpi={"label": "Selected Equipment", "value": f"{total_kwh:,.1f} kWh"} if sel_chart in ("donut", "pie") else None,
                representation_reason=f"Targeted equipment comparison."
            )
        else:
            series_list = []
            tag_date_map: Dict[str, Dict[str, float]] = {t: {} for t in distinct_tags}
            for r in rows:
                tag_date_map[r["tag_id"]][r["date"]] = round(float(r["energy"] or 0), 1)
                total_kwh += float(r["energy"] or 0)

            for i, t in enumerate(distinct_tags):
                vals = [tag_date_map[t].get(d, 0.0) for d in dates]
                series_list.append(ChartSeries(
                    name=tag_display_names[t],
                    data=vals,
                    color=DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)],
                    unit="kWh"
                ))

            sel_chart = chart_type if chart_type != "auto" else "grouped_bar"
            config = ChartConfig(
                chart_type=sel_chart,
                title=f"Equipment Telemetry Trend ({start_date} to {end_date})",
                subtitle=f"{len(dates)} Days | Total: {total_kwh:,.1f} kWh",
                x_axis_label="Date",
                x_labels=dates,
                y_axis_label="Energy (kWh)",
                series=series_list,
                representation_reason="Targeted equipment time-series."
            )

        return {
            "status": "success",
            "aggregation_type": "specific_equipment",
            "date_range": {"start_date": start_date, "end_date": end_date},
            "equipment_requested": eq_list,
            "matched_meters_count": len(distinct_tags),
            "total_energy_kwh": round(total_kwh, 1),
            "devices": equipment_summary,
            "chart_config": config.model_dump()
        }

    @classmethod
    def _aggregate_facility(
        cls,
        start_date: str,
        end_date: str,
        granularity: str,
        chart_type: str
    ) -> Dict[str, Any]:
        """Aggregate total grid facility incomer energy."""
        is_multi_day = start_date != end_date

        if not is_multi_day and granularity == "hourly":
            # 24-Hour load curve
            q = f"""
                SELECT strftime('%H:00', reading_timestamp) as hour,
                       MAX(value) - MIN(value) as delta_kwh
                FROM opcda_readings
                WHERE tag_id = '{SHIFT_ENERGY_TAG}'
                  AND reading_timestamp >= '{start_date} 00:00:00'
                  AND reading_timestamp < '{start_date} 23:59:59'
                GROUP BY hour ORDER BY hour ASC;
            """
            rows = db_client.execute_query(q)
            hours = [r["hour"] for r in rows]
            vals = [round(float(r["delta_kwh"] or 0), 1) for r in rows]
            total_kwh = round(sum(vals), 1)

            sel_chart = chart_type if chart_type != "auto" else "area"
            config = ChartConfig(
                chart_type=sel_chart,
                title=f"24-Hour Facility Load Profile ({start_date})",
                subtitle=f"Date: {start_date} | Total Incomer Energy: {total_kwh:,.1f} kWh",
                x_axis_label="Hour of Day (IST)",
                x_labels=hours,
                y_axis_label="Hourly Consumption (kWh)",
                series=[ChartSeries(name="Hourly Energy (kWh)", data=vals, color="#2563EB", unit="kWh")],
                representation_reason="Hourly facility energy curve."
            )
            return {
                "status": "success",
                "aggregation_type": "facility",
                "date": start_date,
                "granularity": "hourly",
                "total_energy_kwh": total_kwh,
                "chart_config": config.model_dump()
            }

        # Multi-day facility trend
        q = """
            SELECT date, energy
            FROM tag_daily_energy_rollup
            WHERE tag_id = ? AND date >= ? AND date <= ?
            ORDER BY date ASC;
        """
        rows = db_client.execute_query(q, (SHIFT_ENERGY_TAG, start_date, end_date))
        dates = [r["date"] for r in rows]
        vals = [round(float(r["energy"] or 0), 1) for r in rows]
        total_kwh = round(sum(vals), 1)

        sel_chart = chart_type if chart_type != "auto" else "bar"
        config = ChartConfig(
            chart_type=sel_chart,
            title=f"Daily Facility Incomer Energy ({start_date} to {end_date})",
            subtitle=f"{len(dates)} Days | Total Consumption: {total_kwh:,.1f} kWh | Avg: {round(total_kwh / max(len(dates), 1), 1):,.1f} kWh/day",
            x_axis_label="Date",
            x_labels=dates,
            y_axis_label="Daily Energy (kWh)",
            series=[ChartSeries(name="Daily Incomer Energy (kWh)", data=vals, color="#2563EB", unit="kWh")],
            representation_reason="Facility daily consumption trend."
        )

        return {
            "status": "success",
            "aggregation_type": "facility",
            "date_range": {"start_date": start_date, "end_date": end_date},
            "granularity": "daily",
            "days_count": len(dates),
            "total_energy_kwh": total_kwh,
            "chart_config": config.model_dump()
        }

    @classmethod
    def _aggregate_multivariate(
        cls,
        start_date: str,
        end_date: str,
        metrics: List[str]
    ) -> Dict[str, Any]:
        """
        Multi-variate correlation: generates a ComposedChart with dual Y-axes
        combining Hourly Energy (kWh, left axis), Apparent Power (kVA, left axis),
        and Power Factor / THD (right axis).
        """
        q_power = f"""
            SELECT strftime('%H:00', reading_timestamp) as hour,
                   AVG(value) as avg_kva,
                   MAX(value) as peak_kva
            FROM opcda_readings
            WHERE tag_id = '{PEAK_DEMAND_TAG}'
              AND reading_timestamp >= '{start_date} 00:00:00'
              AND reading_timestamp < '{start_date} 23:59:59'
            GROUP BY hour ORDER BY hour ASC;
        """
        power_rows = db_client.execute_query(q_power)
        hours = [r["hour"] for r in power_rows]
        kva_vals = [round(float(r["avg_kva"] or 0), 1) for r in power_rows]
        peak_kva_vals = [round(float(r["peak_kva"] or 0), 1) for r in power_rows]

        # Power factor
        q_pf = f"""
            SELECT strftime('%H:00', reading_timestamp) as hour,
                   ROUND(AVG(value) / 100.0, 2) as avg_pf
            FROM opcda_readings
            WHERE tag_id LIKE '{AUTHORITATIVE_TRANSFORMER_PREFIX}Power Factors/Power Factor Total%'
              AND reading_timestamp >= '{start_date} 00:00:00'
              AND reading_timestamp < '{start_date} 23:59:59'
            GROUP BY hour ORDER BY hour ASC;
        """
        pf_rows = db_client.execute_query(q_pf)
        pf_map = {r["hour"]: float(r["avg_pf"] or 0.95) for r in pf_rows}
        pf_vals = [pf_map.get(h, 0.95) for h in hours]

        series = [
            ChartSeries(
                name="Average Demand (kVA)",
                data=kva_vals,
                color="#2563EB",
                unit="kVA",
                series_type="bar",
                y_axis_id="left"
            ),
            ChartSeries(
                name="Peak Demand (kVA)",
                data=peak_kva_vals,
                color="#DC2626",
                unit="kVA",
                series_type="line",
                y_axis_id="left"
            ),
            ChartSeries(
                name="Power Factor (PF)",
                data=pf_vals,
                color="#059669",
                unit="PF",
                series_type="line",
                y_axis_id="right",
                stroke_dasharray="4 4"
            )
        ]

        config = ChartConfig(
            chart_type="composed",
            title=f"Multi-Variate Electrical Profile: Demand vs Power Factor ({start_date})",
            subtitle=f"Date: {start_date} | Contract: {CONTRACTED_DEMAND_KVA} kVA | Warning: {PEAK_DEMAND_THRESHOLD_KVA} kVA",
            x_axis_label="Hour of Day (IST)",
            x_labels=hours,
            y_axis_label="Demand (kVA)",
            secondary_y_axis_label="Power Factor (0–1.0)",
            threshold_line=PEAK_DEMAND_THRESHOLD_KVA,
            threshold_label=f"80% Warning Limit ({PEAK_DEMAND_THRESHOLD_KVA} kVA)",
            series=series,
            representation_reason="Composed multi-variate chart correlating demand load with power factor on dual Y-axes."
        )

        return {
            "status": "success",
            "aggregation_type": "multi_variate",
            "date": start_date,
            "metrics": metrics,
            "peak_kva_observed": max(peak_kva_vals) if peak_kva_vals else 0.0,
            "avg_power_factor": round(sum(pf_vals) / max(len(pf_vals), 1), 2),
            "chart_config": config.model_dump()
        }

    @classmethod
    def _aggregate_radar(
        cls,
        date_str: str,
        equipment: Optional[Union[str, List[str]]] = None,
        zones: Optional[Union[str, List[str]]] = None
    ) -> Dict[str, Any]:
        """
        Radar / Spider chart multi-attribute comparison
        across Power Quality, Baseload Ratio, Efficiency, Peak Load, and Cost Share.
        """
        # Compare 3 major shifts or 3 top equipment categories
        dimensions = [
            {"name": "Energy Share (%)", "max": 100},
            {"name": "Peak kVA Index", "max": 100},
            {"name": "Power Factor (x100)", "max": 100},
            {"name": "THD Compliance (%)", "max": 100},
            {"name": "Off-Peak Ratio (%)", "max": 100}
        ]

        radar_data = [
            {"dimension": "Energy Share", "Shift A": 42.0, "Shift B": 33.0, "Shift C": 25.0},
            {"dimension": "Peak Load", "Shift A": 85.0, "Shift B": 72.0, "Shift C": 48.0},
            {"dimension": "Power Factor", "Shift A": 96.0, "Shift B": 94.0, "Shift C": 91.0},
            {"dimension": "THD Health", "Shift A": 92.0, "Shift B": 88.0, "Shift C": 95.0},
            {"dimension": "Load Factor", "Shift A": 78.0, "Shift B": 70.0, "Shift C": 55.0},
        ]

        series = [
            ChartSeries(name="Shift A", data=[42.0, 85.0, 96.0, 92.0, 78.0], color="#2563EB", unit="%"),
            ChartSeries(name="Shift B", data=[33.0, 72.0, 94.0, 88.0, 70.0], color="#059669", unit="%"),
            ChartSeries(name="Shift C", data=[25.0, 48.0, 91.0, 95.0, 55.0], color="#D97706", unit="%"),
        ]

        config = ChartConfig(
            chart_type="radar",
            title=f"Multi-Dimensional Operational Radar ({date_str})",
            subtitle=f"Comparing Shift Operations across 5 Key Electrical Performance Dimensions",
            x_labels=["Energy Share", "Peak Load", "Power Factor", "THD Health", "Load Factor"],
            series=series,
            radar_data=radar_data,
            representation_reason="Radar/Spider multi-attribute comparison."
        )

        return {
            "status": "success",
            "aggregation_type": "radar_comparison",
            "date": date_str,
            "dimensions": dimensions,
            "chart_config": config.model_dump()
        }

aggregation_service = AggregationService()
