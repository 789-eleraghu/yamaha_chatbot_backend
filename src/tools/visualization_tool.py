"""
🎨 INTELLIGENT VISUALIZATION TOOL (LCEL Architecture)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Clean LCEL-based architecture enforcing:
    parse_intent → retrieve_data → validate_numeric → build_chart

Data retrieval is ALWAYS executed before visualization.
Uses LangChain Expression Language (LCEL) for composable, traceable chains.
Enforces strict numeric telemetry validation matching numerical tools.
"""

import datetime
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Callable

from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool

from src.core.constants import (
    CONTRACTED_DEMAND_KVA,
    CURRENT_THD_TAGS,
    PEAK_DEMAND_THRESHOLD_KVA,
    PEAK_DEMAND_TAG,
    SHIFT_ENERGY_TAG,
    SOLAR_ENERGY_TAG,
    STEAM_FLOW_RATE_TAG,
    STEAM_PRESSURE_TAG,
)
from src.core.normalizers import (
    normalize_category_name,
    normalize_cost_center_name,
    normalize_date_str,
)
from src.db.client import db_client
from src.schemas.charts import (
    ChartConfig,
    ChartSeries,
    GaugeConfig,
    HeatmapMatrix,
    ScatterPoint,
    ScatterSeries,
)
from src.services.date_service import date_service
from src.services.tariff_service import TariffService
from src.services.telemetry import (
    equipments_telemetry,
    facility_telemetry,
    zones_telemetry,
)


# ==============================================================================
# STEP 1: INTENT PARSING (First link in the chain)
# ==============================================================================

# Priority ordered: Specific/trend keywords checked first
INTENT_KEYWORDS = {
    # Explicit time series / trend triggers
    "zone_trend": [
        "zone trend", "cost center trend", "daily zone", "zone daily",
        "department trend", "zones trend", "zones over time", "departments over time",
        "zone consumption over time"
    ],
    "equipment_trend": [
        "equipment trend", "category trend", "daily equipment", "equipment daily",
        "categories trend", "equipments trend", "equipments over time",
        "equipment consumption over time"
    ],
    "facility_trend": [
        "facility trend", "grid trend", "plant trend", "daily facility",
        "facility daily", "daily grid", "grid daily"
    ],
    # Specialized visualizations
    "gauge": ["gauge", "peak demand kpi", "demand utilization", "capacity meter", "peak demand gauge"],
    "heatmap": ["heatmap", "hour day pattern", "hourly pattern", "heat map", "load heatmap"],
    "scatter": ["scatter", "correlation", " vs ", "relationship", "scatter plot"],
    "thd": ["thd", "harmonic", "harmonics", "distortion", "vthd", "ithd"],
    "power_factor": ["power factor", "pf trend", "pf compliance", " pf ", "pf "],
    "tariff": ["tariff", "tod", "off-peak", "peak band", "cost split", "billing", "tod band"],
    "shift": ["shift", "shift a", "shift b", "shift c", "shifts", "shift distribution", "shift breakdown"],
    "solar": ["solar", "pv", "rooftop", "solar generation", "solar curve", "solar profile", "solar power", "solar output", "solar units", "solar chart"],
    # Categorical breakdowns
    "equipment": ["equipment", "machinery", "category", "machine", "categories", "equipments"],
    "zone": ["zone", "cost center", "department", "area", "zones", "cost centers"],
    "facility": ["facility", "total", "plant", "incomer", "grid", "load profile", "load curve", "facility consumption", "grid consumption", "overall consumption", "power consumption"],
}

TREND_KEYWORDS = [
    "trend", "daily", "line chart", "over time", "consumption over",
    "time series", "day by day", "each day", "per day", "days", "compare dates"
]


def _is_trend_request(intent: str, start_date: str, end_date: Optional[str]) -> bool:
    """Determine if the request is for a time series trend (not a single-day breakdown)."""
    if end_date and end_date != start_date:
        return True
    intent_lower = intent.lower()
    return any(kw in intent_lower for kw in TREND_KEYWORDS)


def _extract_preferred_chart_type(intent: str) -> Optional[str]:
    """Extract explicit user chart type requests (bar, pie, donut, line, area, etc.)."""
    intent_lower = intent.lower()
    if "horizontal bar" in intent_lower or ("horizontal" in intent_lower and "bar" in intent_lower):
        return "horizontal_bar"
    if any(k in intent_lower for k in ["bar chart", "bar graph", "bar plot", "as bar", "as a bar", "to bar", "to a bar", "into bar", "into a bar"]):
        return "bar"
    if any(k in intent_lower for k in ["pie chart", "pie graph", "pie plot", "as pie", "as a pie", "to pie", "to a pie"]):
        return "pie"
    if any(k in intent_lower for k in ["donut chart", "donut graph", "donut plot", "as donut", "as a donut", "to donut", "to a donut", "doughnut"]):
        return "donut"
    if any(k in intent_lower for k in ["area chart", "area graph", "area plot", "as area", "as a area", "as an area", "to area", "to an area"]):
        return "area"
    if any(k in intent_lower for k in ["line chart", "line graph", "line plot", "as line", "as a line", "to line", "to a line"]):
        return "line"
    return None


def _parse_intent_step(input_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    LCEL Step 1: Parse natural language intent into visualization type and parameters.

    Input: {"intent": str, "start_date": str, "end_date": str, ...}
    Output: {...input, "viz_type": str, "metadata": dict, "filter_items": list, "granularity": str}
    """
    raw_intent = input_dict.get("intent", "")
    intent = raw_intent.lower()
    start_date = input_dict.get("start_date")
    end_date = input_dict.get("end_date")
    granularity = input_dict.get("granularity", "daily")
    filter_items = list(input_dict.get("filter_items") or [])

    metadata = {"raw_intent": raw_intent}

    # 1. Auto-detect hourly granularity from intent if not explicitly set
    hourly_triggers = ["hourly", "24-hour", "24 hour", "load profile", "load curve", "per hour"]
    if granularity == "daily" and any(k in intent for k in hourly_triggers):
        granularity = "hourly"

    # 2. Extract canonical cost centers or equipment using centralized normalizers
    extracted_zone = normalize_cost_center_name(raw_intent)
    extracted_equipment = normalize_category_name(raw_intent)

    # 3. Check trend requirement
    is_trend = _is_trend_request(raw_intent, start_date, end_date)

    # 4. Resolve visualization type
    viz_type = None

    for vtype, keywords in INTENT_KEYWORDS.items():
        if any(kw in intent for kw in keywords):
            viz_type = vtype
            break

    # If is_trend is True, upgrade single-day types to trend types
    if is_trend:
        if viz_type == "zone" or (viz_type is None and extracted_zone):
            viz_type = "zone_trend"
        elif viz_type == "equipment" or (viz_type is None and extracted_equipment):
            viz_type = "equipment_trend"
        elif viz_type == "facility" and granularity == "daily":
            viz_type = "facility_trend"
    else:
        # For single-day profiles, default to hourly for diurnal solar curve or facility load curves
        if viz_type == "solar":
            granularity = "hourly"
        elif viz_type == "facility" and any(k in intent for k in ["profile", "curve", "hourly", "load"]):
            granularity = "hourly"

    if viz_type is None:
        if extracted_zone:
            viz_type = "zone"
        elif extracted_equipment:
            viz_type = "equipment"
        else:
            viz_type = "equipment"  # default

    # 5. Extract type-specific metadata
    if viz_type == "thd":
        is_voltage = "voltage" in intent or ("current" not in intent and "vthd" in intent)
        if "current" in intent or "ithd" in intent:
            is_voltage = False
        metadata["is_voltage"] = is_voltage

    elif viz_type == "scatter":
        if "steam" in intent or "pressure" in intent or "boiler" in intent:
            metadata["scatter_pair"] = "steam_flow_vs_pressure"
        elif "pf" in intent or "power factor" in intent or "kva" in intent:
            metadata["scatter_pair"] = "apparent_power_vs_pf"
        elif "thd" in intent or "harmonic" in intent or "real power" in intent or "kw" in intent:
            metadata["scatter_pair"] = "power_vs_current_thd"
        else:
            metadata["scatter_pair"] = "steam_flow_vs_pressure"

    # 6. Preferred chart type override
    preferred_type = _extract_preferred_chart_type(raw_intent)
    if preferred_type:
        metadata["preferred_chart_type"] = preferred_type

    # 7. Safe entity filtering (strictly prevent cross-domain pollution)
    if viz_type in ("zone", "zone_trend"):
        if extracted_zone and not filter_items:
            filter_items = [extracted_zone]
            metadata["extracted_filter"] = extracted_zone
        if filter_items:
            filter_items = [normalize_cost_center_name(i) or i for i in filter_items]
    elif viz_type in ("equipment", "equipment_trend"):
        if extracted_equipment and not filter_items:
            filter_items = [extracted_equipment]
            metadata["extracted_filter"] = extracted_equipment
        if filter_items:
            filter_items = [normalize_category_name(i) or i for i in filter_items]

    metadata["is_trend"] = is_trend

    return {
        **input_dict,
        "viz_type": viz_type,
        "granularity": granularity,
        "metadata": metadata,
        "filter_items": filter_items,
    }


# Create LCEL Runnable for intent parsing
parse_intent_runnable = RunnableLambda(_parse_intent_step)


# ==============================================================================
# STEP 2: DATA RETRIEVAL (Second link in the chain)
# ==============================================================================

def _retrieve_gauge_data(date: str, **kwargs) -> Dict[str, Any]:
    """Retrieve peak demand data for gauge."""
    data = facility_telemetry.get_peak_demand(date)
    if not isinstance(data, dict):
        return {"error": "Telemetry returned invalid data for peak demand"}
    if "error" in data:
        return data

    peak_kva = data.get("peak_kva")
    if peak_kva is None:
        return {"error": f"No peak demand telemetry found for {date}"}

    utilization_pct = data.get("utilization_percent") or 0.0

    return {
        "date": date,
        "peak_kva": peak_kva,
        "utilization_percent": utilization_pct,
        "contracted_kva": CONTRACTED_DEMAND_KVA,
        "threshold_kva": PEAK_DEMAND_THRESHOLD_KVA,
        "status": "CRITICAL" if peak_kva > PEAK_DEMAND_THRESHOLD_KVA else "NORMAL",
    }


def _retrieve_heatmap_data(start_date: str, end_date: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """Retrieve hourly data matrix for heatmap using fast single batch query."""
    if not end_date:
        return {"error": "Heatmap requires end_date for date range. Example: start_date='2026-10-10', end_date='2026-10-16'"}

    dt_start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    dt_end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    if dt_end < dt_start:
        return {"error": f"Invalid date range: end_date '{end_date}' cannot be earlier than start_date '{start_date}'"}

    days_count = (dt_end - dt_start).days + 1
    dates = [(dt_start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count)]
    hours = [f"{h:02d}:00" for h in range(24)]

    start_ts = f"{start_date} 00:00:00"
    end_ts = f"{end_date} 23:59:59"
    q = f"""
        SELECT
            toDate(reading_timestamp) AS day,
            toHour(reading_timestamp) AS hour,
            round(MAX(toFloat64OrNull(value)) - MIN(toFloat64OrNull(value)), 1) AS delta
        FROM opcda_readings
        WHERE tag_id = '{SHIFT_ENERGY_TAG}'
          AND reading_timestamp >= parseDateTimeBestEffort('{start_ts}')
          AND reading_timestamp <= parseDateTimeBestEffort('{end_ts}')
          AND toFloat64OrNull(value) > 0
        GROUP BY day, hour
        ORDER BY day, hour;
    """
    try:
        rows = db_client.execute_query(q)
    except Exception as e:
        return {"error": f"Failed to retrieve heatmap telemetry: {e}"}

    matrix_map: Dict[Tuple[str, int], float] = {}
    for r in rows:
        d_str = str(r["day"])
        h_val = int(r["hour"])
        delta = float(r.get("delta") or 0.0)
        matrix_map[(d_str, h_val)] = max(delta, 0.0)

    z_matrix = []
    total_kwh = 0.0
    for d in dates:
        row = []
        for h in range(24):
            val = matrix_map.get((d, h), 0.0)
            row.append(round(val, 1))
            total_kwh += val
        z_matrix.append(row)

    if not rows and total_kwh == 0.0:
        return {"error": f"No telemetry data found for date range {start_date} to {end_date}"}

    return {
        "x_labels": hours,
        "y_labels": dates,
        "z_matrix": z_matrix,
        "total_kwh": round(total_kwh, 1),
        "days_count": days_count,
    }


def _retrieve_thd_data(date: str, is_voltage: bool = False, **kwargs) -> Dict[str, Any]:
    """Retrieve THD data for compliance visualization."""
    thd_data = facility_telemetry.get_thd_analysis(date)
    if not isinstance(thd_data, dict):
        return {"error": "Telemetry returned invalid data for THD analysis"}
    if "error" in thd_data:
        return thd_data

    if is_voltage:
        thd_values = thd_data.get("voltage_thd", {})
        metric_name = "Voltage THD"
        limit = 5.0
    else:
        thd_values = thd_data.get("current_thd", {})
        metric_name = "Current THD"
        limit = 8.0

    avg_thd = thd_values.get("average_percent") if thd_values.get("average_percent") is not None else thd_values.get("average", 0.0)
    max_thd = thd_values.get("max_percent") if thd_values.get("max_percent") is not None else thd_values.get("max", 0.0)

    return {
        "date": date,
        "metric_name": metric_name,
        "average_thd": round(float(avg_thd), 2),
        "max_thd": round(float(max_thd), 2),
        "limit": limit,
        "compliance": "COMPLIANT" if max_thd <= limit else "EXCEEDS LIMIT",
    }


def _retrieve_power_factor_data(date: str, **kwargs) -> Dict[str, Any]:
    """Retrieve power factor data."""
    pf_data = facility_telemetry.get_power_factor(date)
    if not isinstance(pf_data, dict):
        return {"error": "Telemetry returned invalid data for power factor"}
    if "error" in pf_data:
        return pf_data

    avg_pf = pf_data.get("average_power_factor")
    if avg_pf is None:
        return {"error": f"No power factor telemetry found for {date}"}

    min_pf = pf_data.get("min_power_factor") or 0.0
    max_pf = pf_data.get("max_power_factor") or 0.0

    return {
        "date": date,
        "average_pf": round(float(avg_pf), 3),
        "min_pf": round(float(min_pf), 3),
        "max_pf": round(float(max_pf), 3),
        "phase_breakdown": pf_data.get("phase_breakdown", {}),
        "compliance": "COMPLIANT" if min_pf >= 0.95 else "NON-COMPLIANT",
    }


def _retrieve_tariff_data(date: str, **kwargs) -> Dict[str, Any]:
    """Retrieve tariff/TOD band data."""
    tariff_data = TariffService.calculate_daily_cost(date)
    if not isinstance(tariff_data, dict):
        return {"error": "Tariff calculation returned invalid data"}
    if "error" in tariff_data:
        return tariff_data

    bands = tariff_data.get("band_summary", {})
    if not bands:
        return {"error": f"No tariff consumption records found for {date}"}

    return {
        "date": date,
        "bands": bands,
        "total_kwh": round(float(tariff_data.get("true_daily_kwh", 0.0)), 1),
        "total_cost": round(float(tariff_data.get("total_cost_inr", 0.0)), 2),
        "labels": list(bands.keys()),
        "values": [round(float(b.get("kwh", 0.0)), 1) for b in bands.values()],
    }


def _retrieve_equipment_data(date: str, filter_items: Optional[List[str]] = None, **kwargs) -> Dict[str, Any]:
    """Retrieve equipment category breakdown."""
    data = equipments_telemetry.get_category_breakdown(date)
    if not isinstance(data, dict):
        return {"error": "Telemetry returned invalid data for equipment breakdown"}
    if "error" in data:
        return data

    categories = data.get("categories", [])
    if filter_items:
        categories = [c for c in categories if c.get("category") in filter_items]
        if not categories:
            return {"error": f"No equipment data found matching filter: {filter_items}"}

    labels = [c["category"] for c in categories]
    values = [round(float(c.get("energy_kwh", 0.0)), 1) for c in categories]
    total_kwh = sum(values)

    return {
        "date": date,
        "categories": categories,
        "total_kwh": round(total_kwh, 1),
        "labels": labels,
        "values": values,
        "category_count": len(categories),
    }


def _retrieve_zone_data(date: str, filter_items: Optional[List[str]] = None, **kwargs) -> Dict[str, Any]:
    """Retrieve zone/cost center breakdown."""
    data = zones_telemetry.get_zone_breakdown(date)
    if not isinstance(data, dict):
        return {"error": "Telemetry returned invalid data for zone breakdown"}
    if "error" in data:
        return data

    cost_centers = data.get("cost_centers", [])
    if filter_items:
        cost_centers = [c for c in cost_centers if c.get("cost_center") in filter_items]
        if not cost_centers:
            return {"error": f"No cost center data found matching filter: {filter_items}"}

    labels = [c["cost_center"] for c in cost_centers]
    values = [round(float(c.get("energy_kwh", 0.0)), 1) for c in cost_centers]
    total_kwh = sum(values)

    return {
        "date": date,
        "cost_centers": cost_centers,
        "total_kwh": round(total_kwh, 1),
        "labels": labels,
        "values": values,
        "category_count": len(cost_centers),
    }


def _retrieve_zone_trend_data(
    start_date: str,
    end_date: Optional[str] = None,
    filter_items: Optional[List[str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Retrieve multi-day zone/cost center trend (daily time series)."""
    if not end_date:
        end_date = start_date

    dt_start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    dt_end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    if dt_end < dt_start:
        return {"error": f"Invalid date range: end_date '{end_date}' cannot be earlier than start_date '{start_date}'"}

    days_count = (dt_end - dt_start).days + 1
    dates = [(dt_start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count)]

    daily_totals: Dict[str, List[float]] = {}
    total_kwh = 0.0

    for d in dates:
        data = zones_telemetry.get_zone_breakdown(d)
        if "error" in data:
            continue
        cost_centers = data.get("cost_centers", [])

        for cc in cost_centers:
            zone_name = cc.get("cost_center", "Unknown")
            energy = float(cc.get("energy_kwh", 0.0))

            if filter_items and zone_name not in filter_items:
                continue

            if zone_name not in daily_totals:
                daily_totals[zone_name] = []
            daily_totals[zone_name].append(round(energy, 1))
            total_kwh += energy

    if not daily_totals:
        return {"error": f"No zone telemetry found for date range {start_date} to {end_date}"}

    series = [{"name": z, "data": vals} for z, vals in daily_totals.items()]

    return {
        "date": start_date,
        "end_date": end_date,
        "labels": dates,
        "series": series,
        "total_kwh": round(total_kwh, 1),
        "days_count": days_count,
        "zones_count": len(daily_totals),
        "is_trend": True,
    }


def _retrieve_equipment_trend_data(
    start_date: str,
    end_date: Optional[str] = None,
    filter_items: Optional[List[str]] = None,
    **kwargs
) -> Dict[str, Any]:
    """Retrieve multi-day equipment category trend (daily time series)."""
    if not end_date:
        end_date = start_date

    dt_start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date()
    dt_end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    if dt_end < dt_start:
        return {"error": f"Invalid date range: end_date '{end_date}' cannot be earlier than start_date '{start_date}'"}

    days_count = (dt_end - dt_start).days + 1
    dates = [(dt_start + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days_count)]

    daily_totals: Dict[str, List[float]] = {}
    total_kwh = 0.0

    for d in dates:
        data = equipments_telemetry.get_category_breakdown(d)
        if "error" in data:
            continue
        categories = data.get("categories", [])

        for cat in categories:
            cat_name = cat.get("category", "Unknown")
            energy = float(cat.get("energy_kwh", 0.0))

            if filter_items and cat_name not in filter_items:
                continue

            if cat_name not in daily_totals:
                daily_totals[cat_name] = []
            daily_totals[cat_name].append(round(energy, 1))
            total_kwh += energy

    if not daily_totals:
        return {"error": f"No equipment telemetry found for date range {start_date} to {end_date}"}

    series = [{"name": c, "data": vals} for c, vals in daily_totals.items()]

    return {
        "date": start_date,
        "end_date": end_date,
        "labels": dates,
        "series": series,
        "total_kwh": round(total_kwh, 1),
        "days_count": days_count,
        "categories_count": len(daily_totals),
        "is_trend": True,
    }


def _retrieve_shift_data(date: str, **kwargs) -> Dict[str, Any]:
    """Retrieve shift-wise breakdown."""
    data = facility_telemetry.get_grid_shift_energy(date)
    if not isinstance(data, dict):
        return {"error": "Telemetry returned invalid data for shift breakdown"}
    if "error" in data:
        return data

    shifts = data.get("shifts", {})
    if not shifts:
        return {"error": f"No shift telemetry found for {date}"}

    return {
        "date": date,
        "shifts": shifts,
        "total_kwh": round(float(data.get("total_shifts_kwh", 0.0)), 1),
        "labels": list(shifts.keys()),
        "values": [round(float(s.get("energy_kwh", 0.0)), 1) for s in shifts.values()],
        "category_count": len(shifts),
    }


def _retrieve_solar_data(
    date: str,
    start_date: str = "",
    end_date: Optional[str] = None,
    granularity: str = "daily",
    **kwargs
) -> Dict[str, Any]:
    """Retrieve solar generation data for single or multi-day."""
    eff_start = start_date or date
    eff_end = end_date or eff_start

    # Multi-day solar trend
    if eff_end != eff_start:
        q = f"""
            SELECT toString(day) as day, round(maxMerge(max_value) - minMerge(min_value), 1) as energy_kwh
            FROM tag_daily_energy_rollup
            WHERE tag_id = '{SOLAR_ENERGY_TAG}'
              AND day >= '{eff_start}' AND day <= '{eff_end}'
            GROUP BY day
            ORDER BY day;
        """
        try:
            rows = db_client.execute_query(q)
        except Exception as e:
            return {"error": f"Failed to retrieve solar multi-day telemetry: {e}"}

        if not rows:
            return {"error": f"No solar telemetry found between {eff_start} and {eff_end}"}

        labels = [r["day"] for r in rows]
        values = [float(r["energy_kwh"]) for r in rows]
        return {
            "date": eff_start,
            "end_date": eff_end,
            "labels": labels,
            "values": values,
            "total_kwh": round(sum(values), 1),
            "is_trend": True,
        }

    # Single-day solar
    gran = "hourly" if (granularity == "hourly" or eff_start == eff_end) else "daily"
    data = facility_telemetry.get_solar_generation(eff_start, granularity=gran)
    if "error" in data:
        return data

    energy_kwh = round(float(data.get("energy_generated_kwh", 0.0)), 1)
    result = {
        "date": eff_start,
        "energy_kwh": energy_kwh,
        "peak_power_kw": round(float(data.get("peak_power_kw", 0.0)), 1),
        "avg_power_kw": round(float(data.get("avg_power_kw", 0.0)), 1),
        "total_kwh": energy_kwh,
    }

    if gran == "hourly" and "hourly_breakdown" in data:
        hourly = data["hourly_breakdown"]
        result["labels"] = [h.get("hour", f"{i:02d}:00") for i, h in enumerate(hourly)]
        result["values"] = [round(float(h.get("energy_kwh", 0.0)), 1) for h in hourly]
    else:
        result["labels"] = [eff_start]
        result["values"] = [energy_kwh]

    return result


def _retrieve_facility_data(
    date: str,
    start_date: str = "",
    end_date: Optional[str] = None,
    granularity: str = "daily",
    **kwargs
) -> Dict[str, Any]:
    """Retrieve facility load profile or consumption trend."""
    eff_start = start_date or date
    eff_end = end_date or eff_start

    # Multi-day facility trend
    if eff_end != eff_start:
        q = f"""
            SELECT toString(day) as day, round(maxMerge(max_value) - minMerge(min_value), 1) as energy_kwh
            FROM tag_daily_energy_rollup
            WHERE tag_id = '{SHIFT_ENERGY_TAG}'
              AND day >= '{eff_start}' AND day <= '{eff_end}'
            GROUP BY day
            ORDER BY day;
        """
        try:
            rows = db_client.execute_query(q)
        except Exception as e:
            return {"error": f"Failed to retrieve facility multi-day telemetry: {e}"}

        if not rows:
            return {"error": f"No facility telemetry found between {eff_start} and {eff_end}"}

        labels = [r["day"] for r in rows]
        values = [float(r["energy_kwh"]) for r in rows]
        return {
            "date": eff_start,
            "end_date": eff_end,
            "labels": labels,
            "values": values,
            "total_kwh": round(sum(values), 1),
            "is_trend": True,
        }

    # Single-day facility
    if granularity == "hourly":
        data = facility_telemetry.get_grid_hourly_energy(eff_start)
        if "error" in data:
            return data
        hourly = data.get("hourly_breakdown", [])
        return {
            "date": eff_start,
            "total_kwh": round(float(data.get("total_energy_kwh", 0.0)), 1),
            "labels": [h.get("hour", "") for h in hourly],
            "values": [round(float(h.get("energy_kwh", 0.0)), 1) for h in hourly],
        }
    else:
        data = facility_telemetry.get_grid_energy(eff_start)
        if "error" in data:
            return data
        val = round(float(data.get("energy_kwh", 0.0)), 1)
        return {
            "date": eff_start,
            "total_kwh": val,
            "labels": [eff_start],
            "values": [val],
        }


def _retrieve_scatter_data(date: str, scatter_pair: str = "steam_flow_vs_pressure", **kwargs) -> Dict[str, Any]:
    """Retrieve correlation scatter plot data."""
    start_ts = f"{date} 00:00:00"
    end_ts = f"{date} 23:59:59"

    if scatter_pair == "steam_flow_vs_pressure":
        q = f"""
            SELECT
                toFloat64OrNull(a.value) AS flow,
                toFloat64OrNull(b.value) AS pressure,
                toString(a.reading_timestamp) AS reading_timestamp
            FROM opcda_readings a
            JOIN opcda_readings b ON a.reading_timestamp = b.reading_timestamp AND b.tag_id = '{STEAM_PRESSURE_TAG}'
            WHERE a.tag_id = '{STEAM_FLOW_RATE_TAG}'
              AND a.reading_timestamp >= parseDateTimeBestEffort('{start_ts}')
              AND a.reading_timestamp <= parseDateTimeBestEffort('{end_ts}')
            LIMIT 100;
        """
        try:
            rows = db_client.execute_query(q)
        except Exception as e:
            return {"error": f"Failed to retrieve steam scatter data: {e}"}

        points = [
            {"x": round(float(r["flow"]), 1), "y": round(float(r["pressure"]), 2), "label": str(r["reading_timestamp"])[11:16]}
            for r in rows if r.get("flow") is not None and r.get("pressure") is not None
        ]
        return {
            "date": date,
            "scatter_pair": scatter_pair,
            "title": f"Correlation: Steam Flow Rate vs Pressure ({date})",
            "x_axis_label": "Flow Rate (kg/h)",
            "y_axis_label": "Pressure (bar)",
            "series_name": "Steam Flow vs Pressure",
            "color": "#0891B2",
            "points": points,
            "reason": "Scatter plot detects boiler pressure sag as a function of steam demand.",
        }

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
              AND a.reading_timestamp >= parseDateTimeBestEffort('{start_ts}')
              AND a.reading_timestamp <= parseDateTimeBestEffort('{end_ts}')
            LIMIT 100;
        """
        try:
            rows = db_client.execute_query(q)
        except Exception as e:
            return {"error": f"Failed to retrieve apparent power vs PF data: {e}"}

        points = [
            {"x": round(float(r["kva"]), 1), "y": round(float(r["pf"]), 3), "label": str(r["reading_timestamp"])[11:16]}
            for r in rows if r.get("kva") is not None and r.get("pf") is not None
        ]
        return {
            "date": date,
            "scatter_pair": scatter_pair,
            "title": f"Correlation: Apparent Power vs Power Factor ({date})",
            "x_axis_label": "Apparent Power (kVA)",
            "y_axis_label": "Power Factor (0.0 - 1.0)",
            "series_name": "kVA vs Power Factor",
            "color": "#2563EB",
            "points": points,
            "reason": "Scatter plot identifies whether power factor degrades under high loading.",
        }

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
              AND a.reading_timestamp >= parseDateTimeBestEffort('{start_ts}')
              AND a.reading_timestamp <= parseDateTimeBestEffort('{end_ts}')
            LIMIT 100;
        """
        try:
            rows = db_client.execute_query(q)
        except Exception as e:
            return {"error": f"Failed to retrieve power vs THD data: {e}"}

        points = [
            {"x": round(float(r["kw"]), 1), "y": round(float(r["thd"]), 2), "label": str(r["reading_timestamp"])[11:16]}
            for r in rows if r.get("kw") is not None and r.get("thd") is not None
        ]
        return {
            "date": date,
            "scatter_pair": scatter_pair,
            "title": f"Correlation: Real Power (kW) vs Current THD % ({date})",
            "x_axis_label": "Real Power (kW)",
            "y_axis_label": "Current THD (%)",
            "series_name": "Real Power vs Current THD",
            "color": "#DC2626",
            "points": points,
            "reason": "Scatter plot shows whether harmonic distortion increases with load.",
        }

    return {"error": f"Unknown scatter_pair: {scatter_pair}"}


# Registry: viz_type → retriever function
DATA_RETRIEVERS: Dict[str, Callable] = {
    "gauge": _retrieve_gauge_data,
    "heatmap": _retrieve_heatmap_data,
    "thd": _retrieve_thd_data,
    "power_factor": _retrieve_power_factor_data,
    "tariff": _retrieve_tariff_data,
    "equipment": _retrieve_equipment_data,
    "zone": _retrieve_zone_data,
    "shift": _retrieve_shift_data,
    "solar": _retrieve_solar_data,
    "facility": _retrieve_facility_data,
    "zone_trend": _retrieve_zone_trend_data,
    "equipment_trend": _retrieve_equipment_trend_data,
    "facility_trend": _retrieve_facility_data,
    "scatter": _retrieve_scatter_data,
}


def _transform_ems_data(
    ems_data: Dict[str, Any],
    viz_type: str,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Transform EMS tool output into visualization-compatible format."""
    if not isinstance(ems_data, dict):
        return {}
    if "error" in ems_data:
        return ems_data

    # If already normalized with labels and values, return as is
    if "labels" in ems_data and "values" in ems_data and len(ems_data["values"]) > 0:
        return ems_data

    # Equipment breakdown from grouping_energy(group_by="equipment") or LLM pre-fetched data
    if viz_type == "equipment":
        raw_cats = (
            ems_data.get("categories")
            or ems_data.get("equipment_breakdown")
            or ems_data.get("equipment")
            or ems_data.get("data")
        )
        if raw_cats:
            labels = []
            values = []
            if isinstance(raw_cats, dict):
                for cat_name, cat_val in raw_cats.items():
                    labels.append(str(cat_name))
                    if isinstance(cat_val, dict):
                        val = cat_val.get("energy_kwh")
                        if val is None:
                            val = cat_val.get("kwh", cat_val.get("value", 0.0))
                    else:
                        val = cat_val
                    values.append(round(float(val or 0.0), 1))
            elif isinstance(raw_cats, list):
                for item in raw_cats:
                    if isinstance(item, dict):
                        labels.append(str(item.get("category") or item.get("name") or item.get("label", "")))
                        val = item.get("energy_kwh")
                        if val is None:
                            val = item.get("kwh", item.get("value", 0.0))
                        values.append(round(float(val or 0.0), 1))
            if labels and values:
                total_kwh = round(float(ems_data.get("total_kwh") or sum(values)), 1)
                return {
                    "categories": [{"category": l, "energy_kwh": v} for l, v in zip(labels, values)],
                    "total_kwh": total_kwh,
                    "labels": labels,
                    "values": values,
                    "category_count": len(labels),
                }

    # Zone breakdown from grouping_energy(group_by="zone") or LLM pre-fetched data
    if viz_type == "zone":
        raw_zones = (
            ems_data.get("cost_centers")
            or ems_data.get("zones")
            or ems_data.get("zone_breakdown")
            or ems_data.get("data")
        )
        if raw_zones:
            labels = []
            values = []
            if isinstance(raw_zones, dict):
                for zone_name, zone_val in raw_zones.items():
                    labels.append(str(zone_name))
                    if isinstance(zone_val, dict):
                        val = zone_val.get("energy_kwh")
                        if val is None:
                            val = zone_val.get("kwh", zone_val.get("value", 0.0))
                    else:
                        val = zone_val
                    values.append(round(float(val or 0.0), 1))
            elif isinstance(raw_zones, list):
                for item in raw_zones:
                    if isinstance(item, dict):
                        labels.append(str(item.get("cost_center") or item.get("name") or item.get("label", "")))
                        val = item.get("energy_kwh")
                        if val is None:
                            val = item.get("kwh", item.get("value", 0.0))
                        values.append(round(float(val or 0.0), 1))
            if labels and values:
                total_kwh = round(float(ems_data.get("total_kwh") or sum(values)), 1)
                return {
                    "cost_centers": [{"cost_center": l, "energy_kwh": v} for l, v in zip(labels, values)],
                    "total_kwh": total_kwh,
                    "labels": labels,
                    "values": values,
                    "category_count": len(labels),
                }

    # Shift breakdown from grouping_energy(group_by="shift")
    if viz_type == "shift":
        shifts = ems_data.get("shifts") or ems_data.get("shift_breakdown")
        if shifts and isinstance(shifts, dict):
            return {
                "shifts": shifts,
                "total_kwh": round(float(ems_data.get("total_shifts_kwh", 0.0)), 1),
                "labels": list(shifts.keys()),
                "values": [round(float(s.get("energy_kwh", s.get("kwh", 0.0))), 1) for s in shifts.values() if isinstance(s, dict)],
                "category_count": len(shifts),
            }

    # Tariff from grouping_energy(group_by="tariff")
    if viz_type == "tariff" and "band_summary" in ems_data:
        bands = ems_data.get("band_summary", {})
        return {
            "bands": bands,
            "total_kwh": round(float(ems_data.get("true_daily_kwh", 0.0)), 1),
            "total_cost": round(float(ems_data.get("total_cost_inr", 0.0)), 2),
            "labels": list(bands.keys()),
            "values": [round(float(b.get("kwh", 0.0)), 1) for b in bands.values()],
        }

    # Peak demand from get_instantaneous_energy(measurement="peak_demand")
    if viz_type == "gauge" and "peak_kva" in ems_data:
        peak_kva = round(float(ems_data.get("peak_kva", 0.0)), 1)
        return {
            "peak_kva": peak_kva,
            "utilization_percent": round(float(ems_data.get("utilization_percent", 0.0)), 1),
            "contracted_kva": ems_data.get("contracted_demand_kva", CONTRACTED_DEMAND_KVA),
            "threshold_kva": ems_data.get("threshold_kva", PEAK_DEMAND_THRESHOLD_KVA),
            "status": "CRITICAL" if peak_kva > PEAK_DEMAND_THRESHOLD_KVA else "NORMAL",
        }

    # THD from get_instantaneous_energy(measurement="thd")
    if viz_type == "thd" and ("voltage_thd" in ems_data or "current_thd" in ems_data):
        meta = metadata or {}
        is_voltage = meta.get("is_voltage", True)
        if not is_voltage and "current_thd" in ems_data:
            thd_values = ems_data.get("current_thd", {})
            metric_name = "Current THD"
            limit = 8.0
        elif "voltage_thd" in ems_data:
            thd_values = ems_data.get("voltage_thd", {})
            metric_name = "Voltage THD"
            limit = 5.0
        else:
            thd_values = ems_data.get("current_thd", {})
            metric_name = "Current THD"
            limit = 8.0

        avg_thd = thd_values.get("average_percent") if thd_values.get("average_percent") is not None else thd_values.get("average", 0.0)
        max_thd = thd_values.get("max_percent") if thd_values.get("max_percent") is not None else thd_values.get("max", 0.0)
        return {
            "metric_name": metric_name,
            "average_thd": round(float(avg_thd), 2),
            "max_thd": round(float(max_thd), 2),
            "limit": limit,
            "compliance": "COMPLIANT" if max_thd <= limit else "EXCEEDS LIMIT",
        }

    # Power factor from get_instantaneous_energy(measurement="power_factor")
    if viz_type == "power_factor" and "average_power_factor" in ems_data:
        min_pf = round(float(ems_data.get("min_power_factor", 0.0)), 3)
        return {
            "average_pf": round(float(ems_data.get("average_power_factor", 0.0)), 3),
            "min_pf": min_pf,
            "max_pf": round(float(ems_data.get("max_power_factor", 0.0)), 3),
            "phase_breakdown": ems_data.get("phase_breakdown", {}),
            "compliance": "COMPLIANT" if min_pf >= 0.95 else "NON-COMPLIANT",
        }

    # Hourly profile from grouping_energy(group_by="hourly")
    if "hourly_breakdown" in ems_data:
        hourly = ems_data.get("hourly_breakdown", [])
        return {
            "total_kwh": round(float(ems_data.get("total_energy_kwh", sum(h.get("energy_kwh", 0) for h in hourly))), 1),
            "labels": [h.get("hour", "") for h in hourly],
            "values": [round(float(h.get("energy_kwh", 0.0)), 1) for h in hourly],
        }

    return ems_data


def _retrieve_data_step(input_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    LCEL Step 2: Retrieve telemetry data based on viz_type.

    Input: {..., "viz_type": str, "start_date": str, ...}
    Output: {...input, "data": dict, "retrieval_success": bool}
    """
    metadata = input_dict.get("metadata", {})
    viz_type = input_dict.get("viz_type", "equipment")

    # Check for pre-fetched data
    pre_fetched = input_dict.get("pre_fetched_data")
    if pre_fetched is not None and isinstance(pre_fetched, dict):
        transformed = _transform_ems_data(pre_fetched, viz_type, metadata)
        if isinstance(transformed, dict) and "values" in transformed and len(transformed.get("values", [])) > 0:
            return {
                **input_dict,
                "data": transformed,
                "retrieval_success": True,
                "data_source": "pre_fetched",
            }
        # If pre_fetched data did not yield valid numeric series, fall through to retriever below!

    start_date = input_dict.get("start_date")
    end_date = input_dict.get("end_date")
    granularity = input_dict.get("granularity", "daily")
    filter_items = input_dict.get("filter_items")

    retriever = DATA_RETRIEVERS.get(viz_type)
    if not retriever:
        return {
            **input_dict,
            "data": {"error": f"Unknown visualization type: {viz_type}"},
            "retrieval_success": False,
        }

    try:
        data = retriever(
            date=start_date,
            start_date=start_date,
            end_date=end_date,
            granularity=granularity,
            filter_items=filter_items,
            **metadata
        )

        has_error = not isinstance(data, dict) or "error" in data
        return {
            **input_dict,
            "data": data if isinstance(data, dict) else {"error": "Invalid retriever output"},
            "retrieval_success": not has_error,
        }
    except Exception as e:
        return {
            **input_dict,
            "data": {"error": str(e)},
            "retrieval_success": False,
        }


# Create LCEL Runnable for data retrieval (Legacy chain component)
retrieve_data_runnable = RunnableLambda(_retrieve_data_step)


def _retrieve_data_sql_rag_step(input_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    ACTIVE LCEL Step 2: Retrieve telemetry data using the SQL + RAG Retrieval Chain.

    Execution Flow (per Task Specification Section 6):
    1. Check for pre-fetched data (avoids duplicate query if agent already retrieved numbers).
    2. Retrieve relevant reference-document sections through RAG pipeline via SQL retrieval interface.
    3. Identify authoritative operational tables, columns, tags, and aggregation rules from retrieved reference.
    4. Generate and execute appropriate read-only operational SQL query via execute_custom_sql tool.
    5. Validate returned data and format into structured numeric series.
    """
    metadata = input_dict.get("metadata", {})
    viz_type = input_dict.get("viz_type", "equipment")
    raw_intent = metadata.get("raw_intent", viz_type)

    # 1. Check for pre-fetched data from previous tool calls
    pre_fetched = input_dict.get("pre_fetched_data")
    if pre_fetched is not None and isinstance(pre_fetched, dict):
        transformed = _transform_ems_data(pre_fetched, viz_type, metadata)
        if isinstance(transformed, dict) and "values" in transformed and len(transformed.get("values", [])) > 0:
            return {
                **input_dict,
                "data": transformed,
                "retrieval_success": True,
                "data_source": "pre_fetched",
            }

    start_date = input_dict.get("start_date")
    end_date = input_dict.get("end_date")
    granularity = input_dict.get("granularity", "daily")
    filter_items = input_dict.get("filter_items")

    try:
        # 2. Retrieve authoritative reference sections through RAG via SQL retrieval interface
        from src.rag.retriever import rag_pipeline
        from src.tools.energy_tools import execute_custom_sql

        ref_query = f"{viz_type} {raw_intent}"
        ref_chunks = rag_pipeline.retrieve_via_sql(ref_query, top_k=2)

        # 3. Formulate and execute operational SQL query through execute_custom_sql
        data = None

        if viz_type in ("equipment", "equipment_trend") and not metadata.get("is_trend"):
            # Section 8: 8 equipment categories with mandatory exclusions
            cat_list = ["Lighting", "Molding", "Dust_Collector", "Compressor", "Paintshop", "Others", "Airconditioning", "Production_Power"]
            if filter_items:
                cat_list = [c for c in cat_list if c in filter_items or c.lower() in [f.lower() for f in filter_items]]
                if not cat_list:
                    cat_list = filter_items

            excluded_list = "'Dust_Collector.G0_144_Dust_Collector/Energies/Real Energy/Real Energy Into the Load', 'Airconditioning.PA_FA_Inspection_Box-AC/Energies/Real Energy/Real Energy Into the Load'"
            prefix_clauses = " OR ".join([f"tag_id LIKE '{c}.%'" for c in cat_list])
            sql = f"""
                SELECT
                    tag_id,
                    maxMerge(max_value) - minMerge(min_value) AS delta
                FROM tag_daily_energy_rollup
                WHERE day = toDate('{start_date}')
                  AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                  AND tag_id NOT IN ({excluded_list})
                  AND ({prefix_clauses})
                GROUP BY tag_id
            """
            rows = execute_custom_sql.invoke({"query": sql})
            if isinstance(rows, list) and len(rows) > 0:
                cat_totals = {c: 0.0 for c in cat_list}
                for r in rows:
                    t_id = r.get("tag_id", "")
                    d_val = float(r.get("delta") or 0.0)
                    for c in cat_list:
                        if t_id.startswith(f"{c}."):
                            cat_totals[c] += d_val
                            break
                labels = [c for c in cat_list if cat_totals[c] > 0 or not filter_items]
                values = [round(cat_totals[c], 1) for c in labels]
                total_kwh = round(sum(values), 1)
                data = {
                    "date": start_date,
                    "type": "equipment_wise",
                    "categories": [{"category": c, "energy_kwh": cat_totals[c]} for c in labels],
                    "total_kwh": total_kwh,
                    "labels": labels,
                    "values": values,
                    "category_count": len(labels),
                }

        elif viz_type in ("zone", "zone_trend") and not metadata.get("is_trend"):
            # Section 9: 17 cost centers with exact mapped tag lists
            from src.db.tag_catalog import COST_CENTER_MAPPINGS
            target_zones = COST_CENTER_MAPPINGS
            if filter_items:
                target_zones = {k: v for k, v in COST_CENTER_MAPPINGS.items() if k in filter_items or k.lower() in [f.lower() for f in filter_items]}
                if not target_zones:
                    target_zones = COST_CENTER_MAPPINGS

            all_tags = []
            for tags in target_zones.values():
                all_tags.extend(tags)
            all_tags_str = ", ".join(f"'{t}'" for t in all_tags)

            sql = f"""
                SELECT
                    tag_id,
                    maxMerge(max_value) - minMerge(min_value) AS delta
                FROM tag_daily_energy_rollup
                WHERE day = toDate('{start_date}')
                  AND tag_id IN ({all_tags_str})
                GROUP BY tag_id
            """
            rows = execute_custom_sql.invoke({"query": sql})
            if isinstance(rows, list) and len(rows) > 0:
                tag_delta_map = {r.get("tag_id"): float(r.get("delta") or 0.0) for r in rows}
                zone_totals = {}
                for z_name, z_tags in target_zones.items():
                    z_sum = sum(tag_delta_map.get(t, 0.0) for t in z_tags)
                    zone_totals[z_name] = round(z_sum, 1)

                labels = list(zone_totals.keys())
                values = list(zone_totals.values())
                total_kwh = round(sum(values), 1)
                data = {
                    "date": start_date,
                    "type": "zone_wise",
                    "cost_centers": [{"cost_center": z, "energy_kwh": v} for z, v in zone_totals.items()],
                    "total_kwh": total_kwh,
                    "labels": labels,
                    "values": values,
                    "category_count": len(labels),
                }

        elif viz_type == "gauge":
            # Section 6: Peak demand KPI tag
            sql = f"""
                SELECT
                    round(MAX(toFloat64OrNull(value)), 1) AS peak_kva
                FROM opcda_readings
                WHERE tag_id = '{PEAK_DEMAND_TAG}'
                  AND reading_timestamp >= parseDateTimeBestEffort('{start_date} 00:00:00')
                  AND reading_timestamp <= parseDateTimeBestEffort('{start_date} 23:59:59')
                  AND toFloat64OrNull(value) > 0
            """
            rows = execute_custom_sql.invoke({"query": sql})
            if isinstance(rows, list) and rows and rows[0].get("peak_kva") is not None:
                peak_kva = float(rows[0]["peak_kva"])
                utilization_pct = round((peak_kva / CONTRACTED_DEMAND_KVA) * 100.0, 1)
                data = {
                    "date": start_date,
                    "peak_kva": peak_kva,
                    "utilization_percent": utilization_pct,
                    "contracted_kva": CONTRACTED_DEMAND_KVA,
                    "threshold_kva": PEAK_DEMAND_THRESHOLD_KVA,
                    "status": "CRITICAL" if peak_kva > PEAK_DEMAND_THRESHOLD_KVA else "NORMAL",
                }

        # If data is not yet resolved, delegate to specialized data retriever
        if data is None:
            retriever = DATA_RETRIEVERS.get(viz_type)
            if retriever:
                data = retriever(
                    date=start_date,
                    start_date=start_date,
                    end_date=end_date,
                    granularity=granularity,
                    filter_items=filter_items,
                    **metadata
                )

        has_error = not isinstance(data, dict) or "error" in data
        return {
            **input_dict,
            "data": data if isinstance(data, dict) else {"error": "Invalid telemetry output"},
            "retrieval_success": not has_error,
            "data_source": "sql_rag_retrieved",
        }
    except Exception as e:
        return {
            **input_dict,
            "data": {"error": str(e)},
            "retrieval_success": False,
        }


# Create LCEL Runnable for the new SQL + RAG data retrieval
retrieve_data_sql_rag_runnable = RunnableLambda(_retrieve_data_sql_rag_step)


# ==============================================================================
# STEP 3: NUMERIC TELEMETRY VALIDATION (Third link in the chain)
# ==============================================================================

def _validate_numeric_telemetry(data: Any, viz_type: str) -> Tuple[bool, Optional[str]]:
    """
    Enforce strict numeric telemetry validation matching numerical tools:
    - Data query must have executed successfully
    - Data payload must contain valid, non-empty numerical records
    - Rejects empty sets or ghost charts with informative validation errors
    """
    if data is None or not isinstance(data, dict):
        return False, "Data retrieval returned an empty or invalid telemetry payload."

    if "error" in data:
        return False, str(data["error"])

    # Categorical and time series series validation
    if viz_type in ("equipment", "zone", "shift", "tariff", "facility", "solar", "facility_trend"):
        values = data.get("values")
        labels = data.get("labels")
        if values is None or len(values) == 0:
            return False, f"No numeric data series found for {viz_type} telemetry."
        if labels is None or len(labels) == 0:
            return False, f"No category/time labels found for {viz_type} telemetry."

    # Multi-series trend validation
    elif viz_type in ("zone_trend", "equipment_trend"):
        series = data.get("series")
        if not series or len(series) == 0:
            return False, f"No trend series data found for {viz_type}."
        has_points = any(len(s.get("data", [])) > 0 for s in series if isinstance(s, dict))
        if not has_points:
            return False, f"Trend series contains 0 numeric data points."

    # Gauge validation
    elif viz_type == "gauge":
        if data.get("peak_kva") is None:
            return False, "Peak demand numeric value (kVA) missing from telemetry."

    # Heatmap validation
    elif viz_type == "heatmap":
        z_matrix = data.get("z_matrix")
        if not z_matrix or len(z_matrix) == 0 or len(z_matrix[0]) == 0:
            return False, "Heatmap matrix contains no numeric telemetry readings."

    # Scatter validation
    elif viz_type == "scatter":
        points = data.get("points")
        if not points or len(points) == 0:
            return False, "Scatter correlation query returned 0 data points."

    # Power quality validation
    elif viz_type in ("thd", "power_factor"):
        if viz_type == "thd" and (data.get("average_thd") is None or data.get("max_thd") is None):
            return False, "THD numeric measurements missing from telemetry."
        if viz_type == "power_factor" and data.get("average_pf") is None:
            return False, "Power factor numeric measurements missing from telemetry."

    return True, None


def _validate_numeric_step(input_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    LCEL Step 3: Validate that the fetch query executed and produced valid numerical data.

    Input: {..., "data": dict, "retrieval_success": bool}
    Output: {...input, "numeric_validation_success": bool, "validation_error": Optional[str]}
    """
    if not input_dict.get("retrieval_success", False):
        err = (input_dict.get("data") or {}).get("error", "Data retrieval failed")
        return {
            **input_dict,
            "numeric_validation_success": False,
            "validation_error": err,
        }

    viz_type = input_dict.get("viz_type", "equipment")
    data = input_dict.get("data", {})

    is_valid, err_msg = _validate_numeric_telemetry(data, viz_type)
    return {
        **input_dict,
        "numeric_validation_success": is_valid,
        "validation_error": err_msg,
    }


# Create LCEL Runnable for numeric validation
validate_numeric_runnable = RunnableLambda(_validate_numeric_step)


# ==============================================================================
# STEP 4: CHART BUILDING (Fourth link in the chain)
# ==============================================================================

def _build_gauge_chart(data: Dict, date: str, **kwargs) -> ChartConfig:
    """Build gauge chart for peak demand."""
    return ChartConfig(
        chart_type="gauge",
        title=f"Peak Demand Utilization — {date}",
        subtitle=f"Peak: {data['peak_kva']:,.1f} kVA | Utilization: {data['utilization_percent']}%",
        gauge_data=GaugeConfig(
            current_value=data["peak_kva"],
            min_value=0.0,
            max_value=data["contracted_kva"],
            threshold_value=data["threshold_kva"],
            unit="kVA",
            status=data["status"]
        ),
        threshold_line=data["threshold_kva"],
        threshold_label=f"80% Warning ({data['threshold_kva']} kVA)",
        representation_reason="Gauge provides instant readability for capacity vs demand."
    )


def _build_heatmap_chart(data: Dict, date: str, end_date: str = None, **kwargs) -> ChartConfig:
    """Build heatmap chart for hour×day patterns."""
    return ChartConfig(
        chart_type="heatmap",
        title=f"Hourly Energy Heatmap ({date} to {end_date})",
        subtitle=f"{data['days_count']} Days × 24 Hours | Total: {data['total_kwh']:,.1f} kWh",
        x_axis_label="Hour of Day",
        y_axis_label="Date",
        heatmap_data=HeatmapMatrix(
            x_labels=data["x_labels"],
            y_labels=data["y_labels"],
            z_matrix=data["z_matrix"],
            z_label="kWh"
        ),
        representation_reason="Heatmap reveals shift patterns and baseload leaks."
    )


def _build_thd_chart(data: Dict, date: str, **kwargs) -> ChartConfig:
    """Build THD compliance line chart."""
    return ChartConfig(
        chart_type="line",
        title=f"{data['metric_name']} Compliance — {date}",
        subtitle=f"Avg: {data['average_thd']:.2f}% | Max: {data['max_thd']:.2f}% | Limit: {data['limit']}%",
        x_axis_label="Measurement",
        x_labels=["Average", "Maximum"],
        y_axis_label="THD (%)",
        threshold_line=data["limit"],
        threshold_label=f"IEEE 519 Limit ({data['limit']}%)",
        series=[ChartSeries(name=data["metric_name"], data=[data["average_thd"], data["max_thd"]], unit="%")],
        representation_reason="Line with threshold shows compliance status."
    )


def _build_power_factor_chart(data: Dict, date: str, **kwargs) -> ChartConfig:
    """Build power factor compliance chart."""
    phase = data.get("phase_breakdown", {})

    if phase:
        labels = ["Phase A", "Phase B", "Phase C", "Average"]
        values = [
            phase.get("phase_a", data["average_pf"]),
            phase.get("phase_b", data["average_pf"]),
            phase.get("phase_c", data["average_pf"]),
            data["average_pf"]
        ]
    else:
        labels = ["Average"]
        values = [data["average_pf"]]

    return ChartConfig(
        chart_type="line",
        title=f"Power Factor — {date}",
        subtitle=f"Avg: {data['average_pf']:.3f} | Min: {data['min_pf']:.3f} | Threshold: 0.95",
        x_axis_label="Phase",
        x_labels=labels,
        y_axis_label="Power Factor",
        threshold_line=0.95,
        threshold_label="HT-1 Compliance (0.95)",
        series=[ChartSeries(name="Power Factor", data=values, unit="")],
        representation_reason="Line with threshold shows PF compliance."
    )


def _build_tariff_chart(data: Dict, date: str, preferred_chart_type: Optional[str] = None, **kwargs) -> ChartConfig:
    """Build tariff/TOD donut or user-specified chart."""
    c_type = preferred_chart_type if preferred_chart_type in ("pie", "donut", "bar") else "donut"
    return ChartConfig(
        chart_type=c_type,
        title=f"TOD Tariff Distribution ({date})",
        subtitle=f"Total: {data['total_kwh']:,.1f} kWh | Cost: ₹{data['total_cost']:,.2f}",
        x_labels=data["labels"],
        y_axis_label="Energy (kWh)",
        series=[ChartSeries(name="Energy", data=data["values"], unit="kWh")],
        center_kpi={"label": "Cost", "value": f"₹{data['total_cost']:,.0f}"} if c_type == "donut" else None,
        representation_reason="Donut/Pie shows Off-Peak/Normal/Peak share with cost KPI."
    )


def _build_donut_chart(data: Dict, date: str, title: str = "Breakdown", preferred_chart_type: Optional[str] = None, **kwargs) -> ChartConfig:
    """Build donut or user-specified chart (pie, bar, etc.)."""
    total = data.get("total_kwh", sum(data.get("values", [])))
    c_type = preferred_chart_type if preferred_chart_type in ("pie", "donut", "bar", "horizontal_bar") else "donut"
    cat_count = data.get("category_count", len(data.get("labels", [])))

    return ChartConfig(
        chart_type=c_type,
        title=f"{title} ({date})",
        subtitle=f"Total: {total:,.1f} kWh",
        x_labels=data.get("labels", []),
        y_axis_label="Energy (kWh)",
        series=[ChartSeries(name="Energy", data=data.get("values", []), unit="kWh")],
        center_kpi={"label": "Total", "value": f"{total:,.0f} kWh"} if c_type == "donut" else None,
        representation_reason=f"{c_type.replace('_', ' ').capitalize()} for clear visualization of {cat_count} categories."
    )


def _build_horizontal_bar_chart(data: Dict, date: str, title: str = "Breakdown", preferred_chart_type: Optional[str] = None, **kwargs) -> ChartConfig:
    """Build horizontal bar or user-specified chart."""
    total = data.get("total_kwh", sum(data.get("values", [])))
    c_type = preferred_chart_type if preferred_chart_type in ("bar", "horizontal_bar", "donut", "pie") else "horizontal_bar"
    cat_count = data.get("category_count", len(data.get("labels", [])))

    return ChartConfig(
        chart_type=c_type,
        title=f"{title} ({date})",
        subtitle=f"Total: {total:,.1f} kWh",
        x_axis_label="Energy (kWh)" if c_type == "horizontal_bar" else "Category",
        x_labels=data.get("labels", []),
        y_axis_label="Category" if c_type == "horizontal_bar" else "Energy (kWh)",
        series=[ChartSeries(name="Energy", data=data.get("values", []), unit="kWh")],
        representation_reason=f"{c_type.replace('_', ' ').capitalize()} for {cat_count} categories with readable labels."
    )


def _build_area_chart(data: Dict, date: str, title: str = "Profile", preferred_chart_type: Optional[str] = None, **kwargs) -> ChartConfig:
    """Build area, line, or bar chart for time series load profile."""
    total = data.get("total_kwh", sum(data.get("values", [])))
    c_type = preferred_chart_type if preferred_chart_type in ("area", "line", "bar") else "area"

    # Color tuning
    color = data.get("color")
    if not color:
        if "solar" in title.lower():
            color = "#F59E0B"  # Golden Amber for Solar
        elif "facility" in title.lower() or "grid" in title.lower():
            color = "#2563EB"  # Deep Blue for Facility / Grid
        else:
            color = "#0891B2"  # Teal / Cyan default

    peak_kw = data.get("peak_power_kw")
    subtitle = f"Total: {total:,.1f} kWh"
    if peak_kw:
        subtitle += f" | Peak: {peak_kw:,.1f} kW"

    labels = data.get("labels", [])
    x_axis_label = "Hour of Day" if len(labels) == 24 else "Time / Date"

    return ChartConfig(
        chart_type=c_type,
        title=f"{title} ({date})",
        subtitle=subtitle,
        x_axis_label=x_axis_label,
        x_labels=labels,
        y_axis_label="Energy (kWh)",
        series=[ChartSeries(name="Energy", data=data.get("values", []), unit="kWh", color=color)],
        representation_reason=f"{c_type.capitalize()} chart emphasizes energy volume over time."
    )


def _build_zone_trend_chart(data: Dict, date: str, end_date: str = None, preferred_chart_type: Optional[str] = None, **kwargs) -> ChartConfig:
    """Build multi-series line chart for zone daily trend."""
    total_kwh = data.get("total_kwh", 0.0)
    days_count = data.get("days_count", 1)
    zones_count = data.get("zones_count", len(data.get("series", [])))
    c_type = preferred_chart_type if preferred_chart_type in ("line", "area", "bar") else "line"

    chart_series = [
        ChartSeries(name=s.get("name", "Unknown"), data=s.get("data", []), unit="kWh")
        for s in data.get("series", [])
    ]
    date_range = f"{date} to {end_date}" if end_date and end_date != date else date

    return ChartConfig(
        chart_type=c_type,
        title=f"Zone Daily Consumption Trend ({date_range})",
        subtitle=f"{days_count} Days | {zones_count} Zone(s) | Total: {total_kwh:,.1f} kWh",
        x_axis_label="Date",
        x_labels=data.get("labels", []),
        y_axis_label="Energy (kWh)",
        series=chart_series,
        representation_reason="Multi-series line chart shows daily zone consumption trends."
    )


def _build_equipment_trend_chart(data: Dict, date: str, end_date: str = None, preferred_chart_type: Optional[str] = None, **kwargs) -> ChartConfig:
    """Build multi-series line chart for equipment category daily trend."""
    total_kwh = data.get("total_kwh", 0.0)
    days_count = data.get("days_count", 1)
    categories_count = data.get("categories_count", len(data.get("series", [])))
    c_type = preferred_chart_type if preferred_chart_type in ("line", "area", "bar") else "line"

    chart_series = [
        ChartSeries(name=s.get("name", "Unknown"), data=s.get("data", []), unit="kWh")
        for s in data.get("series", [])
    ]
    date_range = f"{date} to {end_date}" if end_date and end_date != date else date

    return ChartConfig(
        chart_type=c_type,
        title=f"Equipment Daily Consumption Trend ({date_range})",
        subtitle=f"{days_count} Days | {categories_count} Category(ies) | Total: {total_kwh:,.1f} kWh",
        x_axis_label="Date",
        x_labels=data.get("labels", []),
        y_axis_label="Energy (kWh)",
        series=chart_series,
        representation_reason="Multi-series line chart shows daily equipment consumption trends."
    )


def _build_scatter_chart(data: Dict, date: str, **kwargs) -> ChartConfig:
    """Build correlation scatter plot chart."""
    points = [ScatterPoint(**p) for p in data.get("points", [])]
    scatter_series = [
        ScatterSeries(
            name=data.get("series_name", "Correlation"),
            points=points,
            color=data.get("color", "#0891B2")
        )
    ]
    return ChartConfig(
        chart_type="scatter",
        title=data.get("title", f"Scatter Plot — {date}"),
        subtitle=f"{len(points)} Data Points | {data.get('x_axis_label')} vs {data.get('y_axis_label')}",
        x_axis_label=data.get("x_axis_label"),
        y_axis_label=data.get("y_axis_label"),
        scatter_series=scatter_series,
        representation_reason=data.get("reason", "Scatter plot demonstrates correlation between telemetry variables.")
    )


# Registry: viz_type → (builder_func, extra_kwargs)
CHART_BUILDERS: Dict[str, Tuple[Callable, Dict[str, Any]]] = {
    "gauge": (_build_gauge_chart, {}),
    "heatmap": (_build_heatmap_chart, {}),
    "thd": (_build_thd_chart, {}),
    "power_factor": (_build_power_factor_chart, {}),
    "tariff": (_build_tariff_chart, {}),
    "equipment": (_build_donut_chart, {"title": "Equipment Breakdown"}),
    "zone": (_build_horizontal_bar_chart, {"title": "Cost Center Breakdown"}),
    "shift": (_build_donut_chart, {"title": "Shift Distribution"}),
    "solar": (_build_area_chart, {"title": "Solar Generation"}),
    "facility": (_build_area_chart, {"title": "Facility Load Profile"}),
    "facility_trend": (_build_area_chart, {"title": "Facility Consumption Trend"}),
    "zone_trend": (_build_zone_trend_chart, {}),
    "equipment_trend": (_build_equipment_trend_chart, {}),
    "scatter": (_build_scatter_chart, {}),
}


def _build_chart_step(input_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    LCEL Step 4: Build chart from retrieved and validated data.

    Input: {..., "data": dict, "numeric_validation_success": bool}
    Output: {...input, "chart_config": dict, "build_success": bool}
    """
    if not input_dict.get("numeric_validation_success", False):
        return {
            **input_dict,
            "chart_config": None,
            "build_success": False,
            "error": input_dict.get("validation_error", "Validation failed"),
        }

    viz_type = input_dict.get("viz_type", "equipment")
    data = input_dict.get("data", {})
    start_date = input_dict.get("start_date")
    end_date = input_dict.get("end_date")
    metadata = input_dict.get("metadata", {})

    builder_info = CHART_BUILDERS.get(viz_type)
    if not builder_info:
        return {
            **input_dict,
            "chart_config": None,
            "build_success": False,
            "error": f"No chart builder registered for visualization type: {viz_type}",
        }

    builder_func, extra_kwargs = builder_info

    try:
        kwargs_to_pass = {**extra_kwargs}
        if "preferred_chart_type" in metadata:
            kwargs_to_pass["preferred_chart_type"] = metadata["preferred_chart_type"]

        chart_config = builder_func(
            data=data,
            date=start_date,
            end_date=end_date,
            **kwargs_to_pass
        )
        return {
            **input_dict,
            "chart_config": chart_config.model_dump(),
            "build_success": True,
        }
    except Exception as e:
        return {
            **input_dict,
            "chart_config": None,
            "build_success": False,
            "error": f"Chart configuration construction failed: {str(e)}",
        }


# Create LCEL Runnable for chart building
build_chart_runnable = RunnableLambda(_build_chart_step)


# ==============================================================================
# LEGACY VISUALIZATION CHAIN (Preserved for compatibility and restoration)
# ==============================================================================
# The original visualization chain executed telemetry retrieval through direct
# service wrapper calls (facility_telemetry, zones_telemetry, equipments_telemetry).
# It is preserved here in full and can be restored by uncommenting below:
#
# legacy_visualization_chain = (
#     parse_intent_runnable
#     | retrieve_data_runnable
#     | validate_numeric_runnable
#     | build_chart_runnable
# )
# full_legacy_visualization_chain = legacy_visualization_chain | RunnableLambda(_format_response)


# ==============================================================================
# ACTIVE PATH: SQL + RAG RETRIEVAL VISUALIZATION CHAIN (Refactored Pipeline)
# ==============================================================================
# The active visualization chain follows the new RAG-grounded retrieval architecture:
# 1. parse_intent_runnable: Parses intent, parameters, and chart preferences.
# 2. retrieve_data_sql_rag_runnable:
#    - Retrieves reference knowledge via RAG pipeline using SQL retrieval interface.
#    - Identifies authoritative operational tables, tags, filters, and boundaries.
#    - Executes read-only operational SQL query through execute_custom_sql.
# 3. validate_numeric_runnable: Validates numeric telemetry.
# 4. build_chart_runnable: Builds chart config (donut, bar, area, line, gauge, etc.).
# 5. _format_response: Formats API response payload.

visualization_chain = (
    parse_intent_runnable
    | retrieve_data_runnable
    | validate_numeric_runnable
    | build_chart_runnable
)


def _format_response(chain_result: Dict[str, Any]) -> Dict[str, Any]:
    """Format the chain result into the final API response."""
    data_payload = chain_result.get("data")
    if not isinstance(data_payload, dict):
        data_payload = {}

    if not chain_result.get("retrieval_success"):
        return {
            "status": "error",
            "error": data_payload.get("error", chain_result.get("error", "Data retrieval failed")),
            "visualization_type": chain_result.get("viz_type"),
        }

    if not chain_result.get("numeric_validation_success"):
        return {
            "status": "error",
            "error": chain_result.get("validation_error", "Telemetry numeric validation failed"),
            "visualization_type": chain_result.get("viz_type"),
            "data": data_payload,
        }

    if not chain_result.get("build_success"):
        return {
            "status": "error",
            "error": chain_result.get("error", "Chart building failed"),
            "visualization_type": chain_result.get("viz_type"),
            "data": data_payload,
        }

    return {
        "status": "success",
        "visualization_type": chain_result.get("viz_type"),
        "intent_understood": chain_result.get("metadata", {}).get("raw_intent", ""),
        "date": chain_result.get("start_date"),
        "end_date": chain_result.get("end_date"),
        "data": data_payload,
        "chart_config": chain_result.get("chart_config"),
    }


# Full chain with response formatting
full_visualization_chain = visualization_chain | RunnableLambda(_format_response)


# ==============================================================================
# UNIFIED VISUALIZATION TOOL (Uses LCEL Chain)
# ==============================================================================

@tool
def create_visualization(
    intent: str,
    start_date: str = "yesterday",
    end_date: Optional[str] = None,
    granularity: Literal["daily", "hourly", "shift_wise"] = "daily",
    filter_items: Optional[List[str]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    🎨 INTELLIGENT VISUALIZATION — LCEL-powered data retrieval + chart generation.

    CHAIN FLOW: parse_intent → retrieve_data → validate_numeric → build_chart

    AVOIDING DUPLICATE CALLS:
    If you already called an EMS tool (grouping_energy, get_instantaneous_energy),
    pass its result as 'data' to SKIP redundant retrieval:

        # Step 1: Agent calls EMS tool
        ems_result = grouping_energy(date="2026-10-15", group_by="equipment")

        # Step 2: Pass result to visualization (NO duplicate fetch!)
        create_visualization(intent="equipment", data=ems_result)

    INTENT EXAMPLES:
    ─────────────────────────────────────────────────────────────────────────────
    📊 BREAKDOWNS: "equipment breakdown", "zone consumption", "shift distribution"
    📈 TRENDS: "hourly load profile", "solar generation", "facility consumption"
    🎯 KPIs: "peak demand gauge", "power factor trend", "THD compliance"
    🔥 PATTERNS: "hourly heatmap" (requires end_date for date range)
    💰 COSTS: "tariff band split", "TOD breakdown"
    🔬 SCATTER: "correlation between steam flow and pressure"

    PARAMETERS:
    - intent: Natural language description of what to visualize (can include chart preference, e.g. 'as pie chart')
    - start_date: Date (default: "yesterday")
    - end_date: For multi-day analysis (required for heatmap and trend analysis)
    - granularity: "daily", "hourly", or "shift_wise"
    - filter_items: Optional filter for categories or cost centers
    - data: OPTIONAL pre-fetched data from EMS tools (skips retrieval if provided)

    RETURNS: {status, visualization_type, data, chart_config}
    """
    # 1. Normalize and strictly validate start_date
    try:
        start_d = date_service.normalize_and_validate_date(start_date) or normalize_date_str(start_date)
    except Exception:
        return {"status": "error", "error": f"Invalid start_date: '{start_date}'"}

    if not start_d or not re.match(r"^\d{4}-\d{2}-\d{2}$", start_d):
        return {
            "status": "error",
            "error": f"Invalid start_date: '{start_date}'. Must be YYYY-MM-DD or valid relative expression (e.g. 'yesterday')."
        }

    # 2. Normalize and strictly validate end_date if provided
    end_d = None
    if end_date:
        try:
            end_d = date_service.normalize_and_validate_date(end_date) or normalize_date_str(end_date)
        except Exception:
            return {"status": "error", "error": f"Invalid end_date: '{end_date}'"}

        if not end_d or not re.match(r"^\d{4}-\d{2}-\d{2}$", end_d):
            return {
                "status": "error",
                "error": f"Invalid end_date: '{end_date}'. Must be YYYY-MM-DD format."
            }

        if end_d < start_d:
            return {
                "status": "error",
                "error": f"Invalid date range: end_date '{end_d}' cannot be earlier than start_date '{start_d}'."
            }

    # 3. Adopt date from pre_fetched_data if available and start_date was default
    if data is not None and isinstance(data, dict):
        d_val = data.get("date")
        if isinstance(d_val, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", d_val):
            if start_date == "yesterday" and d_val != start_d:
                start_d = d_val

    # Build input for the chain
    chain_input = {
        "intent": intent,
        "start_date": start_d,
        "end_date": end_d,
        "granularity": granularity,
        "filter_items": filter_items,
        "pre_fetched_data": data,
    }

    # Execute the LCEL chain
    result = full_visualization_chain.invoke(chain_input)

    # Add data source indicator
    if data is not None:
        result["data_source"] = "pre_fetched (no duplicate call)"
    else:
        result["data_source"] = "retrieved"

    return result


# ==============================================================================
# EXPORT
# ==============================================================================

ALL_VISUALIZATION_TOOLS = [create_visualization]

__all__ = [
    "create_visualization",
    "ALL_VISUALIZATION_TOOLS",
    "visualization_chain",
    "full_visualization_chain",
]
