"""
Unit & Integration Tests for Services and Tools
"""

import pytest
from src.services.energy_service import EnergyService
from src.services.shift_service import ShiftService
from src.services.tariff_service import TariffService
from src.services.demand_service import DemandService
from src.services.dg_service import DGService
from src.services.power_quality_service import PowerQualityService
from src.services.breakdown_service import BreakdownService
from src.services.rca_service import RCAService
from src.rag.retriever import ems_kb
from src.tools.energy_tools import (
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
)

TEST_DATE = "2026-10-15"
TEST_MONTH = "2026-10"

def test_energy_service():
    res = EnergyService.get_facility_daily_energy(TEST_DATE)
    assert res["date"] == TEST_DATE
    assert res["energy_kwh"] > 0
    assert "source" in res

def test_shift_service():
    res = ShiftService.get_shift_consumption(TEST_DATE)
    assert res["date"] == TEST_DATE
    assert res["shift_a_kwh"] is not None and res["shift_a_kwh"] > 0
    assert res["shift_b_kwh"] is not None and res["shift_b_kwh"] > 0
    assert res["shift_c_kwh"] is not None and res["shift_c_kwh"] > 0
    assert res["total_shifts_kwh"] > 0

def test_tariff_service():
    res = TariffService.calculate_daily_cost(TEST_DATE)
    assert res["date"] == TEST_DATE
    assert res["total_cost_inr"] > 0
    assert res["rescaling_factor"] > 0
    assert len(res["hourly_breakdown"]) == 24
    assert "Peak" in res["band_summary"]

def test_demand_service():
    res = DemandService.get_peak_demand_analysis(TEST_DATE)
    assert res["date"] == TEST_DATE
    assert res["peak_kva"] is not None and res["peak_kva"] > 0
    assert res["utilization_percent"] > 0
    assert len(res["hourly_profile"]) == 24

def test_dg_service():
    res = DGService.get_dg_monthly_metrics(TEST_MONTH)
    assert res["month"] == TEST_MONTH
    assert res["runtime_minutes"] >= 0
    assert res["energy_generated_kwh"] >= 0

def test_power_quality_service():
    thd = PowerQualityService.get_thd_analysis(TEST_DATE)
    assert thd["voltage_thd"]["average_percent"] > 0
    assert thd["current_thd"]["average_percent"] > 0

    re = PowerQualityService.get_reactive_energy(TEST_DATE)
    assert "HT_Room" in re["transformers"]
    assert re["transformers"]["HT_Room"] > 0

    steam = PowerQualityService.get_steam_summary(TEST_DATE)
    assert steam["current_flow_rate_kgh"] > 0
    assert steam["steam_consumed_kg"] > 0

def test_breakdown_service():
    eq = BreakdownService.get_equipment_wise_breakdown(TEST_DATE)
    assert eq["categories_count"] == 8
    assert eq["total_kwh"] > 0

    cc = BreakdownService.get_zone_wise_cost_centers(TEST_DATE)
    assert cc["cost_centers_count"] == 17
    assert cc["total_kwh"] > 0

def test_rca_service():
    rca = RCAService.diagnose_day(TEST_DATE)
    assert rca["target_date"] == TEST_DATE
    assert rca["actual_consumption_kwh"] > 0
    assert rca["baseline_consumption_kwh"] > 0
    assert "variance_kwh" in rca
    assert "top_consuming_categories" in rca

    # Test spike detection on normal day
    spikes_normal = RCAService.detect_and_explain_spikes(TEST_DATE)
    assert spikes_normal["date"] == TEST_DATE
    assert "findings_summary" in spikes_normal

    # Test spike detection on day with excursion (2026-10-17)
    spikes_exc = RCAService.detect_and_explain_spikes("2026-10-17")
    assert spikes_exc["anomalies_detected_count"] > 0
    assert any(a["domain"] == "peak_demand" for a in spikes_exc["detailed_anomalies"])

    # Test hourly anomaly drill-down (Hour 15 on 2026-10-17)
    hourly_diag = RCAService.explain_hourly_anomaly("2026-10-17", 15)
    assert hourly_diag["hour"] == "15:00"
    assert hourly_diag["facility_kwh"] > 0
    assert hourly_diag["peak_apparent_power_kva"] > 1180.0
    assert hourly_diag["threshold_exceeded"] is True
    assert len(hourly_diag["equipment_categories"]) > 0
    assert len(hourly_diag["top_active_devices"]) > 0
    assert "CRITICAL" in hourly_diag["engineering_verdict"]

def test_rag_retriever():
    results = ems_kb.search("tariff rescaling rule")
    assert len(results) > 0
    assert any("tariff" in r["content"].lower() or "tariff" in r["header"].lower() for r in results)

def test_tools():
    # Test tool invocation
    assert get_energy_consumption.invoke({"date": TEST_DATE})["energy_kwh"] > 0
    assert get_shift_wise_consumption.invoke({"date": TEST_DATE})["total_shifts_kwh"] > 0
    assert get_cost_and_tariff.invoke({"date": TEST_DATE})["total_cost_inr"] > 0
    assert get_peak_demand_analysis.invoke({"date": TEST_DATE})["peak_kva"] > 0
    assert get_dg_generator_status.invoke({"month": TEST_MONTH})["runtime_minutes"] >= 0
    assert get_power_quality_and_utilities.invoke({"metric": "thd", "date": TEST_DATE})["voltage_thd"]["average_percent"] > 0
    assert get_breakdown_summary.invoke({"group_by": "equipment_wise", "date": TEST_DATE})["total_kwh"] > 0
    assert diagnose_high_consumption.invoke({"date": TEST_DATE})["actual_consumption_kwh"] > 0
    assert diagnose_spikes_and_anomalies.invoke({"date": "2026-10-17"})["anomalies_detected_count"] > 0
    assert explain_hourly_anomaly.invoke({"date": "2026-10-17", "hour": 15})["facility_kwh"] > 0
    assert len(search_ems_knowledge_base.invoke({"query": "shift definitions"})["results"]) > 0

if __name__ == "__main__":
    pytest.main(["-v", "tests/test_services.py"])
