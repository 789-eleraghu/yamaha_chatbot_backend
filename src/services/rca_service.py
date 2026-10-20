"""
Root Cause Analysis (RCA) & Anomaly Detection Service
Answers:
- 'Why was consumption high?'
- 'Why was there a sudden spike in demand / energy?'
- 'What went wrong at 15:00?'
- 'Explain Shift C night baseload leaks and power quality excursions.'
Retrieves granular telemetry from opcda_readings to provide physical engineering deductions.
"""

import datetime
from typing import Any, Dict, List, Optional
from src.core.constants import (
    CATEGORY_EXCLUDED_TAGS,
    CONTRACTED_DEMAND_KVA,
    CURRENT_THD_TAGS,
    EQUIPMENT_WISE_CATEGORIES,
    PEAK_DEMAND_TAG,
    PEAK_DEMAND_THRESHOLD_KVA,
    SHIFT_ENERGY_TAG,
    STEAM_FLOW_RATE_TAG,
    STEAM_PRESSURE_TAG,
    VOLTAGE_THD_TAGS,
)
from src.db.sqlite_client import db_client
from src.services.breakdown_service import BreakdownService
from src.services.demand_service import DemandService
from src.services.energy_service import EnergyService
from src.services.power_quality_service import PowerQualityService
from src.services.shift_service import ShiftService
from src.services.tariff_service import TariffService

class RCAService:
    @staticmethod
    def diagnose_day(date_str: str) -> Dict[str, Any]:
        """
        Diagnose overall daily anomalous consumption on date_str:
        1. Compare against 30-day baseline for the same day-of-week
        2. Identify top variance drivers across Equipment Categories
        3. Check for night shift (Shift C) baseload inflation
        4. Cross-reference peak demand excursions
        """
        target_energy = EnergyService.get_facility_daily_energy(date_str)
        day_kwh = target_energy.get("energy_kwh") or 0.0

        target_dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        weekday = target_dt.weekday()

        # Query past days for baseline
        q_history = """
            SELECT date, energy
            FROM tag_daily_energy_rollup
            WHERE tag_id = ? AND date < ?
            ORDER BY date DESC
            LIMIT 30;
        """
        history_rows = db_client.execute_query(q_history, (SHIFT_ENERGY_TAG, date_str))
        
        same_day_vals = [
            float(r["energy"]) for r in history_rows 
            if datetime.datetime.strptime(r["date"], "%Y-%m-%d").date().weekday() == weekday
        ]
        baseline_kwh = round(sum(same_day_vals) / len(same_day_vals), 1) if same_day_vals else day_kwh
        variance_kwh = round(day_kwh - baseline_kwh, 1)
        variance_pct = round((variance_kwh / baseline_kwh) * 100.0, 1) if baseline_kwh > 0 else 0.0

        equipment_breakdown = BreakdownService.get_equipment_wise_breakdown(date_str)
        cost_center_breakdown = BreakdownService.get_zone_wise_cost_centers(date_str)
        shift_data = ShiftService.get_shift_consumption(date_str)
        demand_data = DemandService.get_peak_demand_analysis(date_str)

        top_categories = equipment_breakdown.get("categories", [])[:3]
        top_cost_centers = cost_center_breakdown.get("cost_centers", [])[:3]

        return {
            "target_date": date_str,
            "actual_consumption_kwh": day_kwh,
            "baseline_consumption_kwh": baseline_kwh,
            "variance_kwh": variance_kwh,
            "variance_percent": variance_pct,
            "is_anomaly": variance_pct > 10.0,
            "shift_distribution": {
                "shift_a_kwh": shift_data.get("shift_a_kwh"),
                "shift_b_kwh": shift_data.get("shift_b_kwh"),
                "shift_c_kwh": shift_data.get("shift_c_kwh"),
            },
            "peak_demand": {
                "peak_kva": demand_data.get("peak_kva"),
                "utilization_percent": demand_data.get("utilization_percent"),
                "excursions_above_1180kva": demand_data.get("excursion_events_count", 0)
            },
            "top_consuming_categories": top_categories,
            "top_consuming_cost_centers": top_cost_centers
        }

    @staticmethod
    def detect_and_explain_spikes(
        date_str: str, 
        anomaly_type: str = "all"
    ) -> Dict[str, Any]:
        """
        Deep-dive multi-domain anomaly & spike detector:
        1. Peak Demand Excursions (> 1180 kVA or sharp spikes) with culprit machines.
        2. Hourly Consumption Spikes (highest hour vs daily mean) with category breakdown.
        3. Shift C Baseload Leaks (un-shutdown equipment overnight).
        4. Power Quality Harmonic and Power Factor Excursions.
        5. Steam utility spikes and pressure drops.
        """
        anomalies_found: List[Dict[str, Any]] = []
        findings_summary: List[str] = []

        # ---------------------------------------------------------
        # 1. Peak Demand Spikes & Excursions
        # ---------------------------------------------------------
        if anomaly_type in ("all", "peak_demand"):
            demand_info = DemandService.get_peak_demand_analysis(date_str)
            peak_kva = demand_info.get("peak_kva") or 0.0
            excursions = demand_info.get("excursion_events") or []

            if excursions:
                for exc in excursions:
                    start_t = exc["start_time"]
                    end_t = exc["end_time"]
                    exc_peak = exc["max_kva"]
                    duration_min = exc["count"]

                    # Query top devices active during excursion window
                    culprit_tags = RCAService._get_top_active_devices_in_window(start_t, end_t, limit=5)

                    diag = (
                        f"CRITICAL DEMAND SPIKE: Apparent power peaked at {exc_peak:,.1f} kVA "
                        f"(exceeding 1180.0 kVA limit by {round(exc_peak - PEAK_DEMAND_THRESHOLD_KVA, 1)} kVA) "
                        f"between {start_t[11:16]} and {end_t[11:16]} IST ({duration_min} minutes). "
                        f"Primary physical driver: simultaneous heavy motor and press loading across "
                        f"{', '.join(t['device_name'] for t in culprit_tags[:3])}."
                    )
                    findings_summary.append(diag)
                    anomalies_found.append({
                        "domain": "peak_demand",
                        "severity": "CRITICAL",
                        "metric": f"{exc_peak} kVA",
                        "threshold": f"{PEAK_DEMAND_THRESHOLD_KVA} kVA",
                        "window": f"{start_t} to {end_t}",
                        "duration_minutes": duration_min,
                        "explanation": diag,
                        "culprit_devices": culprit_tags
                    })
            elif peak_kva > 1100.0:
                diag = f"High demand notice: Peak apparent power reached {peak_kva} kVA (utilizing {demand_info.get('utilization_percent')}%), near the 1180 kVA threshold."
                anomalies_found.append({
                    "domain": "peak_demand",
                    "severity": "WARNING",
                    "metric": f"{peak_kva} kVA",
                    "threshold": f"{PEAK_DEMAND_THRESHOLD_KVA} kVA",
                    "explanation": diag
                })

        # ---------------------------------------------------------
        # 2. Hourly Consumption Spikes
        # ---------------------------------------------------------
        if anomaly_type in ("all", "hourly_spike"):
            tariff_res = TariffService.calculate_daily_cost(date_str)
            hourly_list = tariff_res.get("hourly_breakdown") or []
            if hourly_list:
                kwh_vals = [h["rescaled_kwh"] for h in hourly_list]
                mean_kwh = sum(kwh_vals) / len(kwh_vals) if kwh_vals else 0.0
                max_kwh = max(kwh_vals)
                max_idx = kwh_vals.index(max_kwh)
                max_hour_label = hourly_list[max_idx]["hour_label"]

                # Spike threshold: 25% above daily average hour
                if max_kwh > (1.25 * mean_kwh) and max_kwh > 500:
                    spike_hour_num = int(max_hour_label.split(":")[0])
                    hourly_diag = RCAService.explain_hourly_anomaly(date_str, spike_hour_num)
                    
                    diag_text = (
                        f"HOURLY LOAD SPIKE: Hour {max_hour_label} surged to {max_kwh:,.1f} kWh "
                        f"({round(((max_kwh - mean_kwh) / mean_kwh) * 100, 1)}% above daily average {round(mean_kwh, 1)} kWh/hr). "
                        f"Top consuming category: {hourly_diag['top_category']} ({hourly_diag['top_category_kwh']} kWh)."
                    )
                    findings_summary.append(diag_text)
                    anomalies_found.append({
                        "domain": "hourly_energy",
                        "severity": "WARNING",
                        "hour": max_hour_label,
                        "hourly_kwh": max_kwh,
                        "mean_hourly_kwh": round(mean_kwh, 1),
                        "explanation": diag_text,
                        "hourly_details": hourly_diag
                    })

        # ---------------------------------------------------------
        # 3. Shift C Baseload Leaks (00:40 to 08:00)
        # ---------------------------------------------------------
        if anomaly_type in ("all", "shift_c_baseload"):
            shift_info = ShiftService.get_shift_consumption(date_str)
            shift_c_kwh = shift_info.get("shift_c_kwh") or 0.0
            shift_a_kwh = shift_info.get("shift_a_kwh") or 0.0
            
            # Shift C duration = 7h 20m = 7.333 hours
            shift_c_rate = shift_c_kwh / 7.333 if shift_c_kwh > 0 else 0.0
            
            # Anomaly: Shift C average rate > 65% of Shift A day rate or > 1200 kWh/hr
            shift_a_rate = shift_a_kwh / 9.0 if shift_a_kwh > 0 else 0.0
            if shift_c_rate > 1200 or (shift_a_rate > 0 and (shift_c_rate / shift_a_rate) > 0.65):
                culprits_c = RCAService._get_top_active_devices_in_window(
                    f"{date_str} 00:40:00", f"{date_str} 08:00:00", limit=5
                )
                diag_c = (
                    f"SHIFT C BASELOAD ANOMALY: Night shift energy averaged {round(shift_c_rate, 1)} kWh/hr "
                    f"(Total {shift_c_kwh:,.1f} kWh), indicating substantial idle baseload leakage. "
                    f"Top running equipment overnight: {', '.join(t['device_name'] for t in culprits_c[:3])}."
                )
                findings_summary.append(diag_c)
                anomalies_found.append({
                    "domain": "shift_c_baseload",
                    "severity": "WARNING",
                    "shift_c_kwh": shift_c_kwh,
                    "hourly_rate_kwh": round(shift_c_rate, 1),
                    "explanation": diag_c,
                    "culprit_devices": culprits_c
                })

        # ---------------------------------------------------------
        # 4. Power Quality (THD & Power Factor)
        # ---------------------------------------------------------
        if anomaly_type in ("all", "power_quality"):
            thd_info = PowerQualityService.get_thd_analysis(date_str)
            max_v_thd = thd_info.get("voltage_thd", {}).get("max_percent") or 0.0
            max_c_thd = thd_info.get("current_thd", {}).get("max_percent") or 0.0

            if max_v_thd > 5.0:
                msg = f"VOLTAGE HARMONIC SPIKE: Peak Voltage THD reached {max_v_thd}% (exceeding IEEE 519 5.0% limit)."
                findings_summary.append(msg)
                anomalies_found.append({
                    "domain": "power_quality",
                    "metric": "voltage_thd",
                    "severity": "WARNING",
                    "peak_value": f"{max_v_thd}%",
                    "limit": "5.0%",
                    "explanation": msg
                })

            if max_c_thd > 8.0:
                msg = f"CURRENT HARMONIC SPIKE: Peak Current THD reached {max_c_thd}% (exceeding IEEE 519 8.0% limit) due to non-linear VFD loading."
                findings_summary.append(msg)
                anomalies_found.append({
                    "domain": "power_quality",
                    "metric": "current_thd",
                    "severity": "WARNING",
                    "peak_value": f"{max_c_thd}%",
                    "limit": "8.0%",
                    "explanation": msg
                })

            # Check min PF
            pf_tag = "HT_Room.South_Utilities_1000kVA_Transformer/Power Factors/Power Factor Total/Power Factor Total"
            q_pf = """
                SELECT MIN(value / 100.0) as min_pf, reading_timestamp
                FROM opcda_readings
                WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ? AND value > 0;
            """
            pf_rows = db_client.execute_query(q_pf, (pf_tag, f"{date_str} 00:00:00", f"{date_str} 23:59:59"))
            if pf_rows and pf_rows[0]["min_pf"] is not None:
                min_pf = round(float(pf_rows[0]["min_pf"]), 3)
                if min_pf < 0.90:
                    pf_time = pf_rows[0]["reading_timestamp"][11:16]
                    msg = f"POWER FACTOR SAG: Power factor dropped to {min_pf} at {pf_time} IST (below 0.90 target)."
                    findings_summary.append(msg)
                    anomalies_found.append({
                        "domain": "power_quality",
                        "metric": "power_factor",
                        "severity": "WARNING",
                        "min_value": min_pf,
                        "timestamp": pf_time,
                        "explanation": msg
                    })

        # ---------------------------------------------------------
        # 5. Steam Utility Surges
        # ---------------------------------------------------------
        if anomaly_type in ("all", "steam"):
            q_steam = """
                SELECT MAX(value) as max_flow, MIN(value) as min_press
                FROM opcda_readings
                WHERE tag_id IN (?, ?) AND reading_timestamp >= ? AND reading_timestamp <= ?;
            """
            s_rows = db_client.execute_query(q_steam, (
                STEAM_FLOW_RATE_TAG, STEAM_PRESSURE_TAG, f"{date_str} 00:00:00", f"{date_str} 23:59:59"
            ))
            # Individual queries for flow and pressure
            q_flow = f"SELECT MAX(value) as val FROM opcda_readings WHERE tag_id = '{STEAM_FLOW_RATE_TAG}' AND reading_timestamp >= ? AND reading_timestamp <= ?"
            q_pres = f"SELECT MIN(value) as val FROM opcda_readings WHERE tag_id = '{STEAM_PRESSURE_TAG}' AND reading_timestamp >= ? AND reading_timestamp <= ? AND value > 0"
            f_res = db_client.execute_query(q_flow, (f"{date_str} 00:00:00", f"{date_str} 23:59:59"))
            p_res = db_client.execute_query(q_pres, (f"{date_str} 00:00:00", f"{date_str} 23:59:59"))

            max_f = round(float(f_res[0]["val"]), 1) if f_res and f_res[0]["val"] is not None else 0.0
            min_p = round(float(p_res[0]["val"]), 2) if p_res and p_res[0]["val"] is not None else 0.0

            if max_f > 850.0:
                msg = f"STEAM FLOW SPIKE: Peak steam flow rate surged to {max_f} kg/h at Blower Room."
                findings_summary.append(msg)
                anomalies_found.append({
                    "domain": "steam",
                    "metric": "flow_rate",
                    "severity": "WARNING",
                    "peak_flow_kgh": max_f,
                    "explanation": msg
                })

            if 0 < min_p < 3.2:
                msg = f"STEAM PRESSURE SAG: Steam header pressure dropped to {min_p} bar during peak draw."
                findings_summary.append(msg)
                anomalies_found.append({
                    "domain": "steam",
                    "metric": "pressure",
                    "severity": "WARNING",
                    "min_pressure_bar": min_p,
                    "explanation": msg
                })

        return {
            "date": date_str,
            "anomalies_detected_count": len(anomalies_found),
            "findings_summary": findings_summary if findings_summary else ["No abnormal spikes or excursions detected on this date."],
            "detailed_anomalies": anomalies_found
        }

    @staticmethod
    def explain_hourly_anomaly(date_str: str, hour: int) -> Dict[str, Any]:
        """
        Pinpoints and explains why energy or demand was abnormal during a specific hour [hour:00, hour:59].
        Retrieves:
        - Total facility kWh
        - Peak apparent power (kVA)
        - Equipment category breakdown for that hour
        - Top 5 individual machinery meters driving consumption
        - Power quality (THD & PF)
        """
        if not (0 <= hour <= 23):
            return {"error": f"Invalid hour: {hour}. Must be between 0 and 23."}

        start_ts = f"{date_str} {hour:02d}:00:00"
        end_ts = f"{date_str} {hour:02d}:59:59"

        # Facility kWh
        facility_kwh = db_client.get_tag_delta(SHIFT_ENERGY_TAG, start_ts, end_ts) or 0.0
        facility_kwh = round(facility_kwh, 1)

        # Peak kVA in hour
        q_peak = f"""
            SELECT MAX(value) as max_kva, AVG(value) as avg_kva
            FROM opcda_readings
            WHERE tag_id = ? AND reading_timestamp >= ? AND reading_timestamp <= ?;
        """
        peak_row = db_client.execute_query(q_peak, (PEAK_DEMAND_TAG, start_ts, end_ts))
        max_kva = round(float(peak_row[0]["max_kva"]), 1) if peak_row and peak_row[0]["max_kva"] else 0.0
        avg_kva = round(float(peak_row[0]["avg_kva"]), 1) if peak_row and peak_row[0]["avg_kva"] else 0.0

        # Category breakdown in hour
        placeholders = ', '.join(['?'] * len(CATEGORY_EXCLUDED_TAGS))
        q_cat = f"""
            SELECT SUBSTR(tag_id, 1, INSTR(tag_id, '.') - 1) as category, 
                   ROUND(SUM(delta), 1) as category_kwh
            FROM (
                SELECT tag_id, MAX(value) - MIN(value) as delta
                FROM opcda_readings
                WHERE reading_timestamp >= ? AND reading_timestamp <= ?
                  AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
                  AND tag_id NOT IN ({placeholders})
                  AND tag_id NOT LIKE 'HT_Room%'
                  AND tag_id NOT LIKE 'Incomer.%'
                GROUP BY tag_id
                HAVING delta > 0
            )
            GROUP BY category
            ORDER BY category_kwh DESC;
        """
        cat_params = [start_ts, end_ts] + list(CATEGORY_EXCLUDED_TAGS)
        cat_rows = db_client.execute_query(q_cat, cat_params)
        
        categories = [
            {"category": r["category"], "kwh": float(r["category_kwh"])}
            for r in cat_rows if r["category"]
        ]
        top_cat = categories[0]["category"] if categories else "Unknown"
        top_cat_kwh = categories[0]["kwh"] if categories else 0.0

        # Top 5 machinery devices in hour
        top_devices = RCAService._get_top_active_devices_in_window(start_ts, end_ts, limit=5)

        # Power quality in hour
        q_pq = f"""
            SELECT 
                ROUND(AVG(CASE WHEN tag_id = '{VOLTAGE_THD_TAGS[3]}' THEN value END), 2) as avg_v_thd,
                ROUND(AVG(CASE WHEN tag_id = '{CURRENT_THD_TAGS[0]}' THEN value END), 2) as avg_c_thd,
                ROUND(AVG(CASE WHEN tag_id LIKE '%Power Factor Total/Power Factor Total%' THEN value / 100.0 END), 3) as avg_pf
            FROM opcda_readings
            WHERE reading_timestamp >= ? AND reading_timestamp <= ?;
        """
        pq_row = db_client.execute_query(q_pq, (start_ts, end_ts))
        avg_v_thd = pq_row[0]["avg_v_thd"] if pq_row else None
        avg_c_thd = pq_row[0]["avg_c_thd"] if pq_row else None
        avg_pf = pq_row[0]["avg_pf"] if pq_row else None

        # Determine verdict
        verdict = f"Hour {hour:02d}:00-{hour:02d}:59 IST total energy was {facility_kwh} kWh with peak demand of {max_kva} kVA. "
        if max_kva > PEAK_DEMAND_THRESHOLD_KVA:
            verdict += f"CRITICAL: Exceeded 1180 kVA threshold limit. Driven primarily by {top_cat} ({top_cat_kwh} kWh), with heavy load on {top_devices[0]['device_name']}."
        else:
            verdict += f"Load driven predominantly by {top_cat} ({top_cat_kwh} kWh)."

        return {
            "date": date_str,
            "hour": f"{hour:02d}:00",
            "time_window": f"{start_ts} to {end_ts}",
            "facility_kwh": facility_kwh,
            "peak_apparent_power_kva": max_kva,
            "average_apparent_power_kva": avg_kva,
            "threshold_exceeded": max_kva > PEAK_DEMAND_THRESHOLD_KVA,
            "top_category": top_cat,
            "top_category_kwh": top_cat_kwh,
            "equipment_categories": categories,
            "top_active_devices": top_devices,
            "power_quality": {
                "voltage_thd_percent": avg_v_thd,
                "current_thd_percent": avg_c_thd,
                "power_factor": avg_pf
            },
            "engineering_verdict": verdict
        }

    @staticmethod
    def _get_top_active_devices_in_window(start_ts: str, end_ts: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Helper to find top individual equipment devices consuming energy in a time window."""
        placeholders = ', '.join(['?'] * len(CATEGORY_EXCLUDED_TAGS))
        q = f"""
            SELECT tag_id, MAX(value) - MIN(value) as delta
            FROM opcda_readings
            WHERE reading_timestamp >= ? AND reading_timestamp <= ?
              AND tag_id LIKE '%Energies/Real Energy/Real Energy Into the Load'
              AND tag_id NOT IN ({placeholders})
              AND tag_id NOT LIKE 'HT_Room%'
              AND tag_id NOT LIKE 'Incomer.%'
            GROUP BY tag_id
            HAVING delta > 0
            ORDER BY delta DESC
            LIMIT {limit};
        """
        params = [start_ts, end_ts] + list(CATEGORY_EXCLUDED_TAGS)
        rows = db_client.execute_query(q, params)

        results = []
        for r in rows:
            tag = r["tag_id"]
            device_name = tag.split("/")[0] if "/" in tag else tag
            results.append({
                "device_name": device_name,
                "tag_id": tag,
                "energy_kwh": round(float(r["delta"]), 1)
            })
        return results
