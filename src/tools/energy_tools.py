"""
LangChain Tools for Yamaha EMS Assistant
Wraps deterministic services with descriptive schemas for LLM tool calling.
"""

from typing import Any, Dict, List, Literal, Optional
from langchain_core.tools import tool
from src.services.breakdown_service import BreakdownService
from src.services.demand_service import DemandService
from src.services.dg_service import DGService
from src.services.energy_service import EnergyService
from src.services.power_quality_service import PowerQualityService
from src.services.rca_service import RCAService
from src.services.shift_service import ShiftService
from src.services.tariff_service import TariffService
from src.rag.retriever import ems_kb
from src.db.sqlite_client import db_client

@tool
def get_energy_consumption(date: str) -> Dict[str, Any]:
    """
    Get total facility grid electricity consumption (kWh) on the HT_Room 11kV Main Incomer for a specific IST date (YYYY-MM-DD), e.g. 'yesterday's facility consumption', 'total energy today', or daily grid power.
    Uses authoritative counter delta max - min.
    """
    return EnergyService.get_facility_daily_energy(date)

@tool
def get_shift_wise_consumption(date: str) -> Dict[str, Any]:
    """
    Retrieve shift-wise electricity consumption (kWh) for Shift A, B, and C on the HT_Room Main Incomer for a given date (YYYY-MM-DD), including 'yesterday's shift consumption', 'today's shifts', or any specific date.
    Shifts: Shift A (08:00–17:00), Shift B (17:00–00:40 next day), Shift C (00:40–08:00).
    Boundary values use nearest readings at or before exact boundary.
    """
    return ShiftService.get_shift_consumption(date)

@tool
def get_cost_and_tariff(date: str) -> Dict[str, Any]:
    """
    Calculate daily electricity billing and cost (in INR / ₹) under Tariff HT_1 TOD (Time of Day) schedule for date (YYYY-MM-DD), e.g. 'yesterday's bill', 'electricity cost for 2026-10-19', 'TOD tariff charges'.
    scale = true_daily_kWh / sum(hourly_kWh), then rescaled_hour * tariff_rate.
    Returns total cost, tariff band summary (Off-Peak, Normal, Peak), and hourly breakdown.
    """
    return TariffService.calculate_daily_cost(date)

@tool
def get_peak_demand_analysis(date: str) -> Dict[str, Any]:
    """
    Analyze peak apparent power demand (kVA) on the South Utilities Transformer for date (YYYY-MM-DD), e.g. 'peak demand yesterday', 'kVA utilization', 'demand excursions'.
    - Peak kVA and utilization % against 1475.0 kVA contracted capacity
    - Hourly peak profile (00:00 to 23:00)
    - Excursion events exceeding the 80% threshold (1180.0 kVA)
    """
    return DemandService.get_peak_demand_analysis(date)

@tool
def get_dg_generator_status(month: str) -> Dict[str, Any]:
    """
    Get Diesel Generator (DG) operational metrics for a month (YYYY-MM):
    - Runtime minutes and hours (real power > 1.0 kW)
    - Total energy generated (kWh)
    - Start and stop counts, plus details of runs
    """
    return DGService.get_dg_monthly_metrics(month)

@tool
def get_power_quality_and_utilities(metric: Literal["thd", "reactive_energy", "steam"], date: str) -> Dict[str, Any]:
    """
    Get power quality or non-electrical utility metrics for date (YYYY-MM-DD):
    - 'thd': Voltage THD (limit 5%) and Current THD (limit 8%, 3-phase combined average)
    - 'reactive_energy': Cumulative kVARh on South & North Utilities transformers
    - 'steam': Blower Room steam snapshot (flow rate kg/h, pressure bar) & consumed today (kg)
    """
    if metric == "thd":
        return PowerQualityService.get_thd_analysis(date)
    elif metric == "reactive_energy":
        return PowerQualityService.get_reactive_energy(date)
    elif metric == "steam":
        return PowerQualityService.get_steam_summary(date)
    return {"error": f"Unknown metric: {metric}. Choose 'thd', 'reactive_energy', or 'steam'."}

@tool
def get_breakdown_summary(group_by: Literal["equipment_wise", "zone_wise"], date: str) -> Dict[str, Any]:
    """
    Get energy consumption breakdown for date (YYYY-MM-DD):
    - 'equipment_wise': 8 categories (Lighting, Molding, Compressor, etc.) with mandatory exclusions
    - 'zone_wise': 17 organizational cost centers (General Admin, AG Painting, Production Improve, etc.)
    """
    if group_by == "equipment_wise":
        return BreakdownService.get_equipment_wise_breakdown(date)
    elif group_by == "zone_wise":
        return BreakdownService.get_zone_wise_cost_centers(date)
    return {"error": "Invalid group_by. Choose 'equipment_wise' or 'zone_wise'."}

@tool
def diagnose_high_consumption(date: str) -> Dict[str, Any]:
    """
    Automated Root Cause Analysis (RCA) for a given date (YYYY-MM-DD):
    Compares against 30-day baseline, flags anomalous increase, identifies top contributing
    categories and cost centers, and checks shift C baseload inflation and peak excursions.
    """
    return RCAService.diagnose_day(date)

@tool
def diagnose_spikes_and_anomalies(
    date: str,
    anomaly_type: Literal["all", "peak_demand", "hourly_spike", "shift_c_baseload", "power_quality", "steam"] = "all"
) -> Dict[str, Any]:
    """
    Scan telemetry database to detect, isolate, and explain sudden spikes and anomalies on date (YYYY-MM-DD):
    - Peak demand surges exceeding 1180 kVA threshold with culprit machine identification
    - Hourly consumption spikes with category and top-device attribution
    - Shift C (night) baseload leakage where equipment was left running
    - Power quality excursions (Voltage THD > 5%, Current THD > 8%, Power Factor < 0.90)
    - Steam flow spikes and pressure drops
    Retrieves raw telemetry from opcda_readings to provide physical engineering root cause reasoning.
    """
    return RCAService.detect_and_explain_spikes(date, anomaly_type)

@tool
def explain_hourly_anomaly(date: str, hour: int) -> Dict[str, Any]:
    """
    Deep-dive telemetry retrieval for a specific hour (0 to 23 IST) on date (YYYY-MM-DD):
    - Facility kWh and peak kVA during that exact 60-minute window
    - Equipment category breakdown (Molding, Compressors, Airconditioning, etc.)
    - Top 5 individual machinery meters driving consumption
    - Power Quality (THD and Power Factor)
    - Physical engineering verdict on why load was high or abnormal during that hour.
    """
    return RCAService.explain_hourly_anomaly(date, hour)

@tool
def search_ems_knowledge_base(query: str) -> Dict[str, Any]:
    """
    Search the authoritative Yamaha EMS reference document for definitions, calculation formulas,
    meter mapping rules, and data-quality exceptions (e.g. unmapped AC-1/AC-2 conflict).
    """
    results = ems_kb.search(query, top_k=2)
    return {"query": query, "results": results}

@tool
def execute_custom_sql(query: str) -> Dict[str, Any]:
    """
    Execute a read-only SELECT SQL query against the database for ad-hoc custom questions.
    Tables: opcda_readings (tag_id, reading_timestamp, value), tag_daily_energy_rollup (date, tag_id, min_value, max_value, energy).
    """
    clean_q = query.strip().upper()
    if any(k in clean_q for k in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE"]):
        return {"error": "Only read-only SELECT queries are allowed."}

    if "LIMIT" not in clean_q:
        query = query.rstrip(";") + " LIMIT 50;"

    try:
        rows = db_client.execute_query(query)
        return {"count": len(rows), "rows": rows}
    except Exception as e:
        return {"error": str(e)}

@tool
def get_realtime_device_telemetry(device_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get live real-time diagnostic telemetry snapshots for representative devices (Component 10).
    Returns voltage, current, power factor, real power (kW), apparent power (kVA), frequency (Hz), and status.
    Representative devices: HT_Room, North_Utilities, Molding, Compressor, Airconditioning, Lighting, Solar, DG, Dust_Collector, Paintshop.
    """
    from src.db.chat_history import chat_repo
    readings = chat_repo.get_live_device_telemetry(device_name)
    return {
        "status": "success",
        "device_filter": device_name,
        "count": len(readings),
        "telemetry": readings
    }

ALL_EMS_TOOLS = [
    get_energy_consumption,
    get_shift_wise_consumption,
    get_cost_and_tariff,
    get_peak_demand_analysis,
    get_dg_generator_status,
    get_power_quality_and_utilities,
    get_breakdown_summary,
    diagnose_high_consumption,
    diagnose_spikes_and_anomalies,
    explain_hourly_anomaly,
    search_ems_knowledge_base,
    get_realtime_device_telemetry,
    execute_custom_sql,
]
