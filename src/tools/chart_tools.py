"""
Optimized Chart & Visualization Tools (Consolidated)

3 tools replacing 7:
1. create_chart - Primary unified tool for all energy/zone/equipment charts
2. create_power_quality_chart - THD, demand profiles with threshold lines
3. create_specialized_chart - Gauge, scatter plots, heatmaps

All tools return both numerical data AND ready-to-render ChartConfig payloads.
"""

import datetime
from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import tool

from src.core.config import settings
from src.core.constants import (
    CONTRACTED_DEMAND_KVA,
    PEAK_DEMAND_THRESHOLD_KVA,
    PEAK_DEMAND_TAG,
    STEAM_FLOW_RATE_TAG,
    STEAM_PRESSURE_TAG,
    VOLTAGE_THD_TAGS,
    CURRENT_THD_TAGS,
    SHIFT_ENERGY_TAG,
)
from src.core.normalizers import normalize_date_str
from src.db.client import db_client
from src.schemas.charts import (
    ChartConfig,
    ChartSeries,
    GaugeConfig,
    HeatmapMatrix,
    ScatterPoint,
    ScatterSeries,
)
from src.services.aggregation_service import aggregation_service
from src.services.telemetry import facility_telemetry


# ==============================================================================
# Helper Functions
# ==============================================================================

def _validate_date(date_str: str) -> tuple[bool, str, str]:
    """Validate and normalize date string. Returns (is_valid, normalized_date, error_msg)."""
    try:
        normalized = normalize_date_str(date_str)
        return True, normalized, ""
    except Exception as e:
        return False, "", f"Invalid date: {date_str}. Use YYYY-MM-DD format. Error: {e}"


def _safe_call(func, *args, **kwargs) -> Dict[str, Any]:
    """Wrap service calls with error handling."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        return {"error": str(e), "success": False}


# ==============================================================================
# Tool 1: Primary Unified Chart Tool
# ==============================================================================

@tool
def create_chart(
    chart_for: Literal[
        "equipment",
        "zones",
        "facility",
        "solar",
        "shift",
        "tariff",
        "specific_equipment"
    ],
    start_date: str = "yesterday",
    end_date: Optional[str] = None,
    granularity: Literal["daily", "hourly", "30min", "15min", "shift_wise"] = "daily",
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
        "treemap",
        "radial_bar"
    ] = "auto",
    filter_items: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    🎯 PRIMARY CHART TOOL — Use this for ALL energy visualization requests.
    Returns BOTH numerical breakdown AND interactive chart configuration.

    CHART_FOR OPTIONS:
    - 'equipment': 8 categories (Lighting, Molding, Compressor, Airconditioning, Dust_Collector, Paintshop, Production_Power, Others)
    - 'zones': 17 cost centers (General Admin, AG Assy, AG Painting, PA Assy, etc.)
    - 'facility': Total grid incomer load curve
    - 'solar': Rooftop 100kW solar generation
    - 'shift': Shift A (08:00-17:00), B (17:00-00:40), C (00:40-08:00) breakdown
    - 'tariff': Off-Peak, Normal, Peak TOD band distribution
    - 'specific_equipment': Filter to specific machines (use filter_items param)

    GRANULARITY OPTIONS:
    - 'daily' (default): Daily totals
    - 'hourly': 24-hour intervals (00:00-23:00)
    - '30min': 48 intervals
    - '15min': 96 intervals
    - 'shift_wise': Shift A/B/C breakdown

    CHART_TYPE OPTIONS:
    - 'auto' (default): Auto-select best chart type
    - 'stacked_bar': Categories stacked, shows composition
    - 'grouped_bar': Categories side-by-side, shows comparison
    - 'line' / 'area': Time-series trends
    - 'donut' / 'pie': Part-to-whole proportions (≤8 categories)
    - 'horizontal_bar': Ranked comparison (>8 items)
    - 'treemap': Hierarchical size comparison

    FILTER_ITEMS:
    - For 'specific_equipment': List of equipment names to filter
    - For 'zones': List of cost center names to filter (None = all 17)

    EXAMPLES:
    - Equipment breakdown: chart_for='equipment', start_date='2026-10-21'
    - Hourly zone comparison: chart_for='zones', granularity='hourly', chart_type='stacked_bar'
    - Solar profile: chart_for='solar', granularity='hourly'
    - Shift distribution: chart_for='shift', chart_type='donut'
    - Specific zones: chart_for='zones', filter_items=['AG Assy', 'AG Painting']
    """
    # Validate dates
    valid, start_d, err = _validate_date(start_date)
    if not valid:
        return {"error": err}

    end_d = None
    if end_date:
        valid, end_d, err = _validate_date(end_date)
        if not valid:
            return {"error": err}

    # Map chart_for to aggregation_type
    aggregation_map = {
        "equipment": "equipment_wise",
        "zones": "zone_wise",
        "facility": "facility",
        "solar": "solar",
        "shift": "equipment_wise",  # Uses shift_wise granularity
        "tariff": "tariff_bands",
        "specific_equipment": "specific_equipment",
    }

    agg_type = aggregation_map.get(chart_for, "equipment_wise")

    # Handle shift breakdown
    if chart_for == "shift":
        granularity = "shift_wise"

    # Handle tariff bands (special case)
    if chart_for == "tariff":
        from src.services.tariff_service import TariffService
        tariff_data = TariffService.calculate_daily_cost(start_d)
        bands = tariff_data.get("band_summary", {})
        total_kwh = tariff_data.get("true_daily_kwh", 0.0)

        labels = list(bands.keys())
        values = [b["kwh"] for b in bands.values()]
        costs = [b["cost"] for b in bands.values()]

        selected_type = chart_type if chart_type != "auto" else "donut"
        series = [ChartSeries(name="Energy (kWh)", data=values, unit="kWh")]

        config = ChartConfig(
            chart_type=selected_type,
            title=f"TOD Tariff Band Energy Distribution ({start_d})",
            subtitle=f"Total: {total_kwh:,.1f} kWh | Total Cost: ₹{tariff_data.get('total_cost', 0):,.2f}",
            x_axis_label="Tariff Band",
            x_labels=labels,
            y_axis_label="Energy (kWh)",
            series=series,
            center_kpi={"label": "Total Energy", "value": f"{total_kwh:,.1f} kWh"} if selected_type in ("donut", "pie") else None,
            representation_reason="TOD tariff band distribution showing Off-Peak, Normal, and Peak energy share."
        )

        return {
            "status": "success",
            "chart_for": "tariff",
            "date": start_d,
            "total_kwh": total_kwh,
            "total_cost": tariff_data.get("total_cost", 0),
            "bands": [{"band": k, "kwh": v["kwh"], "cost": v["cost"]} for k, v in bands.items()],
            "chart_config": config.model_dump()
        }

    # Call aggregation service for all other chart types
    return _safe_call(
        aggregation_service.aggregate,
        aggregation_type=agg_type,
        start_date=start_d,
        end_date=end_d,
        granularity=granularity,
        equipment=filter_items if chart_for == "specific_equipment" else None,
        zones=filter_items if chart_for == "zones" else None,
        chart_type=chart_type
    )


# ==============================================================================
# Tool 2: Power Quality Charts with Threshold Lines
# ==============================================================================

@tool
def create_power_quality_chart(
    start_date: str,
    metric: Literal["peak_demand", "voltage_thd", "current_thd", "steam_flow", "power_factor"],
    end_date: Optional[str] = None,
    chart_type: Literal["auto", "line", "area", "bar"] = "auto"
) -> Dict[str, Any]:
    """
    Generate power quality time-series charts with compliance threshold lines.

    METRIC OPTIONS:
    - 'peak_demand': Hourly peak kVA with 1180 kVA (80%) threshold line
    - 'voltage_thd': Hourly Voltage THD % with 5% IEEE 519 limit line
    - 'current_thd': Hourly Current THD % with 8% limit line
    - 'steam_flow': Hourly steam flow rate (kg/h) trend
    - 'power_factor': Daily power factor trend with 0.95 compliance threshold

    DATE RANGE:
    - Single day (end_date=None): Hourly profile for that day
    - Multi-day range: Daily trend from start_date to end_date (e.g., last 2 weeks)

    EXAMPLES:
    - Single day peak demand: metric='peak_demand', start_date='2026-10-21'
    - 2-week power factor trend: metric='power_factor', start_date='2026-10-07', end_date='2026-10-21'
    - THD compliance: metric='voltage_thd', start_date='yesterday'
    """
    valid, start_d, err = _validate_date(start_date)
    if not valid:
        return {"error": err}

    # Handle multi-day range
    end_d = None
    is_multi_day = False
    if end_date:
        valid, end_d, err = _validate_date(end_date)
        if not valid:
            return {"error": err}
        is_multi_day = start_d != end_d

    # ─────────────────────────────────────────────────────────────────────────
    # POWER FACTOR TREND (supports multi-day)
    # ─────────────────────────────────────────────────────────────────────────
    if metric == "power_factor":
        if is_multi_day:
            # Multi-day power factor trend
            dt_start = datetime.datetime.strptime(start_d, "%Y-%m-%d").date()
            dt_end = datetime.datetime.strptime(end_d, "%Y-%m-%d").date()
            days_count = (dt_end - dt_start).days + 1

            dates = []
            pf_values = []
            pf_details = []

            for i in range(days_count):
                d = (dt_start + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
                pf_data = facility_telemetry.get_power_factor(d)

                dates.append(d)
                avg_pf = pf_data.get("average_power_factor", 0.0)
                pf_values.append(round(avg_pf, 3) if avg_pf else 0.0)
                pf_details.append({
                    "date": d,
                    "avg_pf": avg_pf,
                    "min_pf": pf_data.get("min_power_factor"),
                    "max_pf": pf_data.get("max_power_factor"),
                    "status": pf_data.get("status", "Unknown")
                })

            # Calculate stats
            valid_pf = [v for v in pf_values if v > 0]
            avg_pf = round(sum(valid_pf) / len(valid_pf), 3) if valid_pf else 0.0
            min_pf = min(valid_pf) if valid_pf else 0.0
            max_pf = max(valid_pf) if valid_pf else 0.0
            below_threshold = sum(1 for v in valid_pf if v < 0.95)

            selected_type = "line" if chart_type == "auto" else chart_type
            config = ChartConfig(
                chart_type=selected_type,
                title=f"Power Factor Trend ({start_d} to {end_d})",
                subtitle=f"Avg: {avg_pf} | Min: {min_pf} | Max: {max_pf} | Days below 0.95: {below_threshold}",
                x_axis_label="Date (IST)",
                x_labels=dates,
                y_axis_label="Power Factor",
                threshold_line=0.95,
                threshold_label="HT-1 Compliance Limit (0.95)",
                series=[ChartSeries(name="Average Power Factor", data=pf_values, color="#059669", unit="PF")],
                representation_reason="Line chart with threshold shows daily power factor compliance trend."
            )
            return {
                "status": "success",
                "metric": "power_factor",
                "date_range": {"start": start_d, "end": end_d},
                "days_count": days_count,
                "average_pf": avg_pf,
                "min_pf": min_pf,
                "max_pf": max_pf,
                "days_below_threshold": below_threshold,
                "daily_breakdown": pf_details,
                "chart_config": config.model_dump()
            }
        else:
            # Single day hourly PF profile
            pf_data = facility_telemetry.get_power_factor(start_d)
            avg_pf = pf_data.get("average_power_factor", 0.0)
            min_pf = pf_data.get("min_power_factor", 0.0)
            max_pf = pf_data.get("max_power_factor", 0.0)

            # For single day, return summary (no hourly PF data typically available)
            config = ChartConfig(
                chart_type="bar",
                title=f"Power Factor Summary — {start_d}",
                subtitle=f"Avg: {avg_pf} | Min: {min_pf} | Max: {max_pf} | Status: {pf_data.get('status', 'Unknown')}",
                x_axis_label="Metric",
                x_labels=["Average PF", "Min PF", "Max PF", "Threshold"],
                y_axis_label="Power Factor",
                threshold_line=0.95,
                threshold_label="HT-1 Compliance (0.95)",
                series=[ChartSeries(name="Power Factor", data=[avg_pf, min_pf, max_pf, 0.95], color="#059669", unit="PF")],
                representation_reason="Bar chart shows power factor metrics against compliance threshold."
            )
            return {
                "status": "success",
                "metric": "power_factor",
                "date": start_d,
                "average_pf": avg_pf,
                "min_pf": min_pf,
                "max_pf": max_pf,
                "phase_breakdown": pf_data.get("phase_breakdown", {}),
                "transformer_pf": pf_data.get("transformer_power_factor", {}),
                "compliance_status": pf_data.get("status", "Unknown"),
                "chart_config": config.model_dump()
            }

    # For other metrics, use single-day logic
    date_str = start_d
    start_ts = f"{date_str} 00:00:00"
    end_ts = f"{date_str} 23:59:59"

    if metric == "peak_demand":
        demand_data = facility_telemetry.get_peak_demand(date_str)
        profile = demand_data.get("hourly_profile", [])
        x_labels = [p["label"] for p in profile]
        y_values = [p["peak_kva"] for p in profile]

        selected_type = "line" if chart_type == "auto" else chart_type
        config = ChartConfig(
            chart_type=selected_type,
            title=f"Hourly Peak Demand Profile (kVA) — {date_str}",
            subtitle=f"Contracted: {CONTRACTED_DEMAND_KVA} kVA | Peak: {demand_data.get('peak_kva')} kVA ({demand_data.get('utilization_percent')}%)",
            x_axis_label="Hour of Day (IST)",
            x_labels=x_labels,
            y_axis_label="Apparent Power (kVA)",
            threshold_line=PEAK_DEMAND_THRESHOLD_KVA,
            threshold_label=f"80% Threshold Limit ({PEAK_DEMAND_THRESHOLD_KVA} kVA)",
            series=[ChartSeries(name="Peak Demand", data=y_values, color="#2563EB", unit="kVA")],
            representation_reason="Line chart with threshold clearly shows demand excursions."
        )
        return {
            "status": "success",
            "metric": "peak_demand",
            "date": date_str,
            "peak_kva": demand_data.get("peak_kva"),
            "utilization_percent": demand_data.get("utilization_percent"),
            "excursion_count": len(demand_data.get("excursions", [])),
            "chart_config": config.model_dump()
        }

    elif metric in ("voltage_thd", "current_thd"):
        is_voltage = (metric == "voltage_thd")
        tag = VOLTAGE_THD_TAGS[3] if is_voltage else CURRENT_THD_TAGS[0]
        limit = 5.0 if is_voltage else 8.0

        q = """
            SELECT formatDateTime(reading_timestamp, '%H:00') AS hour_str, AVG(toFloat64OrNull(value)) AS avg_thd
            FROM opcda_readings
            WHERE tag_id = {tag:String}
              AND reading_timestamp >= parseDateTimeBestEffort({start_ts:String})
              AND reading_timestamp <= parseDateTimeBestEffort({end_ts:String})
              AND toFloat64OrNull(value) > 0
            GROUP BY hour_str ORDER BY hour_str ASC;
        """
        rows = db_client.execute_query(q, {"tag": tag, "start_ts": start_ts, "end_ts": end_ts})

        x_labels = [r["hour_str"] for r in rows]
        y_values = [round(float(r["avg_thd"]), 2) for r in rows]
        max_thd = max(y_values) if y_values else 0.0
        excursions = sum(1 for v in y_values if v > limit)

        name = "Voltage THD (L-N)" if is_voltage else "Current THD (Phase A)"
        config = ChartConfig(
            chart_type="line" if chart_type == "auto" else chart_type,
            title=f"Harmonic Distortion Profile — {name} ({date_str})",
            subtitle=f"Compliance Limit: {limit}% | Max Observed: {max_thd}% | Excursions: {excursions}",
            x_axis_label="Hour of Day (IST)",
            x_labels=x_labels,
            y_axis_label="THD (%)",
            threshold_line=limit,
            threshold_label=f"IEEE 519 Limit ({limit}%)",
            series=[ChartSeries(name=name, data=y_values, color="#D97706", unit="%")],
            representation_reason="Line chart with limit line highlights harmonic excursions."
        )
        return {
            "status": "success",
            "metric": metric,
            "date": date_str,
            "limit_percent": limit,
            "max_observed": max_thd,
            "excursion_hours": excursions,
            "chart_config": config.model_dump()
        }

    elif metric == "steam_flow":
        q = """
            SELECT formatDateTime(reading_timestamp, '%H:00') AS hour_str, AVG(toFloat64OrNull(value)) AS avg_flow
            FROM opcda_readings
            WHERE tag_id = {tag:String}
              AND reading_timestamp >= parseDateTimeBestEffort({start_ts:String})
              AND reading_timestamp <= parseDateTimeBestEffort({end_ts:String})
              AND toFloat64OrNull(value) > 0
            GROUP BY hour_str ORDER BY hour_str ASC;
        """
        rows = db_client.execute_query(q, {"tag": STEAM_FLOW_RATE_TAG, "start_ts": start_ts, "end_ts": end_ts})

        x_labels = [r["hour_str"] for r in rows]
        y_values = [round(float(r["avg_flow"]), 1) for r in rows]
        total_flow = sum(y_values)

        config = ChartConfig(
            chart_type="area" if chart_type == "auto" else chart_type,
            title=f"Steam Flow Rate Profile (kg/h) — {date_str}",
            subtitle=f"Blower Room Steam | Total Flow: {total_flow:,.1f} kg",
            x_axis_label="Hour of Day (IST)",
            x_labels=x_labels,
            y_axis_label="Steam Flow Rate (kg/h)",
            series=[ChartSeries(name="Steam Flow Rate", data=y_values, color="#0891B2", unit="kg/h")],
            representation_reason="Area chart shows thermal utility delivery volume over time."
        )
        return {
            "status": "success",
            "metric": "steam_flow",
            "date": date_str,
            "total_flow_kg": total_flow,
            "chart_config": config.model_dump()
        }

    return {"error": f"Unknown metric: {metric}"}


# ==============================================================================
# Tool 3: Specialized Visualizations (Gauge, Scatter, Heatmap)
# ==============================================================================

@tool
def create_specialized_chart(
    chart_type: Literal["gauge", "scatter", "heatmap"],
    start_date: str,
    end_date: Optional[str] = None,
    scatter_pair: Optional[Literal[
        "steam_flow_vs_pressure",
        "apparent_power_vs_pf",
        "power_vs_current_thd"
    ]] = None
) -> Dict[str, Any]:
    """
    Generate specialized visualizations: Gauges, Scatter Plots, and Heatmaps.

    CHART_TYPE OPTIONS:
    - 'gauge': Peak Demand KPI gauge showing kVA utilization vs 1475 kVA contract (single date)
    - 'scatter': Correlation scatter plot (requires scatter_pair param, single date)
    - 'heatmap': 2D Hour × Date energy matrix (requires start_date AND end_date)

    SCATTER_PAIR OPTIONS (for scatter):
    - 'steam_flow_vs_pressure': Boiler steam flow vs pressure correlation
    - 'apparent_power_vs_pf': Transformer kVA vs Power Factor
    - 'power_vs_current_thd': Real Power kW vs Current THD %

    EXAMPLES:
    - Demand gauge: chart_type='gauge', start_date='2026-10-21'
    - Scatter: chart_type='scatter', start_date='2026-10-21', scatter_pair='apparent_power_vs_pf'
    - Heatmap: chart_type='heatmap', start_date='2026-10-15', end_date='2026-10-21'
    """
    valid, start_d, err = _validate_date(start_date)
    if not valid:
        return {"error": err}

    # ─────────────────────────────────────────────────────────────────────────
    # GAUGE: Peak Demand Utilization
    # ─────────────────────────────────────────────────────────────────────────
    if chart_type == "gauge":
        demand_data = facility_telemetry.get_peak_demand(start_d)
        peak_kva = demand_data.get("peak_kva") or 0.0
        utilization_pct = demand_data.get("utilization_percent") or 0.0
        status = "CRITICAL" if peak_kva > PEAK_DEMAND_THRESHOLD_KVA else "NORMAL"

        gauge_config = GaugeConfig(
            current_value=peak_kva,
            min_value=0.0,
            max_value=CONTRACTED_DEMAND_KVA,
            threshold_value=PEAK_DEMAND_THRESHOLD_KVA,
            unit="kVA",
            status=status
        )

        config = ChartConfig(
            chart_type="gauge",
            title=f"Peak Demand Utilization — {start_d}",
            subtitle=f"Peak: {peak_kva:,.1f} kVA | Utilization: {utilization_pct}% | Status: {status}",
            gauge_data=gauge_config,
            threshold_line=PEAK_DEMAND_THRESHOLD_KVA,
            threshold_label=f"80% Limit ({PEAK_DEMAND_THRESHOLD_KVA} kVA)",
            representation_reason="Radial gauge provides instant executive readability for capacity headroom."
        )
        return {
            "status": "success",
            "chart_type": "gauge",
            "date": start_d,
            "peak_kva": peak_kva,
            "contracted_kva": CONTRACTED_DEMAND_KVA,
            "utilization_percent": utilization_pct,
            "demand_status": status,
            "chart_config": config.model_dump()
        }

    # ─────────────────────────────────────────────────────────────────────────
    # SCATTER: Correlation Plots
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "scatter":
        if not scatter_pair:
            return {"error": "scatter_pair is required for scatter charts. Options: steam_flow_vs_pressure, apparent_power_vs_pf, power_vs_current_thd"}

        start_ts = f"{start_d} 00:00:00"
        end_ts = f"{start_d} 23:59:59"

        if scatter_pair == "steam_flow_vs_pressure":
            q = f"""
                SELECT
                    toFloat64OrNull(a.value) AS flow,
                    toFloat64OrNull(b.value) AS pressure,
                    toString(a.reading_timestamp) AS reading_timestamp
                FROM opcda_readings a
                JOIN opcda_readings b ON a.reading_timestamp = b.reading_timestamp AND b.tag_id = '{STEAM_PRESSURE_TAG}'
                WHERE a.tag_id = '{STEAM_FLOW_RATE_TAG}'
                  AND a.reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
                  AND a.reading_timestamp <= parseDateTimeBestEffort({{end_ts:String}})
                LIMIT 100;
            """
            rows = db_client.execute_query(q, {"start_ts": start_ts, "end_ts": end_ts})

            points = [
                ScatterPoint(x=round(float(r["flow"]), 1), y=round(float(r["pressure"]), 2), label=str(r["reading_timestamp"])[11:16])
                for r in rows if r["flow"] and r["pressure"]
            ]
            scatter_series = [ScatterSeries(name="Steam Flow vs Pressure", points=points, color="#0891B2")]
            title = f"Correlation: Steam Flow Rate vs Pressure ({start_d})"
            x_label, y_label = "Flow Rate (kg/h)", "Pressure (bar)"
            reason = "Scatter plot detects boiler pressure sag as a function of steam demand."

        elif scatter_pair == "apparent_power_vs_pf":
            pf_tag = "HT_Room.South_Utilities_1000kVA_Transformer/Power Factors/Power Factor Total/Power Factor Total"
            q = f"""
                SELECT
                    toFloat64OrNull(a.value) AS kva,
                    (toFloat64OrNull(b.value) / 100.0) AS pf,
                    toString(a.reading_timestamp) AS reading_timestamp
                FROM opcda_readings a
                JOIN opcda_readings b ON a.reading_timestamp = b.reading_timestamp AND b.tag_id = '{pf_tag}'
                WHERE a.tag_id = '{PEAK_DEMAND_TAG}'
                  AND a.reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
                  AND a.reading_timestamp <= parseDateTimeBestEffort({{end_ts:String}})
                LIMIT 100;
            """
            rows = db_client.execute_query(q, {"start_ts": start_ts, "end_ts": end_ts})

            points = [
                ScatterPoint(x=round(float(r["kva"]), 1), y=round(float(r["pf"]), 3), label=str(r["reading_timestamp"])[11:16])
                for r in rows if r["kva"] and r["pf"]
            ]
            scatter_series = [ScatterSeries(name="kVA vs Power Factor", points=points, color="#2563EB")]
            title = f"Correlation: Apparent Power vs Power Factor ({start_d})"
            x_label, y_label = "Apparent Power (kVA)", "Power Factor (0.0 - 1.0)"
            reason = "Pair plot identifies whether power factor degrades under high loading."

        elif scatter_pair == "power_vs_current_thd":
            real_p_tag = "HT_Room.South_Utilities_1000kVA_Transformer/Powers/Real Power/Real Power Total"
            thd_tag = CURRENT_THD_TAGS[0]
            q = f"""
                SELECT
                    toFloat64OrNull(a.value) AS kw,
                    toFloat64OrNull(b.value) AS thd,
                    toString(a.reading_timestamp) AS reading_timestamp
                FROM opcda_readings a
                JOIN opcda_readings b ON a.reading_timestamp = b.reading_timestamp AND b.tag_id = '{thd_tag}'
                WHERE a.tag_id = '{real_p_tag}'
                  AND a.reading_timestamp >= parseDateTimeBestEffort({{start_ts:String}})
                  AND a.reading_timestamp <= parseDateTimeBestEffort({{end_ts:String}})
                LIMIT 100;
            """
            rows = db_client.execute_query(q, {"start_ts": start_ts, "end_ts": end_ts})

            points = [
                ScatterPoint(x=round(float(r["kw"]), 1), y=round(float(r["thd"]), 2), label=str(r["reading_timestamp"])[11:16])
                for r in rows if r["kw"] and r["thd"]
            ]
            scatter_series = [ScatterSeries(name="Real Power vs Current THD", points=points, color="#DC2626")]
            title = f"Correlation: Real Power (kW) vs Current THD % ({start_d})"
            x_label, y_label = "Real Power (kW)", "Current THD (%)"
            reason = "Scatter plot shows whether harmonic distortion increases with load."

        else:
            return {"error": f"Unknown scatter_pair: {scatter_pair}"}

        config = ChartConfig(
            chart_type="scatter",
            title=title,
            x_axis_label=x_label,
            y_axis_label=y_label,
            scatter_series=scatter_series,
            representation_reason=reason
        )
        return {
            "status": "success",
            "chart_type": "scatter",
            "date": start_d,
            "scatter_pair": scatter_pair,
            "data_points": len(points),
            "chart_config": config.model_dump()
        }

    # ─────────────────────────────────────────────────────────────────────────
    # HEATMAP: Hour × Date Energy Matrix
    # ─────────────────────────────────────────────────────────────────────────
    elif chart_type == "heatmap":
        if not end_date:
            return {"error": "end_date is required for heatmap charts. Example: start_date='2026-10-15', end_date='2026-10-21'"}

        valid, end_d, err = _validate_date(end_date)
        if not valid:
            return {"error": err}

        dt_start = datetime.datetime.strptime(start_d, "%Y-%m-%d").date()
        dt_end = datetime.datetime.strptime(end_d, "%Y-%m-%d").date()
        days_count = (dt_end - dt_start).days + 1

        dates = [(dt_start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count)]
        hours = [f"{h:02d}:00" for h in range(24)]

        # Build 2D matrix [dates][hours]
        z_matrix = []
        total_kwh = 0.0
        for d in dates:
            row = []
            for h in range(24):
                h_start = f"{d} {h:02d}:00:00"
                h_end = f"{d} {h:02d}:59:59"
                val = db_client.get_tag_delta(SHIFT_ENERGY_TAG, h_start, h_end) or 0.0
                row.append(round(val, 1))
                total_kwh += val
            z_matrix.append(row)

        heatmap_data = HeatmapMatrix(
            x_labels=hours,
            y_labels=dates,
            z_matrix=z_matrix,
            z_label="kWh"
        )

        config = ChartConfig(
            chart_type="heatmap",
            title=f"Hourly Energy Load Heatmap ({start_d} to {end_d})",
            subtitle=f"Matrix: {len(dates)} Days × 24 Hours | Total: {total_kwh:,.1f} kWh",
            x_axis_label="Hour of Day (IST)",
            y_axis_label="Calendar Date",
            heatmap_data=heatmap_data,
            representation_reason="2D Heatmap visualizes shift-level patterns, night baseload leaks, and production clusters."
        )
        return {
            "status": "success",
            "chart_type": "heatmap",
            "date_range": {"start": start_d, "end": end_d},
            "days_count": days_count,
            "total_kwh": round(total_kwh, 1),
            "chart_config": config.model_dump()
        }

    return {"error": f"Unknown chart_type: {chart_type}"}


# ==============================================================================
# Tool Registry & Backward Compatibility
# ==============================================================================

from src.services.aggregation_service import aggregation_service
from src.services.telemetry import equipments_telemetry, zones_telemetry

ALL_CHART_TOOLS = [
    create_chart,
    create_power_quality_chart,
    create_specialized_chart,
]


@tool
def aggregate_energy_telemetry(
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
    granularity: Literal["daily", "hourly", "30min", "15min", "shift_wise"] = "daily",
    equipment: Optional[List[str]] = None,
    zones: Optional[List[str]] = None,
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
    """Unified industrial telemetry and energy aggregation tool for Yamaha EMS."""
    return aggregation_service.aggregate(
        aggregation_type=aggregation_type,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
        equipment=equipment,
        zones=zones,
        metrics=metrics,
        chart_type=chart_type
    )


# Backward-compatible tool wrappers for legacy tests and routes
@tool
def create_breakdown_chart(
    date: str = "yesterday",
    breakdown_type: Literal["equipment_wise", "zone_wise", "tariff_bands"] = "equipment_wise",
    preferred_type: Literal["auto", "donut", "pie", "bar", "stacked_bar"] = "auto"
) -> Dict[str, Any]:
    """Legacy wrapper for breakdown charts."""
    clean_date = normalize_date_str(date)
    if breakdown_type == "equipment_wise":
        data = equipments_telemetry.get_category_breakdown(clean_date)
        items = data.get("categories", [])
        title = f"Equipment-Wise Energy Breakdown ({clean_date})"
        total_kwh = data.get("total_kwh", 0.0)
        labels = [item["category"] for item in items]
        values = [item["energy_kwh"] for item in items]
    elif breakdown_type == "zone_wise":
        data = zones_telemetry.get_zone_breakdown(clean_date)
        items = data.get("cost_centers", [])
        title = f"Zone-Wise Cost Center Breakdown ({clean_date})"
        total_kwh = data.get("total_kwh", 0.0)
        labels = [item["cost_center"] for item in items]
        values = [item["energy_kwh"] for item in items]
    elif breakdown_type == "tariff_bands":
        from src.services.tariff_service import TariffService
        tariff_data = TariffService.calculate_daily_cost(clean_date)
        bands = tariff_data.get("band_summary", {})
        title = f"TOD Tariff Band Energy Share ({clean_date})"
        total_kwh = tariff_data.get("true_daily_kwh", 0.0)
        labels = list(bands.keys())
        values = [b["kwh"] for b in bands.values()]
        items = [{"band": k, "kwh": v["kwh"]} for k, v in bands.items()]
    else:
        return {"error": f"Unknown breakdown_type: {breakdown_type}"}

    if preferred_type == "auto":
        selected_type = "donut" if len(labels) <= 8 else "bar"
    else:
        selected_type = preferred_type

    config = ChartConfig(
        chart_type=selected_type,
        title=title,
        subtitle=f"Total: {total_kwh:,.1f} kWh",
        x_labels=labels,
        y_axis_label="Energy (kWh)",
        series=[ChartSeries(name="Energy", data=values, unit="kWh")],
        center_kpi={"label": "Total", "value": f"{total_kwh:,.0f} kWh"} if selected_type in ("donut", "pie") else None,
        representation_reason="Optimal breakdown representation."
    )
    result = config.model_dump()
    result["total_kwh"] = total_kwh
    result["categories"] = items
    result["breakdown"] = items
    result["chart_config"] = config.model_dump()
    return result


@tool
def create_time_series_chart(
    date: str = "yesterday",
    metric: Literal["apparent_power", "hourly_kwh", "voltage_thd", "current_thd", "steam_flow"] = "hourly_kwh"
) -> Dict[str, Any]:
    """Legacy wrapper for create_power_quality_chart."""
    clean_date = normalize_date_str(date)
    if metric == "hourly_kwh":
        res = create_chart.invoke({
            "chart_for": "facility",
            "start_date": clean_date,
            "granularity": "hourly",
            "chart_type": "bar"
        })
        return res.get("chart_config", res)
    elif metric == "apparent_power":
        res = create_power_quality_chart.invoke({
            "start_date": clean_date,
            "metric": "peak_demand"
        })
        return res.get("chart_config", res)
    else:
        res = create_power_quality_chart.invoke({
            "start_date": clean_date,
            "metric": metric
        })
        return res.get("chart_config", res)


@tool
def create_shift_comparison_chart(
    start_date: str = "yesterday",
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """Legacy wrapper for shift comparison."""
    start_d = normalize_date_str(start_date)
    end_d = normalize_date_str(end_date) if end_date else None

    if not end_d or start_d == end_d:
        data = facility_telemetry.get_grid_shift_energy(start_d)
        shifts = data.get("shifts", {})
        labels = ["Shift A (Day)", "Shift B (Evening)", "Shift C (Night)"]
        values = [
            shifts.get("Shift A", {}).get("energy_kwh", 0.0),
            shifts.get("Shift B", {}).get("energy_kwh", 0.0),
            shifts.get("Shift C", {}).get("energy_kwh", 0.0)
        ]
        total = data.get("total_shifts_kwh", sum(values))
        config = ChartConfig(
            chart_type="donut",
            title=f"Shift-Wise Energy Distribution ({start_d})",
            subtitle=f"Total: {total:,.1f} kWh",
            x_labels=labels,
            y_axis_label="Energy (kWh)",
            series=[ChartSeries(name="Shift Energy", data=values, unit="kWh")],
            center_kpi={"label": "Total", "value": f"{total:,.0f} kWh"},
            representation_reason="Donut chart clearly shows relative contribution of 3 operational shifts."
        )
        return config.model_dump()
    else:
        dt_start = datetime.datetime.strptime(start_d, "%Y-%m-%d").date()
        dt_end = datetime.datetime.strptime(end_d, "%Y-%m-%d").date()
        days_count = (dt_end - dt_start).days + 1
        dates = [(dt_start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count)]
        shift_a, shift_b, shift_c = [], [], []
        for d in dates:
            data = facility_telemetry.get_grid_shift_energy(d)
            shifts = data.get("shifts", {})
            shift_a.append(shifts.get("Shift A", {}).get("energy_kwh", 0.0))
            shift_b.append(shifts.get("Shift B", {}).get("energy_kwh", 0.0))
            shift_c.append(shifts.get("Shift C", {}).get("energy_kwh", 0.0))
        series = [
            ChartSeries(name="Shift A (Day)", data=shift_a, color="#2563EB", unit="kWh"),
            ChartSeries(name="Shift B (Evening)", data=shift_b, color="#059669", unit="kWh"),
            ChartSeries(name="Shift C (Night)", data=shift_c, color="#D97706", unit="kWh")
        ]
        config = ChartConfig(
            chart_type="stacked_bar",
            title=f"Shift Energy Comparison ({start_d} to {end_d})",
            subtitle=f"Multi-Day Comparison across 3 Shifts",
            x_axis_label="Calendar Date",
            x_labels=dates,
            y_axis_label="Energy (kWh)",
            series=series,
            representation_reason="Stacked bar chart enables direct comparison of shift-by-shift totals over consecutive production dates."
        )
        return config.model_dump()


@tool
def create_demand_utilization_gauge(date: str = "yesterday") -> Dict[str, Any]:
    """Legacy wrapper for peak demand gauge."""
    res = create_specialized_chart.invoke({
        "chart_type": "gauge",
        "start_date": date
    })
    return res.get("chart_config", res)


@tool
def create_correlation_scatter_plot(
    date: str = "yesterday",
    pair_type: Literal["steam_flow_vs_pressure", "apparent_power_vs_pf", "power_vs_current_thd"] = "steam_flow_vs_pressure"
) -> Dict[str, Any]:
    """Legacy wrapper for correlation scatter plots."""
    res = create_specialized_chart.invoke({
        "chart_type": "scatter",
        "start_date": date,
        "scatter_pair": pair_type
    })
    return res.get("chart_config", res)


@tool
def create_load_heatmap(
    start_date: str = "yesterday",
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """Legacy wrapper for load heatmap."""
    res = create_specialized_chart.invoke({
        "chart_type": "heatmap",
        "start_date": start_date,
        "end_date": end_date
    })
    return res.get("chart_config", res)


__all__ = [
    "create_chart",
    "create_power_quality_chart",
    "create_specialized_chart",
    "create_breakdown_chart",
    "create_time_series_chart",
    "create_shift_comparison_chart",
    "create_demand_utilization_gauge",
    "create_correlation_scatter_plot",
    "create_load_heatmap",
    "aggregate_energy_telemetry",
    "ALL_CHART_TOOLS",
]
