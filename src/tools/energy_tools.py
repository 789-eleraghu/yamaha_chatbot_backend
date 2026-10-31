"""
LangChain Industrial EMS Telemetry Tools (Consolidated 7-Tool Architecture)

Unified tool registry for Yamaha Energy Management System:
- 3 Primary Tools: get_cummulative_energy, get_instantaneous_energy, grouping_energy
- 4 Specialist Tools: diagnose_consumption, explain_hourly_anomaly, search_knowledge_base, execute_custom_sql

This architecture eliminates redundant public wrappers and provides clear LLM intent matching.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import tool

from src.core.constants import (
    CATEGORY_EXCLUDED_TAGS,
    DG_ENERGY_TAG,
    EQUIPMENT_WISE_CATEGORIES,
    SHIFT_ENERGY_TAG,
    SOLAR_ENERGY_TAG,
    STEAM_TOTALIZER_TAG,
)
from src.db.client import db_client
from src.db.tag_catalog import COST_CENTER_MAPPINGS
from src.rag.retriever import ems_kb
from src.services.date_service import date_service
from src.services.rca_service import RCAService
from src.services.tariff_service import TariffService
from src.services.telemetry import (
    equipments_telemetry,
    facility_telemetry,
    generators_telemetry,
    zones_telemetry,
)


# ==============================================================================
# Internal Helpers: Date Validation & Error Handling
# ==============================================================================

def _validate_date(date: str, fmt: str = "%Y-%m-%d") -> tuple[bool, str]:
    """Validate date string format. Returns (is_valid, error_message)."""
    try:
        datetime.strptime(date, fmt)
        return True, ""
    except ValueError:
        return False, f"Invalid date format: '{date}'. Expected {fmt}."


def _safe_call(func, *args, **kwargs) -> Dict[str, Any]:
    """Wrap service calls with error handling."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        return {"error": str(e), "success": False}


# ==============================================================================
# Internal Helper: Sector Resolution
# ==============================================================================

def _resolve_sector(sector: str) -> tuple[str, str, str]:
    """
    Resolve a sector string to (sector_type, identifier, display_label).
    sector_type is one of: 'facility', 'solar', 'dg', 'steam', 'reactive', 'equipment', 'cost_center', 'tag', 'unknown'.
    """
    s = sector.strip()
    s_lower = s.lower().replace("-", "_")
    s_norm = re.sub(r"[\s_]+", " ", s_lower).strip()

    # Facility / Grid / Main Incomer
    facility_keywords = (
        "facility", "grid", "plant", "incomer", "main", "main incomer", "11kv",
        "11kv main incomer", "ht room", "ht_room", "ht room 11kv main incomer",
        "main_incomer", "total", "all_facility", "whole plant"
    )
    if s_lower in facility_keywords or s_norm in facility_keywords or any(kw in s_norm for kw in ["main incomer", "11kv", "facility grid"]):
        return ("facility", SHIFT_ENERGY_TAG, "Facility Grid (11kV Main Incomer)")

    # Solar
    if s_lower in ("solar", "rooftop_solar", "pv", "solar_plant"):
        return ("solar", SOLAR_ENERGY_TAG, "Rooftop Solar 100kW")

    # DG / Generator
    if s_lower in ("dg", "generator", "diesel_generator", "diesel", "backup"):
        return ("dg", DG_ENERGY_TAG, "DG Incomer 300kVA")

    # Steam / Boiler
    if s_lower in ("steam", "boiler", "steam_flow"):
        return ("steam", STEAM_TOTALIZER_TAG, "Blower Room Steam")

    # Reactive Energy
    if s_lower in ("reactive", "reactive_energy", "kvarh"):
        return ("reactive", "reactive", "Substation Reactive Energy")

    # Equipment Categories (8 types)
    for cat in EQUIPMENT_WISE_CATEGORIES:
        clean_cat = cat.lower().replace("_", "")
        clean_s = s_lower.replace("_", "").replace(" ", "")
        if clean_s == clean_cat or clean_s.rstrip("s") == clean_cat.rstrip("s"):
            return ("equipment", cat, f"Equipment: {cat}")

    # Aliases for equipment categories
    eq_aliases = {
        "ac": "Airconditioning",
        "aircondition": "Airconditioning",
        "airconditioning": "Airconditioning",
        "air_conditioning": "Airconditioning",
        "lights": "Lighting",
        "light": "Lighting",
        "compressors": "Compressor",
        "moldings": "Molding",
        "dust": "Dust_Collector",
        "dustcollector": "Dust_Collector",
        "dust_collectors": "Dust_Collector",
        "paint": "Paintshop",
        "paint_shop": "Paintshop",
        "production": "Production_Power",
    }
    if s_lower in eq_aliases:
        cat = eq_aliases[s_lower]
        return ("equipment", cat, f"Equipment: {cat}")

    # Cost Centers / Zones (17 types)
    for cc in COST_CENTER_MAPPINGS:
        clean_cc = cc.lower().replace(" ", "").replace("_", "").replace("/", "")
        clean_s = s_lower.replace(" ", "").replace("_", "").replace("/", "")
        if clean_s == clean_cc or clean_s in clean_cc or clean_cc in clean_s:
            return ("cost_center", cc, f"Cost Center: {cc}")

    # Raw Tag or contains '/'
    if "/" in s:
        return ("tag", s, s)

    return ("unknown", s, s)


def _calc_sector_cumulative(
    sec_type: str,
    sec_id: str,
    sec_label: str,
    start_date: str,
    end_date: str,
    target_dates: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Calculate cumulative energy for a resolved sector over date(s)."""
    is_single_day = (start_date == end_date) and (not target_dates)

    if target_dates:
        days_clause = "day IN (" + ", ".join(f"'{d}'" for d in target_dates) + ")"
    else:
        days_clause = f"day >= toDate('{start_date}') AND day <= toDate('{end_date}')"

    if sec_type == "facility":
        # Facility = HT Incomer + Solar + DG (total plant consumption from all sources)
        if is_single_day:
            # Get HT Incomer (grid import)
            ht_res = facility_telemetry.get_grid_energy(start_date)
            ht_kwh = ht_res.get("energy_kwh", 0.0) if isinstance(ht_res, dict) else 0.0

            # Get Solar generation
            solar_res = facility_telemetry.get_solar_generation(start_date)
            solar_kwh = solar_res.get("energy_generated_kwh", 0.0) if isinstance(solar_res, dict) else 0.0

            # Get DG generation
            dg_res = generators_telemetry.get_daily_metrics(start_date)
            dg_kwh = dg_res.get("energy_generated_kwh", 0.0) if isinstance(dg_res, dict) else 0.0

            total_kwh = round(ht_kwh + solar_kwh + dg_kwh, 1)
            return {
                "sector": "Total Facility Consumption",
                "energy_kwh": total_kwh,
                "breakdown": {
                    "ht_incomer_kwh": round(ht_kwh, 1),
                    "solar_kwh": round(solar_kwh, 1),
                    "dg_kwh": round(dg_kwh, 1),
                },
                "note": "Total = HT Incomer (grid) + Solar + DG",
                "unit": "kWh",
            }
        else:
            # Multi-day: sum all three sources
            ht_q = f"""
                SELECT toString(day) as date, ROUND(maxMerge(max_value) - minMerge(min_value), 1) as kwh
                FROM tag_daily_energy_rollup
                WHERE tag_id = '{SHIFT_ENERGY_TAG}' AND {days_clause}
                GROUP BY day ORDER BY day;
            """
            solar_q = f"""
                SELECT toString(day) as date, ROUND(maxMerge(max_value) - minMerge(min_value), 1) as kwh
                FROM tag_daily_energy_rollup
                WHERE tag_id = '{SOLAR_ENERGY_TAG}' AND {days_clause}
                GROUP BY day ORDER BY day;
            """
            dg_q = f"""
                SELECT toString(day) as date, ROUND(maxMerge(max_value) - minMerge(min_value), 1) as kwh
                FROM tag_daily_energy_rollup
                WHERE tag_id = '{DG_ENERGY_TAG}' AND {days_clause}
                GROUP BY day ORDER BY day;
            """
            ht_rows = db_client.execute_query(ht_q)
            solar_rows = db_client.execute_query(solar_q)
            dg_rows = db_client.execute_query(dg_q)

            ht_total = sum(r["kwh"] for r in ht_rows if r.get("kwh") is not None)
            solar_total = sum(r["kwh"] for r in solar_rows if r.get("kwh") is not None)
            dg_total = sum(r["kwh"] for r in dg_rows if r.get("kwh") is not None)

            return {
                "sector": "Total Facility Consumption",
                "energy_kwh": round(ht_total + solar_total + dg_total, 1),
                "breakdown": {
                    "ht_incomer_kwh": round(ht_total, 1),
                    "solar_kwh": round(solar_total, 1),
                    "dg_kwh": round(dg_total, 1),
                },
                "daily_breakdown": {
                    "ht_incomer": ht_rows,
                    "solar": solar_rows,
                    "dg": dg_rows,
                },
                "note": "Total = HT Incomer (grid) + Solar + DG",
                "unit": "kWh",
            }

    elif sec_type == "solar":
        if is_single_day:
            res = facility_telemetry.get_solar_generation(start_date)
            return {
                "sector": sec_label,
                "meter": res.get("meter", "Incomer.Incomer_Solar_100kW"),
                "energy_kwh": res.get("energy_generated_kwh", 0.0),
                "peak_power_kw": res.get("peak_power_kw", 0.0),
                "avg_power_kw": res.get("avg_power_kw", 0.0),
                "unit": "kWh",
            }
        else:
            q = f"""
                SELECT toString(day) as date, ROUND(maxMerge(max_value) - minMerge(min_value), 1) as kwh
                FROM tag_daily_energy_rollup
                WHERE tag_id = '{SOLAR_ENERGY_TAG}' AND {days_clause}
                GROUP BY day ORDER BY day;
            """
            rows = db_client.execute_query(q)
            total = sum(r["kwh"] for r in rows if r.get("kwh") is not None)
            return {
                "sector": sec_label,
                "meter": "Incomer.Incomer_Solar_100kW",
                "tag_id": SOLAR_ENERGY_TAG,
                "energy_kwh": round(total, 1),
                "daily_breakdown": rows,
                "unit": "kWh",
            }

    elif sec_type == "dg":
        if is_single_day:
            res = generators_telemetry.get_daily_metrics(start_date)
            return {
                "sector": sec_label,
                "generator": res.get("generator", "Incomer.DG_Incomer_300kVA"),
                "energy_kwh": res.get("energy_generated_kwh", 0.0),
                "runtime_minutes": res.get("runtime_minutes", 0),
                "runtime_hours": res.get("runtime_hours", 0.0),
                "starts_count": res.get("starts_count", 0),
                "unit": "kWh",
            }
        else:
            q = f"""
                SELECT toString(day) as date, ROUND(maxMerge(max_value) - minMerge(min_value), 1) as kwh
                FROM tag_daily_energy_rollup
                WHERE tag_id = '{DG_ENERGY_TAG}' AND {days_clause}
                GROUP BY day ORDER BY day;
            """
            rows = db_client.execute_query(q)
            total = sum(r["kwh"] for r in rows if r.get("kwh") is not None)
            return {
                "sector": sec_label,
                "generator": "Incomer.DG_Incomer_300kVA",
                "tag_id": DG_ENERGY_TAG,
                "energy_kwh": round(total, 1),
                "daily_breakdown": rows,
                "unit": "kWh",
            }

    elif sec_type == "steam":
        # Steam returns mass consumption in kg, NOT electrical energy
        res = facility_telemetry.get_steam_summary(start_date)
        return {
            "sector": sec_label,
            "steam_consumed_kg": res.get("steam_consumed_kg", 0.0),
            "current_flow_rate_kgh": res.get("current_flow_rate_kgh"),
            "current_pressure_bar": res.get("current_pressure_bar"),
            "unit": "kg",
            "note": "Steam is measured in kg, not kWh. Do not sum with electrical energy.",
        }

    elif sec_type == "reactive":
        # Reactive energy returns kVARh, NOT active electrical energy kWh
        res = facility_telemetry.get_reactive_energy(start_date)
        total_kvarh = sum(v for v in res.get("transformers", {}).values() if v is not None)
        return {
            "sector": sec_label,
            "reactive_energy_kvarh": round(total_kvarh, 1),
            "transformers": res.get("transformers", {}),
            "unit": "kVARh",
            "note": "Reactive energy is kVARh, not kWh. Do not sum with active energy.",
        }

    elif sec_type == "equipment":
        if is_single_day:
            res = equipments_telemetry.get_category_energy(sec_id, start_date)
            return {
                "sector": sec_label,
                "category": sec_id,
                "energy_kwh": res.get("total_energy_kwh", 0.0),
                "device_count": res.get("device_count", 0),
                "devices": res.get("devices", []),
                "unit": "kWh",
            }
        else:
            excluded_list = ", ".join(f"'{t}'" for t in CATEGORY_EXCLUDED_TAGS)
            q = f"""
                SELECT toString(day) as date, ROUND(SUM(tag_energy), 1) as kwh
                FROM (
                    SELECT day, tag_id, maxMerge(max_value) - minMerge(min_value) as tag_energy
                    FROM tag_daily_energy_rollup
                    WHERE {days_clause}
                      AND tag_id LIKE '{sec_id}.%'
                      AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                      AND tag_id NOT IN ({excluded_list})
                    GROUP BY day, tag_id
                )
                GROUP BY day ORDER BY day;
            """
            rows = db_client.execute_query(q)
            total = sum(r["kwh"] for r in rows if r.get("kwh") is not None)
            return {
                "sector": sec_label,
                "category": sec_id,
                "energy_kwh": round(total, 1),
                "daily_breakdown": rows,
                "unit": "kWh",
            }

    elif sec_type == "cost_center":
        if is_single_day:
            res = zones_telemetry.get_cost_center_energy(sec_id, start_date)
            return {
                "sector": sec_label,
                "cost_center": sec_id,
                "energy_kwh": res.get("total_energy_kwh", 0.0),
                "meter_count": res.get("active_meters_count", 0),
                "meters": res.get("meters", []),
                "unit": "kWh",
            }
        else:
            tags = COST_CENTER_MAPPINGS.get(sec_id, [])
            if not tags:
                return {"sector": sec_label, "error": f"No tags mapped for cost center '{sec_id}'"}
            tag_list = ", ".join(f"'{t}'" for t in tags)
            q = f"""
                SELECT toString(day) as date, ROUND(SUM(tag_energy), 1) as kwh
                FROM (
                    SELECT day, tag_id, maxMerge(max_value) - minMerge(min_value) as tag_energy
                    FROM tag_daily_energy_rollup
                    WHERE {days_clause}
                      AND tag_id IN ({tag_list})
                    GROUP BY day, tag_id
                )
                GROUP BY day ORDER BY day;
            """
            rows = db_client.execute_query(q)
            total = sum(r["kwh"] for r in rows if r.get("kwh") is not None)
            return {
                "sector": sec_label,
                "cost_center": sec_id,
                "energy_kwh": round(total, 1),
                "daily_breakdown": rows,
                "unit": "kWh",
            }

    elif sec_type == "tag":
        q = f"""
            SELECT toString(day) as date, ROUND(maxMerge(max_value) - minMerge(min_value), 1) as kwh
            FROM tag_daily_energy_rollup
            WHERE tag_id = '{sec_id}' AND {days_clause}
            GROUP BY day ORDER BY day;
        """
        rows = db_client.execute_query(q)
        total = sum(r["kwh"] for r in rows if r.get("kwh") is not None)
        return {
            "sector": sec_label,
            "tag_id": sec_id,
            "energy_kwh": round(total, 1),
            "daily_breakdown": rows,
            "unit": "kWh",
        }

    else:
        return {
            "sector": sec_label,
            "error": f"Unknown sector: '{sec_id}'. Expected facility, solar, DG, equipment category, or cost center zone.",
            "energy_kwh": 0.0,
        }


# ==============================================================================
# Tool 1: get_cummulative_energy (Cumulative Energy Consumption)
# ==============================================================================

@tool
def get_cummulative_energy(
    start_date: str,
    end_date: str,
    sectors: list[str],
    target_dates: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """
    Get cumulative energy consumption (kWh) for specified sectors over a date range.

    USE THIS TOOL FOR:
    - Daily/weekly/monthly energy totals
    - "How much energy did X consume yesterday/last week?"
    - Equipment or zone energy consumption
    - Solar generation totals
    - DG energy generated

    DO NOT USE FOR:
    - Live/instantaneous readings (use get_instantaneous_energy)
    - Hourly breakdowns (use grouping_energy with group_by='hourly')
    - Shift breakdowns (use grouping_energy with group_by='shift')

    Parameters:
    - start_date: Start date YYYY-MM-DD (use same as end_date for single day)
    - end_date: End date YYYY-MM-DD
    - sectors: List of sectors. Valid values:
        - 'facility'/'grid' - Main 11kV incomer
        - 'solar' - 100kW rooftop solar
        - 'dg'/'generator' - Diesel generator
        - Equipment categories: Lighting, Molding, Compressor, Airconditioning, Dust_Collector, Paintshop, Production_Power, Others
        - Cost centers: General Admin, AG Painting, AG Assy, PA WW Process, Production Improve, etc.
    - target_dates: Optional specific dates to query (overrides start/end range)

    Returns cumulative kWh per sector. Steam returns kg (mass), reactive returns kVARh - these CANNOT be summed with electrical energy.
    """
    norm_start = date_service.normalize_and_validate_date(start_date) or start_date
    norm_end = date_service.normalize_and_validate_date(end_date) or end_date or norm_start

    norm_targets = None
    if target_dates:
        norm_targets = [date_service.normalize_and_validate_date(d) or d for d in target_dates]

    if isinstance(sectors, str):
        sec_list = [sectors]
    elif sectors:
        sec_list = list(sectors)
    else:
        sec_list = ["facility"]

    results_by_sector: Dict[str, Any] = {}
    total_electrical_kwh = 0.0
    non_electrical_sectors: List[str] = []

    for sec in sec_list:
        sec_type, sec_id, sec_label = _resolve_sector(sec)
        sec_res = _calc_sector_cumulative(
            sec_type=sec_type,
            sec_id=sec_id,
            sec_label=sec_label,
            start_date=norm_start,
            end_date=norm_end,
            target_dates=norm_targets,
        )
        results_by_sector[sec] = sec_res

        # Only sum electrical energy (kWh), not steam (kg) or reactive (kVARh)
        if sec_type in ("steam", "reactive"):
            non_electrical_sectors.append(sec)
        elif "energy_kwh" in sec_res and isinstance(sec_res["energy_kwh"], (int, float)):
            total_electrical_kwh += float(sec_res["energy_kwh"])

    out: Dict[str, Any] = {
        "status": "success",
        "start_date": norm_start,
        "end_date": norm_end,
        "total_electrical_kwh": round(total_electrical_kwh, 1),
        "sectors": results_by_sector,
    }

    if non_electrical_sectors:
        out["note"] = f"Sectors {non_electrical_sectors} use different units (kg or kVARh) and are excluded from total_electrical_kwh."

    # If single sector requested, flatten details for convenient access
    if len(sec_list) == 1:
        first_res = results_by_sector[sec_list[0]]
        for k, v in first_res.items():
            if k not in out:
                out[k] = v

    return out


# ==============================================================================
# Tool 2: get_instantaneous_energy (Live/Real-time Measurements)
# ==============================================================================

@tool
def get_instantaneous_energy(
    date: str,
    measurement: Literal["power_factor", "thd", "peak_demand", "steam", "reactive", "dg_runtime", "solar_power", "device_telemetry"],
    device_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get instantaneous or point-in-time measurements for power quality and utilities.

    USE THIS TOOL FOR:
    - Power factor readings
    - Harmonics (THD) analysis
    - Peak demand (kVA) and utilization
    - Steam flow rate and pressure
    - Reactive energy totals
    - DG runtime and operational status
    - Solar power output
    - Live device voltage/current/power readings

    DO NOT USE FOR:
    - Cumulative energy consumption totals (use get_cummulative_energy)
    - Hourly or shift breakdowns (use grouping_energy)

    Parameters:
    - date: Date for the measurement (YYYY-MM-DD)
    - measurement: Type of measurement:
        - 'power_factor': Plant PF on 11kV Main Incomer (avg, min, max, per-phase)
        - 'thd': Voltage THD (limit 5%) and Current THD (limit 8%)
        - 'peak_demand': Peak kVA, utilization %, hourly profile, excursions >1180 kVA
        - 'steam': Blower Room steam flow (kg/h), pressure (bar), daily consumption (kg)
        - 'reactive': Cumulative kVARh on transformers
        - 'dg_runtime': DG runtime minutes/hours, energy generated, start/stop counts
        - 'solar_power': Solar generation with hourly power curve
        - 'device_telemetry': Live voltage, current, power readings
    - device_filter: Optional device name filter for 'device_telemetry' measurement

    Returns measurement-specific data structure.
    """
    norm_date = date_service.normalize_and_validate_date(date) or date
    valid, err = _validate_date(norm_date)
    if not valid:
        return {"error": err}

    if measurement == "power_factor":
        res = _safe_call(facility_telemetry.get_power_factor, norm_date)
        if isinstance(res, dict) and "average_power_factor" in res:
            res["value"] = res["average_power_factor"]
            res["reading"] = res["average_power_factor"]
            res["power_factor"] = res["average_power_factor"]
            res["unit"] = "PF"
        return res

    elif measurement == "thd":
        res = _safe_call(facility_telemetry.get_thd_analysis, norm_date)
        if isinstance(res, dict):
            val = res.get("voltage_thd_avg_pct") or res.get("current_thd_avg_pct") or 0.0
            res["value"] = val
            res["reading"] = val
            res["unit"] = "%"
        return res

    elif measurement == "peak_demand":
        res = _safe_call(facility_telemetry.get_peak_demand, norm_date)
        if isinstance(res, dict) and "peak_kva" in res:
            res["value"] = res["peak_kva"]
            res["reading"] = res["peak_kva"]
            res["peak_demand_kva"] = res["peak_kva"]
            res["unit"] = "kVA"
        return res

    elif measurement == "steam":
        res = _safe_call(facility_telemetry.get_steam_summary, norm_date)
        if isinstance(res, dict):
            val = res.get("daily_consumption_kg") or res.get("steam_flow_kg_h") or 0.0
            res["value"] = val
            res["reading"] = val
            res["unit"] = "kg"
        return res

    elif measurement == "reactive":
        return _safe_call(facility_telemetry.get_reactive_energy, norm_date)

    elif measurement == "dg_runtime":
        return _safe_call(generators_telemetry.get_daily_metrics, norm_date)

    elif measurement == "solar_power":
        return _safe_call(facility_telemetry.get_solar_generation, norm_date, granularity="hourly")

    elif measurement == "device_telemetry":
        return _safe_call(equipments_telemetry.get_device_telemetry, device_filter)

    else:
        return {"error": f"Unknown measurement: '{measurement}'. Valid: power_factor, thd, peak_demand, steam, reactive, dg_runtime, solar_power, device_telemetry"}


# ==============================================================================
# Tool 3: grouping_energy (Grouped/Breakdown Views)
# ==============================================================================

@tool
def grouping_energy(
    date: str,
    group_by: Literal["shift", "hourly", "equipment", "zone", "tariff"],
    sector: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get energy consumption grouped by time periods, equipment categories, or cost centers.

    USE THIS TOOL FOR:
    - Shift-wise breakdown (Shift A/B/C)
    - 24-hour load profiles
    - Equipment category breakdown (8 categories)
    - Cost center/zone breakdown (17 zones)
    - Tariff/cost analysis (TOD bands)

    DO NOT USE FOR:
    - Simple cumulative totals (use get_cummulative_energy)
    - Power quality metrics (use get_instantaneous_energy)

    Parameters:
    - date: Date YYYY-MM-DD
    - group_by: Grouping dimension:
        - 'shift': Shift A (08:00-17:00), Shift B (17:00-00:40), Shift C (00:40-08:00)
        - 'hourly': 24-hour load curve (can specify sector for category/zone specific profile)
        - 'equipment': All 8 equipment categories breakdown
        - 'zone': All 17 cost centers breakdown
        - 'tariff': HT-1 TOD tariff breakdown (Off-Peak, Normal, Peak) with ₹ costs
    - sector: Optional sector for 'hourly' group_by (e.g., 'solar', 'Molding', 'General Admin')

    Returns grouped breakdown with percentages and totals.
    """
    clean_date = date_service.normalize_and_validate_date(date) or date
    valid, err = _validate_date(clean_date)
    if not valid:
        return {"error": err}

    g = group_by.lower().strip()

    # Shift Wise
    if g in ("shift", "shifts", "shift_wise"):
        return _safe_call(facility_telemetry.get_grid_shift_energy, clean_date)

    # Hourly Profile
    if g in ("hourly", "hour", "hourly_profile", "hours", "load_profile"):
        if sector:
            sec_type, sec_id, _ = _resolve_sector(sector)
            if sec_type == "solar":
                return _safe_call(facility_telemetry.get_solar_generation, clean_date, granularity="hourly")
            elif sec_type == "equipment":
                return _safe_call(equipments_telemetry.get_category_hourly_profile, sec_id, clean_date)
            elif sec_type == "cost_center":
                return _safe_call(zones_telemetry.get_cost_center_hourly_profile, sec_id, clean_date)
            else:
                return {"error": f"Hourly profile not supported for sector type '{sec_type}'. Use equipment category or cost center."}
        return _safe_call(facility_telemetry.get_grid_hourly_energy, clean_date)

    # Equipment Breakdown (8 categories)
    if g in ("equipment", "equipments", "category", "categories", "equipment_wise"):
        return _safe_call(equipments_telemetry.get_category_breakdown, clean_date)

    # Zone Breakdown (17 cost centers)
    if g in ("zone", "zones", "cost_center", "cost_centers", "zone_wise"):
        return _safe_call(zones_telemetry.get_zone_breakdown, clean_date)

    # Tariff / TOD Cost Breakdown
    if g in ("tariff", "cost", "tod", "bill", "billing"):
        return _safe_call(TariffService.calculate_daily_cost, clean_date)

    return {"error": f"Invalid group_by: '{group_by}'. Choose from 'shift', 'hourly', 'equipment', 'zone', or 'tariff'."}


# ==============================================================================
# Tool 4: aggregate_multi_date (Multi-Date Aggregation & Ranking)
# ==============================================================================

@tool
def aggregate_multi_date(
    group_by: Literal["zone", "equipment"],
    dates: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_n: int = 5,
) -> Dict[str, Any]:
    """
    🏆 MULTI-DATE AGGREGATION — Aggregate zone/equipment consumption over date ranges.

    ✅ USE THIS TOOL FOR:
    - "Last 1 year zone consumption" → start_date="2025-10-26", end_date="2026-10-26", group_by="zone"
    - "Last month equipment breakdown" → start_date="2026-09-26", end_date="2026-10-26", group_by="equipment"
    - "Last 3 months Monday's top zone" → dates=[...from resolve_advanced_date_query...], group_by="zone"

    TWO MODES:
    1. DATE RANGE MODE (simpler, for contiguous ranges):
       aggregate_multi_date(start_date="2025-10-26", end_date="2026-10-26", group_by="zone")

    2. SPECIFIC DATES MODE (for day-of-week filtering):
       First: resolve_advanced_date_query(period="last_3_months", day_filter="monday")
       Then: aggregate_multi_date(dates=[...], group_by="zone")

    Parameters:
    - group_by: "zone" for cost center breakdown, "equipment" for category breakdown
    - dates: Optional list of specific dates (for day-of-week queries, max 100)
    - start_date: Start of date range (use with end_date for contiguous ranges)
    - end_date: End of date range
    - top_n: Number of top consumers to return (default: 5)

    Returns:
    - ranked_results: Top N consumers ranked by total consumption
    - total_kwh: Grand total across all dates
    """
    # Determine dates to use
    if dates:
        # Mode 2: Specific dates provided
        if len(dates) > 100:
            return {"error": f"Too many dates ({len(dates)}). Maximum is 100 to prevent timeout."}
        use_dates = dates
    elif start_date and end_date:
        # Mode 1: Date range - generate list of dates
        norm_start = date_service.normalize_and_validate_date(start_date)
        norm_end = date_service.normalize_and_validate_date(end_date)
        if not norm_start or not norm_end:
            return {"error": f"Invalid date format. Use YYYY-MM-DD."}

        # Generate all dates in range
        import datetime
        start_dt = datetime.datetime.strptime(norm_start, "%Y-%m-%d").date()
        end_dt = datetime.datetime.strptime(norm_end, "%Y-%m-%d").date()

        if (end_dt - start_dt).days > 365:
            return {"error": f"Date range too large ({(end_dt - start_dt).days} days). Maximum is 365 days."}

        use_dates = []
        current = start_dt
        while current <= end_dt:
            use_dates.append(current.strftime("%Y-%m-%d"))
            current += datetime.timedelta(days=1)
    else:
        return {"error": "Provide either 'dates' list OR 'start_date' + 'end_date' range."}

    # Normalize dates
    valid_dates = []
    for d in use_dates:
        norm_d = date_service.normalize_and_validate_date(d)
        if norm_d:
            valid_dates.append(norm_d)

    if not valid_dates:
        return {"error": "No valid dates after normalization."}

    g = group_by.lower().strip()

    # Aggregate consumption across all dates
    aggregated: Dict[str, float] = {}  # name -> total_kwh
    per_date_breakdown: Dict[str, Dict[str, float]] = {}  # date -> {name: kwh}
    total_kwh = 0.0
    errors = []

    for d in valid_dates:
        try:
            if g == "zone":
                data = zones_telemetry.get_zone_breakdown(d)
                items = data.get("cost_centers", [])
                name_key = "cost_center"
            else:  # equipment
                data = equipments_telemetry.get_category_breakdown(d)
                items = data.get("categories", [])
                name_key = "category"

            per_date_breakdown[d] = {}
            for item in items:
                name = item.get(name_key, "Unknown")
                kwh = item.get("energy_kwh", 0.0)

                aggregated[name] = aggregated.get(name, 0.0) + kwh
                per_date_breakdown[d][name] = kwh
                total_kwh += kwh

        except Exception as e:
            errors.append(f"{d}: {str(e)}")

    # Rank by total consumption (descending)
    sorted_items = sorted(aggregated.items(), key=lambda x: x[1], reverse=True)

    # Build ranked results
    ranked_results = []
    for i, (name, kwh) in enumerate(sorted_items[:top_n], 1):
        pct = (kwh / total_kwh * 100) if total_kwh > 0 else 0
        ranked_results.append({
            "rank": i,
            "name": name,
            "total_kwh": round(kwh, 1),
            "percentage": round(pct, 1),
            "avg_per_date": round(kwh / len(valid_dates), 1) if valid_dates else 0,
        })

    result = {
        "status": "success",
        "group_by": group_by,
        "dates_analyzed": len(valid_dates),
        "date_range": f"{valid_dates[0]} to {valid_dates[-1]}",
        "total_kwh": round(total_kwh, 1),
        "categories_count": len(aggregated),
        "ranked_results": ranked_results,
        "all_aggregated": {k: round(v, 1) for k, v in sorted_items},
    }

    # Include per-date breakdown if not too large
    if len(valid_dates) <= 20:
        result["per_date_breakdown"] = {
            d: {k: round(v, 1) for k, v in breakdown.items()}
            for d, breakdown in per_date_breakdown.items()
        }

    if errors:
        result["warnings"] = errors[:5]  # Limit warnings

    return result


# ==============================================================================
# Tool 5: diagnose_consumption (RCA & Anomaly Detection)
# ==============================================================================

@tool
def diagnose_consumption(
    date: str,
    analysis: Literal["full_rca", "spikes", "peak_demand", "shift_c_baseload", "power_quality"] = "full_rca",
) -> Dict[str, Any]:
    """
    Automated diagnostics and Root Cause Analysis for energy anomalies.

    USE THIS TOOL FOR:
    - "Why was consumption high yesterday?"
    - "Detect spikes or anomalies"
    - "What caused the demand surge?"
    - "Night shift baseload leakage"
    - "Power quality issues"

    Parameters:
    - date: Date to diagnose (YYYY-MM-DD)
    - analysis: Type of analysis:
        - 'full_rca': Complete RCA vs 30-day baseline, top contributors, shift analysis
        - 'spikes': Detect all spike types (demand surges, hourly spikes, baseload leakage, PQ issues)
        - 'peak_demand': Peak kVA surges >1180 kVA with culprit machine identification
        - 'shift_c_baseload': Night shift (00:40-08:00) equipment left running
        - 'power_quality': THD >5%/8%, PF <0.90 excursions

    Returns detailed anomaly findings with engineering verdicts and culprit devices.
    """
    norm_date = date_service.normalize_and_validate_date(date) or date
    valid, err = _validate_date(norm_date)
    if not valid:
        return {"error": err}

    if analysis == "full_rca":
        return _safe_call(RCAService.diagnose_day, norm_date)
    else:
        anomaly_map = {
            "spikes": "all",
            "peak_demand": "peak_demand",
            "shift_c_baseload": "shift_c_baseload",
            "power_quality": "power_quality",
        }
        return _safe_call(RCAService.detect_and_explain_spikes, norm_date, anomaly_map.get(analysis, "all"))


# ==============================================================================
# Tool 5: explain_hourly_anomaly (Deep-dive Hour Analysis)
# ==============================================================================

@tool
def explain_hourly_anomaly(date: str, hour: int) -> Dict[str, Any]:
    """
    Deep-dive investigation into a specific hour's telemetry for anomaly analysis.

    USE THIS TOOL FOR:
    - "What happened at 2pm yesterday?"
    - "Explain the hour 14 spike"
    - "Drilldown into 10:00"

    Parameters:
    - date: Date YYYY-MM-DD
    - hour: Hour 0-23 (IST, e.g., 14 = 14:00-15:00)

    Returns:
    - Facility kWh and peak kVA during that 60-minute window
    - Equipment category breakdown for the hour
    - Top 5 individual machinery meters
    - Power quality (THD, PF) during the hour
    - Engineering verdict on anomaly cause
    """
    norm_date = date_service.normalize_and_validate_date(date) or date
    valid, err = _validate_date(norm_date)
    if not valid:
        return {"error": err}

    if not 0 <= hour <= 23:
        return {"error": f"Invalid hour: {hour}. Must be 0-23."}

    return _safe_call(RCAService.explain_hourly_anomaly, norm_date, hour)


# ==============================================================================
# Tool 6: search_knowledge_base (EMS Reference Search)
# ==============================================================================

@tool
def search_knowledge_base(query: str) -> Dict[str, Any]:
    """
    Search the Yamaha EMS reference documentation for definitions, formulas, and operational rules.

    USE THIS TOOL FOR:
    - "What is THD limit?"
    - "How is energy calculated?"
    - "Meter mapping rules"
    - "Shift boundary definitions"
    - "Tariff rate structure"

    Parameters:
    - query: Search query (at least 3 characters)

    Returns matching sections from EMS reference documentation.
    """
    if not query or len(query.strip()) < 3:
        return {"error": "Query too short. Provide at least 3 characters."}

    results = ems_kb.search(query.strip(), top_k=2)
    return {"query": query, "results": results, "success": True}


# ==============================================================================
# ==============================================================================
# Tool 7: execute_custom_sql (Ad-hoc Read-only Queries & RAG Retrieval Interface)
# ==============================================================================

# SQL security: allowed patterns and denied keywords
_SQL_WRITE_KEYWORDS = frozenset([
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    "GRANT", "REVOKE", "MERGE", "REPLACE", "ATTACH", "DETACH", "RENAME",
    "OPTIMIZE", "KILL", "SET", "SYSTEM", "WATCH",
])

_SQL_DANGEROUS_PATTERNS = [
    r";\s*\w",  # Multiple statements
    r"--",     # SQL comments
    r"/\*",    # Block comments
    r"INTO\s+OUTFILE",  # File writes
    r"LOAD\s+DATA",     # File reads
]


def _validate_sql_query(query: str) -> tuple[bool, str]:
    """
    Validate SQL query for read-only safety.
    Returns (is_safe, error_message).
    """
    if not query or not query.strip():
        return False, "Empty query provided."

    clean_q = query.strip()
    upper_q = clean_q.upper()

    # Must start with SELECT or WITH (for CTEs)
    first_word = upper_q.split()[0] if upper_q.split() else ""
    if first_word not in ("SELECT", "WITH"):
        return False, "Only SELECT queries are allowed. Query must start with SELECT or WITH."

    # Strip string literals before checking SQL keywords to prevent false positives
    # on domain names like 'Information System' or tag paths containing dashes
    query_without_strings = re.sub(r"'[^']*'", "''", clean_q)
    query_without_strings = re.sub(r'"[^"]*"', '""', query_without_strings)
    upper_no_strings = query_without_strings.upper()

    # Check for write keywords anywhere in query outside string literals
    tokens = set(re.findall(r'\b[A-Z_]+\b', upper_no_strings))
    forbidden = tokens & _SQL_WRITE_KEYWORDS
    if forbidden:
        return False, f"Write operations not allowed: {', '.join(sorted(forbidden))}"

    # Check for dangerous patterns outside string literals
    for pattern in _SQL_DANGEROUS_PATTERNS:
        if re.search(pattern, query_without_strings, re.IGNORECASE):
            return False, f"Query contains disallowed pattern: {pattern}"

    return True, ""


@tool
def execute_custom_sql(query: str) -> Any:
    """
    Execute read-only SELECT query against the operational telemetry database (ClickHouse).

    USE THIS TOOL FOR:
    - opcda_readings: tag_id, reading_timestamp, value (raw telemetry)
    - tag_daily_energy_rollup: day, tag_id, max_value, min_value (daily aggregates with maxMerge/minMerge)

    SECURITY:
    - Only SELECT or WITH queries allowed
    - Limited to 50 rows maximum
    - Write and mutation operations blocked
    - Comments and multi-statement queries blocked

    Parameters:
    - query: Read-only SELECT query

    Returns query results as a list of row dictionaries (max 50 rows).
    """
    is_safe, err = _validate_sql_query(query)
    if not is_safe:
        return {"error": err, "success": False}

    # Ensure LIMIT exists and is reasonable
    exec_query = query.rstrip(";")
    upper_q = exec_query.upper()

    if "LIMIT" not in upper_q:
        exec_query += " LIMIT 50"
    else:
        # Extract and cap existing LIMIT
        match = re.search(r'LIMIT\s+(\d+)', upper_q)
        if match:
            limit_val = int(match.group(1))
            if limit_val > 50:
                exec_query = re.sub(
                    r'LIMIT\s+\d+',
                    'LIMIT 50',
                    exec_query,
                    flags=re.IGNORECASE
                )

    # Auto-sanitize common ClickHouse String type pitfalls on opcda_readings
    if "opcda_readings" in exec_query.lower():
        exec_query = re.sub(
            r'\b(max|min|avg|sum)\s*\(\s*value\s*\)',
            r'\1(toFloat64OrNull(value))',
            exec_query,
            flags=re.IGNORECASE
        )
        exec_query = re.sub(
            r'\bvalue\s*([><=]+)\s*(\d+)',
            r'toFloat64OrNull(value) \1 \2',
            exec_query,
            flags=re.IGNORECASE
        )

    try:
        return db_client.execute_query(exec_query)
    except Exception as e:
        err_str = str(e)
        hint = ""
        if "Illegal types String and String" in err_str or "minus" in err_str:
            hint = " HINT: In opcda_readings, 'value' is String. Cast via toFloat64OrNull(value): e.g. max(toFloat64OrNull(value)) - min(toFloat64OrNull(value)), or query tag_daily_energy_rollup: SELECT tag_id, maxMerge(max_value) - minMerge(min_value) FROM tag_daily_energy_rollup WHERE day = '...' GROUP BY tag_id. RETRY WITH CORRECTED QUERY."
        elif "AggregateFunction" in err_str:
            hint = " HINT: In tag_daily_energy_rollup, max_value and min_value are AggregateFunctions. Must use combinators: maxMerge(max_value) - minMerge(min_value) GROUP BY day, tag_id. RETRY WITH CORRECTED QUERY."
        return {"error": f"{err_str}.{hint}", "success": False}


# ==============================================================================
# Tool Registry (Exactly 7 Tools)
# ==============================================================================

ALL_EMS_TOOLS = [
    # Primary unified tools (3)
    get_cummulative_energy,
    get_instantaneous_energy,
    grouping_energy,
    # Multi-date aggregation (1)
    aggregate_multi_date,
    # Specialist tools (4)
    diagnose_consumption,
    explain_hourly_anomaly,
    search_knowledge_base,
    execute_custom_sql,
]
