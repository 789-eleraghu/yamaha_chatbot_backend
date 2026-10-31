"""
Unit & Capability Gating Tests for Telemetry OOP Architecture
Validates BaseTelemetryService, FacilityTelemetryService, GeneratorsTelemetryService,
EquipmentsTelemetryService, ZonesTelemetryService, and capability gating.
"""

import pytest
from src.services.telemetry import (
    equipments_telemetry,
    facility_telemetry,
    generators_telemetry,
    zones_telemetry,
    TelemetryCapability,
    UnsupportedCapabilityError,
)
from src.tools.energy_tools import (
    get_cummulative_energy,
    get_instantaneous_energy,
    grouping_energy,
    ALL_EMS_TOOLS,
)

TEST_DATE = "2026-10-15"
TEST_MONTH = "2026-10"


def test_capability_gating():
    """Verify that child classes strictly enforce capability gating."""
    # 1. Generators does not support shift breakdown
    with pytest.raises(UnsupportedCapabilityError) as exc_info:
        generators_telemetry.calculate_shift_breakdown("dummy_tag", TEST_DATE)
    assert "generators" in str(exc_info.value)
    assert "shift_breakdown" in str(exc_info.value)

    # 2. Equipments does not support power quality
    with pytest.raises(UnsupportedCapabilityError) as exc_info:
        equipments_telemetry.check_capability(TelemetryCapability.POWER_QUALITY)
    assert "equipments" in str(exc_info.value)
    assert "power_quality" in str(exc_info.value)

    # 3. Equipments does not support utility steam
    with pytest.raises(UnsupportedCapabilityError) as exc_info:
        equipments_telemetry.check_capability(TelemetryCapability.UTILITIES_STEAM)
    assert "equipments" in str(exc_info.value)

    # 4. Zones does not support instantaneous power
    with pytest.raises(UnsupportedCapabilityError) as exc_info:
        zones_telemetry.check_capability(TelemetryCapability.INSTANTANEOUS_POWER)
    assert "zones" in str(exc_info.value)
    assert "instantaneous_power" in str(exc_info.value)

    # 5. Zones does not support threshold monitoring
    with pytest.raises(UnsupportedCapabilityError) as exc_info:
        zones_telemetry.check_capability(TelemetryCapability.THRESHOLD_MONITORING)
    assert "zones" in str(exc_info.value)


def test_facility_telemetry_service():
    """Verify Tier 1: Facility telemetry calculations."""
    grid = facility_telemetry.get_grid_energy(TEST_DATE)
    assert grid["date"] == TEST_DATE
    assert grid["energy_kwh"] > 0
    assert grid["meter"] == "HT_Room.11kV_Main_Incomer"

    shifts = facility_telemetry.get_grid_shift_energy(TEST_DATE)
    assert shifts["date"] == TEST_DATE
    assert shifts["total_shifts_kwh"] > 0
    assert "Shift A" in shifts["shifts"]
    assert "Shift B" in shifts["shifts"]
    assert "Shift C" in shifts["shifts"]

    solar_daily = facility_telemetry.get_solar_generation(TEST_DATE, granularity="daily")
    assert solar_daily["energy_generated_kwh"] > 0
    assert solar_daily["meter"] == "Incomer.Incomer_Solar_100kW"

    solar_hourly = facility_telemetry.get_solar_generation(TEST_DATE, granularity="hourly")
    assert "hourly_breakdown" in solar_hourly
    assert len(solar_hourly["hourly_breakdown"]) == 24

    demand = facility_telemetry.get_peak_demand(TEST_DATE)
    assert demand["peak_kva"] > 0
    assert len(demand["hourly_profile"]) == 24

    pf = facility_telemetry.get_power_factor("2026-10-21")
    assert pf["average_power_factor"] is not None
    assert pf["average_power_factor"] > 0.90
    assert pf["nature"] == "Lagging"

    thd = facility_telemetry.get_thd_analysis(TEST_DATE)
    assert thd["voltage_thd"]["average_percent"] is not None

    reactive = facility_telemetry.get_reactive_energy(TEST_DATE)
    assert "HT_Room" in reactive["transformers"]

    steam = facility_telemetry.get_steam_summary(TEST_DATE)
    assert steam["steam_consumed_kg"] > 0


def test_generators_telemetry_service():
    """Verify Tier 2: Diesel Generator captive power operations."""
    monthly = generators_telemetry.get_monthly_metrics(TEST_MONTH)
    assert monthly["month"] == TEST_MONTH
    assert monthly["capacity_kva"] == 300.0
    assert monthly["runtime_minutes"] >= 0
    assert monthly["energy_generated_kwh"] >= 0

    daily = generators_telemetry.get_daily_metrics(TEST_DATE)
    assert daily["date"] == TEST_DATE
    assert daily["generator"] == "Incomer.DG_Incomer_300kVA"


def test_equipments_telemetry_service():
    """Verify Tier 3: Equipment categories and exclusions."""
    breakdown = equipments_telemetry.get_category_breakdown(TEST_DATE)
    assert breakdown["type"] == "equipment_wise"
    assert breakdown["categories_count"] == 8
    assert breakdown["total_kwh"] > 0

    cat_energy = equipments_telemetry.get_category_energy("Molding", TEST_DATE)
    assert cat_energy["category"] == "Molding"
    assert cat_energy["total_energy_kwh"] > 0
    assert cat_energy["device_count"] > 0

    telemetry = equipments_telemetry.get_device_telemetry("Molding")
    assert telemetry["status"] == "success"


def test_zones_telemetry_service():
    """Verify Tier 4: Organizational cost centers."""
    zones = zones_telemetry.list_zones()
    assert len(zones) == 17
    assert "General Admin" in zones
    assert "AG Assy" in zones

    breakdown = zones_telemetry.get_zone_breakdown(TEST_DATE)
    assert breakdown["type"] == "zone_wise_cost_centers"
    assert breakdown["cost_centers_count"] == 17
    assert breakdown["total_kwh"] > 0

    cc_energy = zones_telemetry.get_cost_center_energy("General Admin", TEST_DATE)
    assert cc_energy["cost_center"] == "General Admin"
    assert cc_energy["total_energy_kwh"] > 0


def test_unified_tool_registry():
    """Verify exactly 8 tools in the unified architecture."""
    assert len(ALL_EMS_TOOLS) == 8
    tool_names = {t.name for t in ALL_EMS_TOOLS}
    expected_names = {
        "get_cummulative_energy",
        "get_instantaneous_energy",
        "grouping_energy",
        "aggregate_multi_date",  # Multi-date aggregation
        "diagnose_consumption",
        "explain_hourly_anomaly",
        "search_knowledge_base",
        "execute_custom_sql",
    }
    assert tool_names == expected_names


def test_unified_tools_invocation():
    """Verify unified tool invocations via the 7-tool architecture."""
    # Test get_cummulative_energy for facility
    res = get_cummulative_energy.invoke({
        "start_date": TEST_DATE,
        "end_date": TEST_DATE,
        "sectors": ["facility"]
    })
    assert res["status"] == "success"
    assert "energy_kwh" in res

    # Test get_cummulative_energy for equipment category
    res = get_cummulative_energy.invoke({
        "start_date": TEST_DATE,
        "end_date": TEST_DATE,
        "sectors": ["Molding"]
    })
    assert res["status"] == "success"

    # Test get_cummulative_energy for cost center
    res = get_cummulative_energy.invoke({
        "start_date": TEST_DATE,
        "end_date": TEST_DATE,
        "sectors": ["General Admin"]
    })
    assert res["status"] == "success"

    # Test get_instantaneous_energy for DG
    res = get_instantaneous_energy.invoke({
        "date": TEST_DATE,
        "measurement": "dg_runtime"
    })
    assert res["capacity_kva"] == 300.0

    # Test grouping_energy for equipment breakdown
    res = grouping_energy.invoke({
        "date": TEST_DATE,
        "group_by": "equipment"
    })
    assert res["categories_count"] == 8

    # Test grouping_energy for zone breakdown
    res = grouping_energy.invoke({
        "date": TEST_DATE,
        "group_by": "zone"
    })
    assert res["cost_centers_count"] == 17


def test_shift_boundary_definitions():
    """Verify shift boundaries are correctly defined."""
    shifts = facility_telemetry.get_grid_shift_energy(TEST_DATE)

    # Check shift windows are present
    assert "shifts" in shifts
    assert "Shift A" in shifts["shifts"]
    assert "Shift B" in shifts["shifts"]
    assert "Shift C" in shifts["shifts"]

    # Check Shift A window
    assert shifts["shifts"]["Shift A"]["window"] == "08:00 - 17:00"

    # Check Shift C window (00:40 boundary)
    assert shifts["shifts"]["Shift C"]["window"] == "00:40 - 08:00"


if __name__ == "__main__":
    pytest.main(["-v", "tests/test_telemetry_oop.py"])
