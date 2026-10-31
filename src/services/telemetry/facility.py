"""
Facility Telemetry Service (Tier 1: Plant Incomers, Substation & Utilities)
Handles Whole-Plant Grid Incomer, Rooftop Solar, Substation Transformers,
Peak Apparent Power Demand, Power Factor, THD Harmonics, and Steam.
"""

from typing import Any, Dict, List, Literal, Optional
from src.core.constants import (
    CONTRACTED_DEMAND_KVA,
    CURRENT_THD_LIMIT_PERCENT,
    CURRENT_THD_TAGS,
    PEAK_DEMAND_TAG,
    PEAK_DEMAND_THRESHOLD_KVA,
    REACTIVE_ENERGY_TAGS,
    SHIFT_ENERGY_TAG,
    SOLAR_CAPACITY_KW,
    SOLAR_DEVICE_PREFIX,
    SOLAR_ENERGY_TAG,
    SOLAR_POWER_TAG,
    STEAM_FLOW_RATE_TAG,
    STEAM_PRESSURE_TAG,
    STEAM_TOTALIZER_TAG,
    VOLTAGE_THD_LIMIT_PERCENT,
    VOLTAGE_THD_TAGS,
)
from src.services.telemetry.base import (
    BaseTelemetryService,
    TelemetryCapability,
)
from src.db.client import db_client


class FacilityTelemetryService(BaseTelemetryService):
    """
    Tier 1: Whole-Facility Telemetry Service.
    Enforces plant-level contracts, transformer capacity, grid incomer counters,
    and power quality standards.
    """

    def __init__(self):
        super().__init__(
            tier_name="facility",
            supported_capabilities={
                TelemetryCapability.CUMULATIVE_ENERGY,
                TelemetryCapability.INSTANTANEOUS_POWER,
                TelemetryCapability.HOURLY_PROFILE,
                TelemetryCapability.SHIFT_BREAKDOWN,
                TelemetryCapability.POWER_QUALITY,
                TelemetryCapability.THRESHOLD_MONITORING,
                TelemetryCapability.UTILITIES_STEAM,
            }
        )

    # --------------------------------------------------------------------------
    # Grid Consumption (HT_Room 11kV Main Incomer)
    # --------------------------------------------------------------------------
    def get_grid_energy(self, date_str: str) -> Dict[str, Any]:
        """Calculates authoritative total grid energy consumption (kWh) on 11kV Main Incomer."""
        clean_date = self.normalize_date(date_str)
        start_ts, end_ts = self.get_time_window(clean_date)

        # Check daily rollup first for high performance
        rollup_val = db_client.get_daily_rollup_energy(SHIFT_ENERGY_TAG, clean_date)
        if rollup_val is not None and rollup_val > 0:
            kwh = round(float(rollup_val), 1)
            source = "daily_rollup"
        else:
            kwh = self.calculate_cumulative([SHIFT_ENERGY_TAG], start_ts, end_ts)
            source = "counter_delta"

        return {
            "date": clean_date,
            "meter": "HT_Room.11kV_Main_Incomer",
            "tag_id": SHIFT_ENERGY_TAG,
            "energy_kwh": kwh,
            "source": source,
            "formula": "max(Active_Energy_Import_kWh) - min(Active_Energy_Import_kWh)"
        }

    def get_grid_shift_energy(self, date_str: str) -> Dict[str, Any]:
        """Calculates Shift A, Shift B (with Section 9 midnight rule), and Shift C for Main Incomer."""
        return self.calculate_shift_breakdown(SHIFT_ENERGY_TAG, date_str)

    def get_grid_hourly_energy(self, date_str: str) -> Dict[str, Any]:
        """
        Calculates hour-by-hour grid energy consumption on 11kV Main Incomer.
        Uses cumulative counter delta (max - min) per hour.
        Marks future hours as unavailable for today's date.
        """
        import datetime

        clean_date = self.normalize_date(date_str)
        # Use IST timezone (UTC+5:30)
        ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        now_ist = datetime.datetime.now(ist_offset)
        current_date = now_ist.strftime("%Y-%m-%d")
        current_hour = now_ist.hour
        is_today = (clean_date == current_date)

        # Get hourly profile using cumulative counter delta method
        hourly_curve = self.calculate_hourly_profile(
            tag_ids=[SHIFT_ENERGY_TAG],
            date_str=clean_date,
            metric_type="cumulative"
        )

        # Assign shifts to each hour
        def get_shift(hour: int) -> str:
            if 8 <= hour < 17:
                return "Shift A"
            elif 17 <= hour < 24:
                return "Shift B"
            elif 0 <= hour < 1:  # 00:00-00:40 is previous day's Shift B per Section 9
                return "Shift B (prev day)"
            else:  # 01:00-07:59
                return "Shift C"

        hourly_breakdown = []
        total_kwh = 0.0

        for h in hourly_curve:
            hour_int = h["hour_int"]
            is_future = is_today and hour_int > current_hour

            if is_future:
                hourly_breakdown.append({
                    "hour": h["hour"],
                    "hour_int": hour_int,
                    "energy_kwh": None,
                    "shift": get_shift(hour_int),
                    "status": "future",
                    "note": "This hour has not occurred yet"
                })
            else:
                hourly_breakdown.append({
                    "hour": h["hour"],
                    "hour_int": hour_int,
                    "energy_kwh": h["value"],
                    "shift": get_shift(hour_int),
                    "status": "recorded"
                })
                total_kwh += h["value"]

        return {
            "date": clean_date,
            "meter": "HT_Room.11kV_Main_Incomer",
            "tag_id": SHIFT_ENERGY_TAG,
            "total_energy_kwh": round(total_kwh, 1),
            "current_hour_ist": current_hour if is_today else None,
            "is_today": is_today,
            "hourly_breakdown": hourly_breakdown,
            "formula": "hourly: max(counter) - min(counter) per hour",
            "note": "00:00-00:40 belongs to previous day's Shift B per Section 9"
        }

    # --------------------------------------------------------------------------
    # Rooftop Solar Generation (100kW Incomer.Incomer_Solar_100kW)
    # --------------------------------------------------------------------------
    def get_solar_generation(
        self,
        date_str: str,
        granularity: Literal["daily", "hourly"] = "daily"
    ) -> Dict[str, Any]:
        """Queries rooftop 100kW solar plant generation (daily rollup or 24h hourly curve)."""
        clean_date = self.normalize_date(date_str)
        start_ts, end_ts = self.get_time_window(clean_date)

        rollup_solar = db_client.get_daily_rollup_energy(SOLAR_ENERGY_TAG, clean_date)
        if rollup_solar is not None and rollup_solar > 0:
            total_kwh = round(float(rollup_solar), 1)
        else:
            total_kwh = self.calculate_cumulative([SOLAR_ENERGY_TAG], start_ts, end_ts)
        power_stats = self.calculate_instantaneous([SOLAR_POWER_TAG], start_ts, end_ts)

        base_res = {
            "date": clean_date,
            "meter": "Incomer.Incomer_Solar_100kW",
            "capacity_kw": SOLAR_CAPACITY_KW,
            "energy_generated_kwh": total_kwh,
            "peak_power_kw": power_stats.get("max", 0.0) or 0.0,
            "avg_power_kw": power_stats.get("avg", 0.0) or 0.0,
            "avg_generation_power_kw": power_stats.get("avg", 0.0) or 0.0,
            "generation_hours": round(power_stats.get("count", 0) / 60.0, 1) if power_stats.get("count") else 0.0
        }

        if granularity == "hourly":
            hourly_curve = self.calculate_hourly_profile(
                tag_ids=[SOLAR_POWER_TAG],
                date_str=clean_date,
                metric_type="instantaneous"
            )
            base_res["hourly_breakdown"] = [
                {
                    "hour": h["hour"],
                    "energy_kwh": round(h["avg_value"], 1) if h["avg_value"] else 0.0,
                    "active_power_kw": round(h["avg_value"], 1) if h["avg_value"] else 0.0,
                    "peak_power_kw": round(h["peak_value"], 1) if h["peak_value"] else 0.0,
                }
                for h in hourly_curve
            ]

        return base_res

    # --------------------------------------------------------------------------
    # Transformer Peak Demand (kVA vs 1475 Contract & 1180 Threshold)
    # --------------------------------------------------------------------------
    def get_peak_demand(self, date_str: str) -> Dict[str, Any]:
        """Monitors apparent power demand (kVA) against contracted capacity."""
        clean_date = self.normalize_date(date_str)
        start_ts, end_ts = self.get_time_window(clean_date)

        stats = self.calculate_instantaneous([PEAK_DEMAND_TAG], start_ts, end_ts)
        peak_kva = stats.get("max") or 0.0

        # Hourly curve
        hourly_curve = self.calculate_hourly_profile([PEAK_DEMAND_TAG], clean_date, metric_type="instantaneous")

        # Excursion detection (> 1180 kVA)
        q_exc = f"""
            SELECT
                reading_timestamp,
                toFloat64OrNull(value) as kva
            FROM opcda_readings
            WHERE tag_id = '{PEAK_DEMAND_TAG}'
              AND reading_timestamp >= parseDateTimeBestEffort('{start_ts}')
              AND reading_timestamp <= parseDateTimeBestEffort('{end_ts}')
              AND toFloat64OrNull(value) > {PEAK_DEMAND_THRESHOLD_KVA}
            ORDER BY reading_timestamp;
        """
        exc_rows = self.execute_query(q_exc)
        excursions = [
            {"timestamp": str(r["reading_timestamp"]), "apparent_power_kva": round(float(r["kva"]), 1)}
            for r in exc_rows
        ]

        return {
            "date": clean_date,
            "meter": "HT_Room.South_Utilities_1000kVA_Transformer",
            "contracted_demand_kva": CONTRACTED_DEMAND_KVA,
            "threshold_kva": PEAK_DEMAND_THRESHOLD_KVA,
            "peak_kva": peak_kva,
            "average_kva": stats.get("avg") or 0.0,
            "utilization_percent": round((peak_kva / CONTRACTED_DEMAND_KVA) * 100, 1) if CONTRACTED_DEMAND_KVA > 0 else 0.0,
            "threshold_exceeded": peak_kva > PEAK_DEMAND_THRESHOLD_KVA,
            "excursion_count": len(excursions),
            "excursion_events_count": len(excursions),
            "excursions": excursions[:10],
            "excursion_events": excursions[:10],
            "hourly_profile": [
                {
                    "hour": h.get("hour_int", int(h["hour"][:2])),
                    "label": h["hour"],
                    "peak_kva": h["peak_value"] or 0.0,
                    "avg_kva": h["avg_value"] or 0.0
                }
                for h in hourly_curve
            ]
        }

    # --------------------------------------------------------------------------
    # Power Quality: Total Power Factor (PF) & Harmonics (THD)
    # --------------------------------------------------------------------------
    def get_power_factor(self, date_str: str) -> Dict[str, Any]:
        """Calculates total facility PF on Main Incomer and substation transformers."""
        clean_date = self.normalize_date(date_str)
        start_ts, end_ts = self.get_time_window(clean_date)

        q_pf = """
            SELECT
                ROUND(AVG(CASE WHEN tag_id = 'HT_Room.11kV_Main_Incomer/Power Factor/PF lag tot' THEN toFloat64OrNull(value) END) / 100.0, 3) AS main_avg_pf,
                ROUND(MIN(CASE WHEN tag_id = 'HT_Room.11kV_Main_Incomer/Power Factor/PF lag tot' THEN toFloat64OrNull(value) END) / 100.0, 3) AS main_min_pf,
                ROUND(MAX(CASE WHEN tag_id = 'HT_Room.11kV_Main_Incomer/Power Factor/PF lag tot' THEN toFloat64OrNull(value) END) / 100.0, 3) AS main_max_pf,
                ROUND(AVG(CASE WHEN tag_id = 'HT_Room.11kV_Main_Incomer/Power Factor/PF lag a' THEN toFloat64OrNull(value) END) / 100.0, 3) AS phase_a_pf,
                ROUND(AVG(CASE WHEN tag_id = 'HT_Room.11kV_Main_Incomer/Power Factor/PF lag b' THEN toFloat64OrNull(value) END) / 100.0, 3) AS phase_b_pf,
                ROUND(AVG(CASE WHEN tag_id = 'HT_Room.11kV_Main_Incomer/Power Factor/PF lag c' THEN toFloat64OrNull(value) END) / 100.0, 3) AS phase_c_pf,
                ROUND(AVG(CASE WHEN tag_id = 'Incomer.North_Utilities_2000KVA_Transformer/Power Factors/Power Factor Total/Power Factor Total' THEN toFloat64OrNull(value) END) / 100.0, 3) AS north_avg_pf,
                ROUND(MIN(CASE WHEN tag_id = 'Incomer.North_Utilities_2000KVA_Transformer/Power Factors/Power Factor Total/Power Factor Total' THEN toFloat64OrNull(value) END) / 100.0, 3) AS north_min_pf,
                ROUND(MAX(CASE WHEN tag_id = 'Incomer.North_Utilities_2000KVA_Transformer/Power Factors/Power Factor Total/Power Factor Total' THEN toFloat64OrNull(value) END) / 100.0, 3) AS north_max_pf,
                ROUND(AVG(CASE WHEN tag_id = 'HT_Room.South_Utilities_1000kVA_Transformer/Power Factors/Power Factor Total/Power Factor Total' THEN toFloat64OrNull(value) END) / 100.0, 3) AS south_avg_pf
            FROM opcda_readings
            WHERE reading_timestamp >= parseDateTimeBestEffort({start_ts:String})
              AND reading_timestamp <= parseDateTimeBestEffort({end_ts:String})
              AND tag_id IN (
                'HT_Room.11kV_Main_Incomer/Power Factor/PF lag tot',
                'HT_Room.11kV_Main_Incomer/Power Factor/PF lag a',
                'HT_Room.11kV_Main_Incomer/Power Factor/PF lag b',
                'HT_Room.11kV_Main_Incomer/Power Factor/PF lag c',
                'Incomer.North_Utilities_2000KVA_Transformer/Power Factors/Power Factor Total/Power Factor Total',
                'HT_Room.South_Utilities_1000kVA_Transformer/Power Factors/Power Factor Total/Power Factor Total'
              );
        """
        rows = self.execute_query(q_pf, {"start_ts": start_ts, "end_ts": end_ts})
        row = rows[0] if rows else {}

        main_avg = row.get("main_avg_pf")
        main_min = row.get("main_min_pf")
        main_max = row.get("main_max_pf")

        if main_avg is not None:
            if main_avg >= 0.95:
                status = "Excellent"
                verdict = f"Plant average power factor of {main_avg} (Lagging) is optimal. Fully compliant with utility tariff HT_1 (>0.95), eligible for PF incentive and incurring zero penalty."
            elif main_avg >= 0.90:
                status = "Acceptable"
                verdict = f"Plant average power factor of {main_avg} is within utility tariff limits (>=0.90), but capacitor banks should be tuned to achieve >0.95 for maximum efficiency."
            else:
                status = "Low PF Warning"
                verdict = f"Plant average power factor of {main_avg} is below statutory threshold (0.90), incurring low power factor penalties on billing."
        else:
            status = "Unknown"
            verdict = "Power factor telemetry not available for the requested period."

        return {
            "date": clean_date,
            "meter": "HT_Room.11kV_Main_Incomer",
            "average_power_factor": main_avg,
            "nature": "Lagging",
            "min_power_factor": main_min,
            "max_power_factor": main_max,
            "phase_breakdown": {
                "phase_a": row.get("phase_a_pf"),
                "phase_b": row.get("phase_b_pf"),
                "phase_c": row.get("phase_c_pf"),
            },
            "transformer_power_factor": {
                "north_utilities_2000kva": row.get("north_avg_pf"),
                "south_utilities_1000kva": "Offline / No data" if row.get("south_avg_pf") is None else row.get("south_avg_pf")
            },
            "status": status,
            "compliance_verdict": verdict
        }

    def get_thd_analysis(self, date_str: str) -> Dict[str, Any]:
        """Calculates Voltage and Current THD with graceful North Utilities fallback."""
        clean_date = self.normalize_date(date_str)
        start_ts, end_ts = self.get_time_window(clean_date)

        # 1. Voltage THD on South Utilities
        v_stats = self.calculate_instantaneous([VOLTAGE_THD_TAGS[3]], start_ts, end_ts)
        v_avg = v_stats.get("avg")
        v_max = v_stats.get("max")

        # 2. Current THD on South Utilities
        c_stats = self.calculate_instantaneous(CURRENT_THD_TAGS, start_ts, end_ts)
        c_avg = c_stats.get("avg")
        c_max = c_stats.get("max")

        meter_name = "HT_Room.South_Utilities_1000kVA_Transformer"
        # Fallback to North Utilities if South Utilities is offline
        if v_avg is None and c_avg is None:
            tag_v_north = "Incomer.North_Utilities_2000KVA_Transformer/Power Quality/THD Voltage/THD Voltage L-L"
            tag_c_north = [
                "Incomer.North_Utilities_2000KVA_Transformer/Power Quality/THD Current/THD Current A",
                "Incomer.North_Utilities_2000KVA_Transformer/Power Quality/THD Current/THD Current B",
                "Incomer.North_Utilities_2000KVA_Transformer/Power Quality/THD Current/THD Current C"
            ]
            vn = self.calculate_instantaneous([tag_v_north], start_ts, end_ts)
            cn = self.calculate_instantaneous(tag_c_north, start_ts, end_ts)
            if vn.get("avg") is not None or cn.get("avg") is not None:
                v_avg = vn.get("avg")
                v_max = vn.get("max")
                c_avg = cn.get("avg")
                c_max = cn.get("max")
                meter_name = "Incomer.North_Utilities_2000KVA_Transformer (South Utilities offline)"

        return {
            "date": clean_date,
            "meter": meter_name,
            "voltage_thd": {
                "average_percent": v_avg,
                "max_percent": v_max,
                "limit_percent": VOLTAGE_THD_LIMIT_PERCENT,
                "exceeded": (v_max is not None and v_max > VOLTAGE_THD_LIMIT_PERCENT)
            },
            "current_thd": {
                "average_percent": c_avg,
                "max_percent": c_max,
                "limit_percent": CURRENT_THD_LIMIT_PERCENT,
                "exceeded": (c_max is not None and c_max > CURRENT_THD_LIMIT_PERCENT)
            }
        }

    def get_reactive_energy(self, date_str: str) -> Dict[str, Any]:
        """Calculates cumulative kVARh for trustworthy transformers."""
        clean_date = self.normalize_date(date_str)
        start_ts, end_ts = self.get_time_window(clean_date)

        results = {}
        for dev, tag in REACTIVE_ENERGY_TAGS.items():
            delta = self.calculate_cumulative([tag], start_ts, end_ts)
            results[dev] = delta if delta > 0 else None

        return {
            "date": clean_date,
            "unit": "kVARh",
            "transformers": results
        }

    # --------------------------------------------------------------------------
    # Non-Electrical Utilities: Steam Boiler
    # --------------------------------------------------------------------------
    def get_steam_summary(self, date_str: str) -> Dict[str, Any]:
        """Retrieves Steam flow rate, pressure, and cumulative kg consumed."""
        clean_date = self.normalize_date(date_str)
        start_ts, end_ts = self.get_time_window(clean_date)

        tag_list = f"'{STEAM_FLOW_RATE_TAG}', '{STEAM_PRESSURE_TAG}'"
        q_snap = f"""
            SELECT tag_id, toFloat64OrNull(value) as value, reading_timestamp
            FROM opcda_readings
            WHERE tag_id IN ({tag_list})
            ORDER BY reading_timestamp DESC
            LIMIT 2;
        """
        snap_rows = self.execute_query(q_snap)
        flow_rate = None
        pressure = None
        ts = None
        for r in snap_rows:
            ts = str(r["reading_timestamp"])
            if r["tag_id"] == STEAM_FLOW_RATE_TAG and r["value"]:
                flow_rate = round(float(r["value"]), 1)
            elif r["tag_id"] == STEAM_PRESSURE_TAG and r["value"]:
                pressure = round(float(r["value"]), 2)

        steam_kg = self.calculate_cumulative([STEAM_TOTALIZER_TAG], start_ts, end_ts)

        return {
            "date": clean_date,
            "device": "Flowmeter-Gate1.Blower_Room_Steam",
            "snapshot_timestamp": ts,
            "current_flow_rate_kgh": flow_rate,
            "current_pressure_bar": pressure,
            "steam_consumed_kg": steam_kg
        }
