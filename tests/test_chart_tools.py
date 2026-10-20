"""
Unit Tests for Advanced Chart & Graph Tools (src/tools/chart_tools.py)
Validates schema compliance, best representation heuristics, and telemetry payload.
"""

import pytest
from src.tools.chart_tools import (
    create_breakdown_chart,
    create_time_series_chart,
    create_shift_comparison_chart,
    create_demand_utilization_gauge,
    create_correlation_scatter_plot,
    create_load_heatmap,
)

SAMPLE_DATE = "2026-10-15"
SAMPLE_START_DATE = "2026-10-10"
SAMPLE_END_DATE = "2026-10-12"

def test_create_breakdown_chart_equipment_wise():
    # Category count is <= 8 -> Defaults to Donut with Center KPI
    res = create_breakdown_chart.invoke({
        "date": SAMPLE_DATE,
        "breakdown_type": "equipment_wise"
    })
    assert res["chart_type"] == "donut"
    assert "Equipment-Wise Energy Breakdown" in res["title"]
    assert len(res["x_labels"]) <= 8
    assert res["center_kpi"] is not None
    assert "kWh" in res["center_kpi"]["value"]
    assert len(res["series"]) == 1
    assert len(res["series"][0]["data"]) == len(res["x_labels"])
    assert "representation_reason" in res

def test_create_breakdown_chart_zone_wise():
    # Cost centers count is 17 (> 8) -> Defaults to Bar chart to avoid crowding
    res = create_breakdown_chart.invoke({
        "date": SAMPLE_DATE,
        "breakdown_type": "zone_wise"
    })
    assert res["chart_type"] == "bar"
    assert "Zone-Wise Cost Center Breakdown" in res["title"]
    assert len(res["x_labels"]) == 17
    assert len(res["series"][0]["data"]) == 17

def test_create_breakdown_chart_pie_override():
    # Explicitly requesting pie chart
    res = create_breakdown_chart.invoke({
        "date": SAMPLE_DATE,
        "breakdown_type": "tariff_bands",
        "preferred_type": "pie"
    })
    assert res["chart_type"] == "pie"
    assert "TOD Tariff Band" in res["title"]
    assert len(res["x_labels"]) == 3  # Off-Peak, Normal, Peak

def test_create_time_series_chart_apparent_power():
    res = create_time_series_chart.invoke({
        "date": SAMPLE_DATE,
        "metric": "apparent_power"
    })
    assert res["chart_type"] == "line"
    assert res["threshold_line"] == 1180.0
    assert "80% Threshold Limit" in res["threshold_label"]
    assert len(res["x_labels"]) == 24
    assert len(res["series"][0]["data"]) == 24

def test_create_time_series_chart_hourly_kwh():
    res = create_time_series_chart.invoke({
        "date": SAMPLE_DATE,
        "metric": "hourly_kwh"
    })
    assert res["chart_type"] == "bar"
    assert len(res["x_labels"]) == 24
    assert res["series"][0]["unit"] == "kWh"

def test_create_time_series_chart_thd_and_steam():
    # Voltage THD
    v_res = create_time_series_chart.invoke({
        "date": SAMPLE_DATE,
        "metric": "voltage_thd"
    })
    assert v_res["chart_type"] == "line"
    assert v_res["threshold_line"] == 5.0

    # Current THD
    c_res = create_time_series_chart.invoke({
        "date": SAMPLE_DATE,
        "metric": "current_thd"
    })
    assert c_res["chart_type"] == "line"
    assert c_res["threshold_line"] == 8.0

    # Steam Flow
    s_res = create_time_series_chart.invoke({
        "date": SAMPLE_DATE,
        "metric": "steam_flow"
    })
    assert s_res["chart_type"] == "area"
    assert s_res["series"][0]["unit"] == "kg/h"

def test_create_shift_comparison_single_day():
    # Single day defaults to Donut
    res = create_shift_comparison_chart.invoke({
        "start_date": SAMPLE_DATE
    })
    assert res["chart_type"] == "donut"
    assert len(res["x_labels"]) == 3  # Shifts A, B, C
    assert res["center_kpi"] is not None

def test_create_shift_comparison_multi_day():
    # Multi-day defaults to Stacked Bar
    res = create_shift_comparison_chart.invoke({
        "start_date": SAMPLE_START_DATE,
        "end_date": SAMPLE_END_DATE
    })
    assert res["chart_type"] == "stacked_bar"
    assert len(res["x_labels"]) == 3  # 3 days
    assert len(res["series"]) == 3  # Shift A, Shift B, Shift C
    assert res["series"][0]["name"] == "Shift A (Day)"
    assert res["series"][1]["name"] == "Shift B (Evening)"
    assert res["series"][2]["name"] == "Shift C (Night)"

def test_create_demand_utilization_gauge():
    res = create_demand_utilization_gauge.invoke({
        "date": SAMPLE_DATE
    })
    assert res["chart_type"] == "gauge"
    assert res["gauge_data"] is not None
    assert res["gauge_data"]["max_value"] == 1475.0
    assert res["gauge_data"]["threshold_value"] == 1180.0
    assert res["gauge_data"]["status"] in ("NORMAL", "CRITICAL")
    assert res["threshold_line"] == 1180.0

def test_create_correlation_scatter_plot():
    # Steam Flow vs Pressure
    res_steam = create_correlation_scatter_plot.invoke({
        "date": SAMPLE_DATE,
        "pair_type": "steam_flow_vs_pressure"
    })
    assert res_steam["chart_type"] == "scatter"
    assert res_steam["scatter_series"] is not None
    assert len(res_steam["scatter_series"][0]["points"]) > 0

    # Real Power vs Current THD
    res_thd = create_correlation_scatter_plot.invoke({
        "date": SAMPLE_DATE,
        "pair_type": "power_vs_current_thd"
    })
    assert res_thd["chart_type"] == "scatter"
    assert res_thd["scatter_series"] is not None
    assert len(res_thd["scatter_series"][0]["points"]) > 0

def test_create_load_heatmap():
    res = create_load_heatmap.invoke({
        "start_date": SAMPLE_START_DATE,
        "end_date": SAMPLE_END_DATE
    })
    assert res["chart_type"] == "heatmap"
    assert res["heatmap_data"] is not None
    assert len(res["heatmap_data"]["x_labels"]) == 24  # 24 hours
    assert len(res["heatmap_data"]["y_labels"]) == 3   # 3 days
    assert len(res["heatmap_data"]["z_matrix"]) == 3
    assert len(res["heatmap_data"]["z_matrix"][0]) == 24
