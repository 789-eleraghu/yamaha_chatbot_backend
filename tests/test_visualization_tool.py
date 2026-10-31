"""
Unit Tests for Intelligent Visualization Tool (src/tools/visualization_tool.py)
Tests LCEL chain flow: parse_intent → retrieve_data → validate_numeric → build_chart
"""

import pytest
from src.tools.visualization_tool import create_visualization

SAMPLE_DATE = "2026-10-15"
SAMPLE_START_DATE = "2026-10-10"
SAMPLE_END_DATE = "2026-10-12"


def test_equipment_breakdown():
    res = create_visualization.invoke({
        "intent": "equipment breakdown",
        "start_date": SAMPLE_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "equipment"
    assert res["chart_config"]["chart_type"] == "donut"
    assert len(res["chart_config"]["x_labels"]) > 0
    assert len(res["chart_config"]["series"][0]["data"]) > 0
    assert res["data_source"] == "retrieved"


def test_zone_breakdown():
    res = create_visualization.invoke({
        "intent": "zone breakdown",
        "start_date": SAMPLE_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "zone"
    assert res["chart_config"]["chart_type"] == "horizontal_bar"
    assert len(res["chart_config"]["x_labels"]) == 17


def test_entity_normalization_equipment():
    # "Air Compressor" -> canonical "Compressor"
    res = create_visualization.invoke({
        "intent": "Air Compressor energy breakdown",
        "start_date": SAMPLE_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "equipment"
    assert "Compressor" in res["data"]["labels"]
    assert res["data"]["total_kwh"] > 0

    # "HVAC" -> canonical "Airconditioning"
    res_hvac = create_visualization.invoke({
        "intent": "HVAC energy breakdown",
        "start_date": SAMPLE_DATE,
    })
    assert res_hvac["status"] == "success"
    assert "Airconditioning" in res_hvac["data"]["labels"]


def test_cross_domain_filter_protection():
    # "Painting cost center breakdown" must NOT extract "Paintshop" equipment into zone filter
    res = create_visualization.invoke({
        "intent": "Painting cost center breakdown",
        "start_date": SAMPLE_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "zone"
    assert len(res["data"]["labels"]) > 0


def test_zone_trend_multi_day():
    res = create_visualization.invoke({
        "intent": "daily zone trend",
        "start_date": SAMPLE_START_DATE,
        "end_date": SAMPLE_END_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "zone_trend"
    assert res["chart_config"]["chart_type"] == "line"
    assert len(res["chart_config"]["series"]) > 0
    assert len(res["chart_config"]["x_labels"]) == 3  # 10th, 11th, 12th


def test_equipment_trend_multi_day():
    res = create_visualization.invoke({
        "intent": "equipment trend",
        "start_date": SAMPLE_START_DATE,
        "end_date": SAMPLE_END_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "equipment_trend"
    assert res["chart_config"]["chart_type"] == "line"
    assert len(res["chart_config"]["series"]) > 0


def test_facility_consumption_trend():
    res = create_visualization.invoke({
        "intent": "facility consumption over time",
        "start_date": SAMPLE_START_DATE,
        "end_date": "2026-10-15",
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "facility_trend"
    assert len(res["chart_config"]["series"][0]["data"]) == 6


def test_hourly_granularity_auto_detection():
    # User did not set granularity="hourly", but specified "hourly" in intent
    res = create_visualization.invoke({
        "intent": "hourly load profile",
        "start_date": SAMPLE_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "facility"
    assert len(res["chart_config"]["x_labels"]) == 24
    assert len(res["chart_config"]["series"][0]["data"]) == 24


def test_peak_demand_gauge():
    res = create_visualization.invoke({
        "intent": "peak demand gauge",
        "start_date": SAMPLE_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "gauge"
    assert res["chart_config"]["chart_type"] == "gauge"
    assert res["chart_config"]["gauge_data"] is not None
    assert res["chart_config"]["gauge_data"]["current_value"] > 0


def test_power_factor_compliance():
    res = create_visualization.invoke({
        "intent": "power factor compliance",
        "start_date": SAMPLE_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "power_factor"
    assert res["chart_config"]["chart_type"] == "line"
    assert res["chart_config"]["threshold_line"] == 0.95


def test_thd_voltage_vs_current():
    # Voltage THD
    v_res = create_visualization.invoke({
        "intent": "voltage THD analysis",
        "start_date": SAMPLE_DATE,
    })
    assert v_res["status"] == "success"
    assert "Voltage" in v_res["chart_config"]["title"]
    assert v_res["chart_config"]["threshold_line"] == 5.0

    # Current THD
    c_res = create_visualization.invoke({
        "intent": "current THD analysis",
        "start_date": SAMPLE_DATE,
    })
    assert c_res["status"] == "success"
    assert "Current" in c_res["chart_config"]["title"]
    assert c_res["chart_config"]["threshold_line"] == 8.0


def test_scatter_correlation():
    res = create_visualization.invoke({
        "intent": "correlation between steam flow and pressure",
        "start_date": SAMPLE_DATE,
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "scatter"
    assert res["chart_config"]["chart_type"] == "scatter"
    assert res["chart_config"]["scatter_series"] is not None
    assert len(res["chart_config"]["scatter_series"][0]["points"]) > 0


def test_fast_heatmap():
    res = create_visualization.invoke({
        "intent": "hourly heatmap",
        "start_date": SAMPLE_START_DATE,
        "end_date": "2026-10-16",
    })
    assert res["status"] == "success"
    assert res["visualization_type"] == "heatmap"
    assert res["chart_config"]["chart_type"] == "heatmap"
    assert len(res["chart_config"]["heatmap_data"]["y_labels"]) == 7
    assert len(res["chart_config"]["heatmap_data"]["x_labels"]) == 24


def test_user_chart_preference_override():
    # Bar override
    res_bar = create_visualization.invoke({
        "intent": "equipment breakdown as bar chart",
        "start_date": SAMPLE_DATE,
    })
    assert res_bar["status"] == "success"
    assert res_bar["chart_config"]["chart_type"] == "bar"

    # Pie override
    res_pie = create_visualization.invoke({
        "intent": "zone wise consumption as pie chart",
        "start_date": SAMPLE_DATE,
    })
    assert res_pie["status"] == "success"
    assert res_pie["chart_config"]["chart_type"] == "pie"


def test_pre_fetched_data_and_date_adoption():
    from src.tools.energy_tools import grouping_energy, get_instantaneous_energy

    # 1. Date adoption from EMS data
    eq = grouping_energy.invoke({"date": "2026-10-12", "group_by": "equipment"})
    v_eq = create_visualization.invoke({"intent": "equipment breakdown", "data": eq})
    assert v_eq["status"] == "success"
    assert v_eq["date"] == "2026-10-12"
    assert v_eq["data_source"] == "pre_fetched (no duplicate call)"

    # 2. Pre-fetched Current THD selection
    thd = get_instantaneous_energy.invoke({"measurement": "thd", "date": SAMPLE_DATE})
    v_thd = create_visualization.invoke({"intent": "current THD analysis", "data": thd})
    assert v_thd["status"] == "success"
    assert "Current" in v_thd["chart_config"]["title"]


def test_numeric_telemetry_validations():
    # Inverted date range
    res_inv = create_visualization.invoke({
        "intent": "hourly heatmap",
        "start_date": "2026-10-15",
        "end_date": "2026-10-10",
    })
    assert res_inv["status"] == "error"
    assert "Invalid date range" in res_inv["error"]

    # Invalid date string
    res_date = create_visualization.invoke({
        "intent": "equipment breakdown",
        "start_date": "not-a-valid-date",
    })
    assert res_date["status"] == "error"
    assert "Invalid start_date" in res_date["error"]

    # Missing end_date for heatmap
    res_heat = create_visualization.invoke({
        "intent": "hourly heatmap",
        "start_date": SAMPLE_DATE,
    })
    assert res_heat["status"] == "error"
    assert "Heatmap requires end_date" in res_heat["error"]

    # Filter with non-existent items
    res_filt = create_visualization.invoke({
        "intent": "equipment breakdown",
        "filter_items": ["FakeEquipmentCategory999"],
        "start_date": SAMPLE_DATE,
    })
    assert res_filt["status"] == "error"
    assert "No equipment data found" in res_filt["error"]
