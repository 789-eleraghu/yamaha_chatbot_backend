"""
Advanced Graph & Chart Generation Tools
Supports:
- Line, Area, Stacked Area (time-series & load curves)
- Bar, Stacked Bar, Grouped Bar (comparisons & shift compositions)
- Pie, Donut (part-to-whole, category distribution, cost center share)
- Scatter, Pair Plot (correlations: Steam Flow vs Pressure, kW vs THD, kVA vs PF)
- Gauge / Radial (Peak Demand utilization % vs 1475 kVA contract & 1180 kVA threshold)
- 2D Heatmap (Hour-of-day 00:00-23:00 vs Date load matrix)
Selects and formats the best visual representation based on user requirements.
"""

import datetime
from typing import Any, Dict, List, Literal, Optional
from langchain_core.tools import tool

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
from src.db.sqlite_client import db_client
from src.schemas.charts import (
    ChartConfig,
    ChartSeries,
    GaugeConfig,
    HeatmapMatrix,
    ScatterPoint,
    ScatterSeries,
)
from src.services.breakdown_service import BreakdownService
from src.services.demand_service import DemandService
from src.services.shift_service import ShiftService
from src.services.tariff_service import TariffService
from src.core.normalizers import normalize_date_str

# Industrial Color Palettes
PALETTE = [
    "#2563EB",  # Electric Blue
    "#059669",  # Emerald Green
    "#D97706",  # Amber
    "#DC2626",  # Crimson
    "#7C3AED",  # Purple
    "#0891B2",  # Cyan
    "#DB2777",  # Pink
    "#4B5563",  # Slate
]

@tool
def create_breakdown_chart(
    date: str,
    breakdown_type: Literal["equipment_wise", "zone_wise", "tariff_bands"],
    preferred_type: Literal["auto", "donut", "pie", "bar", "stacked_bar"] = "auto"
) -> Dict[str, Any]:
    """
    Generate an optimal breakdown visualization (Donut, Pie, or Bar chart):
    - 'equipment_wise': 8 categories (Lighting, Molding, etc.) with exclusions applied.
    - 'zone_wise': 17 organizational cost centers.
    - 'tariff_bands': Off-Peak, Normal, and Peak kWh and Cost share.
    Selects Donut with Center KPI for proportions, or Bar for ranked comparisons.
    """
    date = normalize_date_str(date)
    if breakdown_type == "equipment_wise":
        data = BreakdownService.get_equipment_wise_breakdown(date)
        items = data.get("categories", [])
        title = f"Equipment-Wise Energy Breakdown ({date})"
        total_kwh = data.get("total_kwh", 0.0)
        labels = [item["category"] for item in items]
        values = [item["energy_kwh"] for item in items]
        unit = "kWh"
    elif breakdown_type == "zone_wise":
        data = BreakdownService.get_zone_wise_cost_centers(date)
        items = data.get("cost_centers", [])
        title = f"Zone-Wise Cost Center Breakdown ({date})"
        total_kwh = data.get("total_kwh", 0.0)
        labels = [item["cost_center"] for item in items]
        values = [item["energy_kwh"] for item in items]
        unit = "kWh"
    elif breakdown_type == "tariff_bands":
        tariff_data = TariffService.calculate_daily_cost(date)
        bands = tariff_data.get("band_summary", {})
        title = f"TOD Tariff Band Energy Share ({date})"
        total_kwh = tariff_data.get("true_daily_kwh", 0.0)
        labels = list(bands.keys())
        values = [b["kwh"] for b in bands.values()]
        items = [{"band": k, "kwh": v["kwh"]} for k, v in bands.items()]
        unit = "kWh"
    else:
        return {"error": f"Unknown breakdown_type: {breakdown_type}"}

    # Best representation logic:
    # If <= 8 slices and preferred_type is auto -> Donut with Center KPI is the most readable
    # If > 10 items (like 17 cost centers) and preferred_type is auto -> Bar chart prevents slice crowding
    if preferred_type == "auto":
        if len(labels) <= 8:
            selected_type = "donut"
            reason = "Donut chart provides the clearest representation for under 8 categorical slices, showing both relative proportions and the total facility KPI in the center."
        else:
            selected_type = "bar"
            reason = f"Ranked horizontal/vertical bar chart is optimal for {len(labels)} categories to prevent label crowding and allow direct visual ranking."
    else:
        selected_type = preferred_type
        reason = f"Explicitly requested {preferred_type} chart."

    series = [
        ChartSeries(
            name=f"Consumption ({unit})",
            data=values,
            unit=unit
        )
    ]

    center_kpi = {
        "label": "Total Energy",
        "value": f"{total_kwh:,.1f} {unit}"
    }

    config = ChartConfig(
        chart_type=selected_type,
        title=title,
        subtitle=f"Date: {date} | Total: {total_kwh:,.1f} {unit}",
        x_axis_label="Category / Department",
        x_labels=labels,
        y_axis_label=f"Energy ({unit})",
        series=series,
        center_kpi=center_kpi if selected_type in ("donut", "pie") else None,
        representation_reason=reason
    )
    result = config.model_dump()
    result["total_kwh"] = total_kwh
    result["categories"] = items
    result["breakdown"] = items
    result["chart_config"] = config.model_dump()
    return result

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
    """
    Unified industrial telemetry and energy aggregation tool for Yamaha EMS.
    Performs multi-dimensional analysis in a SINGLE call without needing multiple tool executions:
    - 'equipment_wise': Aggregates 8 machinery categories with exclusions applied.
    - 'zone_wise': Aggregates 17 organizational cost centers (e.g. AG Assy, AG Painting, General Admin).
    - 'facility': Total facility grid energy trend or hourly/30-min load curve.
    - 'specific_equipment': Pass single or array of machines (e.g. ['Compressor 1', 'Molding 1600T', 'Chiller']).
    - 'multi_variate': Correlates Energy (kWh) with Peak Demand (kVA) and Power Factor on dual Y-axes ComposedChart.
    - 'radar_comparison': Multi-attribute Radar/Spider diagram comparing operational shifts across 5 dimensions.
    - 'granularity': 'daily', 'hourly', '30min' (every 30 minutes, 48 intervals), '15min' (every 15 minutes, 96 intervals).
    Returns both the numerical telemetry dataset and the complete interactive Recharts ChartConfig.
    """
    from src.services.aggregation_service import aggregation_service
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

@tool
def create_time_series_chart(
    date: str,
    metric: Literal["apparent_power", "hourly_kwh", "voltage_thd", "current_thd", "steam_flow"],
    preferred_type: Literal["auto", "line", "area", "bar"] = "auto"
) -> Dict[str, Any]:
    """
    Generate an optimal time-series trend or hourly load curve visualization:
    - 'apparent_power': Peak demand kVA profile with the 1180 kVA threshold line.
    - 'hourly_kwh': Hourly consumption profile (bar or area).
    - 'voltage_thd' / 'current_thd': Harmonic distortion curve with 5% / 8% limit lines.
    - 'steam_flow': Blower Room steam flow rate trend (kg/h).
    """
    date = normalize_date_str(date)
    if metric == "apparent_power":
        demand_data = DemandService.get_peak_demand_analysis(date)
        profile = demand_data.get("hourly_profile", [])
        x_labels = [p["label"] for p in profile]
        y_values = [p["peak_kva"] for p in profile]
        
        selected_type = "line" if preferred_type == "auto" else preferred_type
        config = ChartConfig(
            chart_type=selected_type,
            title=f"Hourly Peak Demand Profile (kVA) - {date}",
            subtitle=f"Contracted: {CONTRACTED_DEMAND_KVA} kVA | Peak: {demand_data.get('peak_kva')} kVA ({demand_data.get('utilization_percent')}%)",
            x_axis_label="Hour of Day (IST)",
            x_labels=x_labels,
            y_axis_label="Apparent Power (kVA)",
            threshold_line=PEAK_DEMAND_THRESHOLD_KVA,
            threshold_label=f"80% Threshold Limit ({PEAK_DEMAND_THRESHOLD_KVA} kVA)",
            series=[
                ChartSeries(name="Peak Apparent Power", data=y_values, color="#2563EB", unit="kVA")
            ],
            representation_reason="Continuous line chart with horizontal limit line is the gold standard for tracking electrical peak demand and visual threshold crossing."
        )
        return config.model_dump()

    elif metric == "hourly_kwh":
        tariff_data = TariffService.calculate_daily_cost(date)
        hourly_rows = tariff_data.get("hourly_breakdown", [])
        x_labels = [r["hour_label"] for r in hourly_rows]
        y_values = [r["rescaled_kwh"] for r in hourly_rows]
        
        selected_type = "bar" if preferred_type == "auto" else preferred_type
        config = ChartConfig(
            chart_type=selected_type,
            title=f"Hourly Energy Consumption Profile (kWh) - {date}",
            subtitle=f"Total: {tariff_data.get('true_daily_kwh'):,.1f} kWh | Rescaling factor: {tariff_data.get('rescaling_factor')}",
            x_axis_label="Hour of Day (IST)",
            x_labels=x_labels,
            y_axis_label="Electricity Consumption (kWh)",
            series=[
                ChartSeries(name="Hourly Energy", data=y_values, color="#059669", unit="kWh")
            ],
            representation_reason="Bar chart best represents discrete hourly energy buckets across the 24-hour day-night cycle."
        )
        return config.model_dump()

    elif metric in ("voltage_thd", "current_thd"):
        # Query hourly THD averages
        is_voltage = (metric == "voltage_thd")
        tag = VOLTAGE_THD_TAGS[3] if is_voltage else CURRENT_THD_TAGS[0]
        limit = 5.0 if is_voltage else 8.0
        unit = "%"
        
        q = f"""
            SELECT SUBSTR(reading_timestamp, 12, 2) || ':00' AS hour_str, AVG(value) AS avg_thd
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ? AND value > 0
            GROUP BY hour_str
            ORDER BY hour_str ASC;
        """
        rows = db_client.execute_query(q, (tag, f"{date} 00:00:00", f"{date} 23:59:59"))
        x_labels = [r["hour_str"] for r in rows]
        y_values = [round(float(r["avg_thd"]), 2) for r in rows]

        name = "Voltage THD (L-N)" if is_voltage else "Current THD (Phase A)"
        config = ChartConfig(
            chart_type="line" if preferred_type == "auto" else preferred_type,
            title=f"Harmonic Distortion Profile - {name} ({date})",
            subtitle=f"Compliance Limit: {limit}%",
            x_axis_label="Hour of Day (IST)",
            x_labels=x_labels,
            y_axis_label="THD (%)",
            threshold_line=limit,
            threshold_label=f"IEEE 519 / Yamaha Limit ({limit}%)",
            series=[
                ChartSeries(name=name, data=y_values, color="#D97706", unit="%")
            ],
            representation_reason="Line chart with regulatory limit line clearly highlights harmonic distortion excursions."
        )
        return config.model_dump()

    elif metric == "steam_flow":
        q = """
            SELECT SUBSTR(reading_timestamp, 12, 2) || ':00' AS hour_str, AVG(value) AS avg_flow
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ? AND value > 0
            GROUP BY hour_str
            ORDER BY hour_str ASC;
        """
        rows = db_client.execute_query(q, (STEAM_FLOW_RATE_TAG, f"{date} 00:00:00", f"{date} 23:59:59"))
        x_labels = [r["hour_str"] for r in rows]
        y_values = [round(float(r["avg_flow"]), 1) for r in rows]

        config = ChartConfig(
            chart_type="area" if preferred_type == "auto" else preferred_type,
            title=f"Steam Flow Rate Profile (kg/h) - {date}",
            subtitle="Flowmeter-Gate1.Blower_Room_Steam",
            x_axis_label="Hour of Day (IST)",
            x_labels=x_labels,
            y_axis_label="Steam Flow Rate (kg/h)",
            series=[
                ChartSeries(name="Steam Flow Rate", data=y_values, color="#0891B2", unit="kg/h")
            ],
            representation_reason="Area chart conveys thermal utility delivery volume smoothly over time."
        )
        return config.model_dump()

    return {"error": f"Unsupported metric: {metric}"}

@tool
def create_shift_comparison_chart(
    start_date: str,
    end_date: Optional[str] = None,
    preferred_type: Literal["auto", "stacked_bar", "grouped_bar", "donut"] = "auto"
) -> Dict[str, Any]:
    """
    Generate a shift comparison visualization across shifts A, B, and C:
    - Single day: Donut or Grouped Bar comparing Shift A (08-17), Shift B (17-00:40), Shift C (00:40-08).
    - Multi-day: Stacked Bar showing daily total height while visualizing Shift A, B, C contributions.
    """
    start_date = normalize_date_str(start_date)
    if end_date:
        end_date = normalize_date_str(end_date)
    if not end_date or end_date == start_date:
        # Single day
        shift_data = ShiftService.get_shift_consumption(start_date)
        a_kwh = shift_data.get("shift_a_kwh") or 0.0
        b_kwh = shift_data.get("shift_b_kwh") or 0.0
        c_kwh = shift_data.get("shift_c_kwh") or 0.0
        total = round(a_kwh + b_kwh + c_kwh, 1)

        selected_type = "donut" if preferred_type in ("auto", "donut") else preferred_type
        labels = ["Shift A (08:00-17:00)", "Shift B (17:00-00:40)", "Shift C (00:40-08:00)"]
        values = [a_kwh, b_kwh, c_kwh]

        config = ChartConfig(
            chart_type=selected_type,
            title=f"Shift-Wise Energy Distribution ({start_date})",
            subtitle=f"Total Across Shifts: {total:,.1f} kWh",
            x_axis_label="Industrial Shift",
            x_labels=labels,
            y_axis_label="Energy (kWh)",
            series=[
                ChartSeries(name="Shift kWh", data=values, unit="kWh")
            ],
            center_kpi={"label": "Shift Total", "value": f"{total:,.1f} kWh"},
            representation_reason="Donut chart immediately displays the proportion of energy consumed across Day (A), Evening (B), and Night (C) shifts."
        )
        return config.model_dump()
    else:
        # Multi-day range: Stacked Bar is the best representation!
        dt_start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
        dt_end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        days_count = (dt_end - dt_start).days + 1

        dates = [(dt_start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count)]
        shift_a_vals = []
        shift_b_vals = []
        shift_c_vals = []

        for d in dates:
            s_data = ShiftService.get_shift_consumption(d)
            shift_a_vals.append(s_data.get("shift_a_kwh") or 0.0)
            shift_b_vals.append(s_data.get("shift_b_kwh") or 0.0)
            shift_c_vals.append(s_data.get("shift_c_kwh") or 0.0)

        selected_type = "stacked_bar" if preferred_type == "auto" else preferred_type
        config = ChartConfig(
            chart_type=selected_type,
            title=f"Multi-Day Shift Breakdown ({start_date} to {end_date})",
            subtitle=f"Total {days_count} Days Tracked",
            x_axis_label="Calendar Date (IST)",
            x_labels=dates,
            y_axis_label="Energy Consumption (kWh)",
            series=[
                ChartSeries(name="Shift A (Day)", data=shift_a_vals, color="#2563EB", unit="kWh"),
                ChartSeries(name="Shift B (Evening)", data=shift_b_vals, color="#D97706", unit="kWh"),
                ChartSeries(name="Shift C (Night)", data=shift_c_vals, color="#7C3AED", unit="kWh"),
            ],
            representation_reason="Stacked bar chart is the optimal visualization for multi-day shift comparisons because bar height reveals the total daily load while internal segments reveal shift composition."
        )
        return config.model_dump()

@tool
def create_demand_utilization_gauge(date: str) -> Dict[str, Any]:
    """
    Generate an executive KPI Gauge/Radial meter showing peak apparent power (kVA)
    against the 1475.0 kVA Contracted Demand limit and 1180.0 kVA (80%) threshold.
    """
    date = normalize_date_str(date)
    demand_data = DemandService.get_peak_demand_analysis(date)
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
        title=f"Peak Demand Utilization Gauge ({date})",
        subtitle=f"Peak: {peak_kva:,.1f} kVA | Utilization: {utilization_pct}% | Status: {status}",
        gauge_data=gauge_config,
        threshold_line=PEAK_DEMAND_THRESHOLD_KVA,
        threshold_label="80% Contract Limit (1180 kVA)",
        representation_reason="Radial Gauge provides instant executive readability for capacity headroom and threshold compliance."
    )
    return config.model_dump()

@tool
def create_correlation_scatter_plot(
    date: str,
    pair_type: Literal["steam_flow_vs_pressure", "apparent_power_vs_pf", "power_vs_current_thd"]
) -> Dict[str, Any]:
    """
    Generate a Scatter Plot / Pair Plot to analyze physical and electrical correlations:
    - 'steam_flow_vs_pressure': Boiler pressure stability vs steam consumption surge.
    - 'apparent_power_vs_pf': Transformer loading (kVA) vs Power Factor degradation.
    - 'power_vs_current_thd': Real load (kW) vs Harmonic current distortion (%).
    """
    date = normalize_date_str(date)
    start_ts = f"{date} 00:00:00"
    end_ts = f"{date} 23:59:59"

    if pair_type == "steam_flow_vs_pressure":
        q = f"""
            SELECT a.value AS flow, b.value AS pressure, a.reading_timestamp
            FROM opcda_readings a
            JOIN opcda_readings b ON a.reading_timestamp = b.reading_timestamp AND b.tag_id = '{STEAM_PRESSURE_TAG}'
            WHERE a.tag_id = '{STEAM_FLOW_RATE_TAG}' AND a.reading_timestamp >= ? AND a.reading_timestamp <= ?
            LIMIT 100;
        """
        rows = db_client.execute_query(q, (start_ts, end_ts))
        points = [
            ScatterPoint(
                x=round(float(r["flow"]), 1),
                y=round(float(r["pressure"]), 2),
                label=r["reading_timestamp"][11:16]
            )
            for r in rows
        ]
        scatter_series = [ScatterSeries(name="Steam Flow vs Pressure", points=points, color="#0891B2")]
        title = f"Correlation: Steam Flow Rate vs Pressure ({date})"
        x_label = "Flow Rate (kg/h)"
        y_label = "Pressure (bar)"
        reason = "Scatter plot detects boiler pressure sag as a function of instantaneous steam demand."

    elif pair_type == "apparent_power_vs_pf":
        pf_tag = f"HT_Room.South_Utilities_1000kVA_Transformer/Power Factors/Power Factor Total/Power Factor Total"
        q = f"""
            SELECT a.value AS kva, (b.value / 100.0) AS pf, a.reading_timestamp
            FROM opcda_readings a
            JOIN opcda_readings b ON a.reading_timestamp = b.reading_timestamp AND b.tag_id = '{pf_tag}'
            WHERE a.tag_id = '{PEAK_DEMAND_TAG}' AND a.reading_timestamp >= ? AND a.reading_timestamp <= ?
            LIMIT 100;
        """
        rows = db_client.execute_query(q, (start_ts, end_ts))
        points = [
            ScatterPoint(
                x=round(float(r["kva"]), 1),
                y=round(float(r["pf"]), 3),
                label=r["reading_timestamp"][11:16]
            )
            for r in rows
        ]
        scatter_series = [ScatterSeries(name="kVA vs Power Factor", points=points, color="#2563EB")]
        title = f"Correlation: Apparent Power vs Power Factor ({date})"
        x_label = "Apparent Power (kVA)"
        y_label = "Power Factor (0.0 - 1.0)"
        reason = "Pair plot identifies whether transformer power factor degrades under high loading."

    elif pair_type == "power_vs_current_thd":
        real_p_tag = "HT_Room.South_Utilities_1000kVA_Transformer/Powers/Real Power/Real Power Total"
        thd_tag = CURRENT_THD_TAGS[0]
        q = f"""
            SELECT a.value AS kw, b.value AS thd, a.reading_timestamp
            FROM opcda_readings a
            JOIN opcda_readings b ON a.reading_timestamp = b.reading_timestamp AND b.tag_id = '{thd_tag}'
            WHERE a.tag_id = '{real_p_tag}' AND a.reading_timestamp >= ? AND a.reading_timestamp <= ?
            LIMIT 100;
        """
        rows = db_client.execute_query(q, (start_ts, end_ts))
        points = [
            ScatterPoint(
                x=round(float(r["kw"]), 1),
                y=round(float(r["thd"]), 2),
                label=r["reading_timestamp"][11:16]
            )
            for r in rows
        ]
        scatter_series = [ScatterSeries(name="Real Power vs Current THD", points=points, color="#DC2626")]
        title = f"Correlation: Real Power (kW) vs Current THD % ({date})"
        x_label = "Real Power (kW)"
        y_label = "Current THD (%)"
        reason = "Scatter plot proves whether non-linear harmonic distortion increases proportionally with factory load."

    else:
        return {"error": f"Unknown pair_type: {pair_type}"}

    config = ChartConfig(
        chart_type="scatter",
        title=title,
        x_axis_label=x_label,
        y_axis_label=y_label,
        scatter_series=scatter_series,
        representation_reason=reason
    )
    return config.model_dump()

@tool
def create_load_heatmap(
    start_date: str,
    end_date: str
) -> Dict[str, Any]:
    """
    Generate a 2D Heatmap Matrix showing energy consumption intensity across
    Hour of Day (00:00 to 23:00) vs Calendar Dates/Days.
    Best visual representation for discovering operational load patterns, vampire loads, and shift anomalies.
    """
    start_date = normalize_date_str(start_date)
    end_date = normalize_date_str(end_date)
    dt_start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    dt_end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    days_count = (dt_end - dt_start).days + 1

    dates = [(dt_start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count)]
    hours = [f"{h:02d}:00" for h in range(24)]

    # Build 2D matrix [dates][hours]
    z_matrix = []
    for d in dates:
        row = []
        for h in range(24):
            start_ts = f"{d} {h:02d}:00:00"
            end_ts = f"{d} {h:02d}:59:59"
            val = db_client.get_tag_delta(SHIFT_ENERGY_TAG, start_ts, end_ts) or 0.0
            row.append(round(val, 1))
        z_matrix.append(row)

    heatmap_data = HeatmapMatrix(
        x_labels=hours,
        y_labels=dates,
        z_matrix=z_matrix,
        z_label="kWh"
    )

    config = ChartConfig(
        chart_type="heatmap",
        title=f"Hourly Energy Load Heatmap ({start_date} to {end_date})",
        subtitle=f"Matrix: {len(dates)} Days × 24 Hours (IST)",
        x_axis_label="Hour of Day (IST)",
        y_axis_label="Calendar Date",
        heatmap_data=heatmap_data,
        representation_reason="2D Heatmap instantly visualizes shift-level energy patterns, night baseload leaks, and high-intensity production clusters."
    )
    return config.model_dump()

ALL_CHART_TOOLS = [
    aggregate_energy_telemetry,
    create_breakdown_chart,
    create_time_series_chart,
    create_shift_comparison_chart,
    create_demand_utilization_gauge,
    create_correlation_scatter_plot,
    create_load_heatmap,
]
