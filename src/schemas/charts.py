"""
Chart Configuration Schemas for Rich Graphing Capabilities
Supports Plotly, Chart.js, Recharts, and ECharts frontends:
- Line, Area, Stacked Area (time series & load profiles)
- Bar, Grouped Bar, Stacked Bar (comparisons & multi-period breakdowns)
- Pie, Donut (proportions, cost center share, tariff band splits)
- Scatter, Pair Plot (correlations: e.g. Steam Flow vs Pressure, kW vs THD)
- Gauge / Radial (KPI utilization vs thresholds, e.g. Contracted 1475 kVA)
- Heatmap (Hour-of-day vs Day-of-week load matrices)
"""

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field

ChartType = Literal[
    "line",
    "bar",
    "stacked_bar",
    "grouped_bar",
    "horizontal_bar",
    "area",
    "stacked_area",
    "donut",
    "pie",
    "radar",
    "radial_bar",
    "composed",
    "treemap",
    "scatter",
    "pair_plot",
    "gauge",
    "heatmap"
]

class ChartSeries(BaseModel):
    name: str = Field(description="Name of the data series (e.g. 'Shift A', 'Peak kVA', 'Molding')")
    data: List[Union[float, int, None]] = Field(description="Array of numeric data values")
    color: Optional[str] = Field(default=None, description="Optional hex color string (e.g. '#2563EB')")
    unit: Optional[str] = Field(default=None, description="Unit of measurement (e.g. 'kWh', 'kVA', '%', '₹')")
    series_type: Optional[Literal["bar", "line", "area", "scatter"]] = Field(
        default=None,
        description="For composed charts: individual series representation type"
    )
    y_axis_id: Optional[Literal["left", "right"]] = Field(
        default="left",
        description="For multi-variate composed charts: which vertical axis ('left' or 'right') to bind to"
    )
    stroke_dasharray: Optional[str] = Field(
        default=None,
        description="Optional dash array (e.g. '4 4') for reference or target series"
    )

class ScatterPoint(BaseModel):
    x: float = Field(description="X-coordinate value")
    y: float = Field(description="Y-coordinate value")
    label: Optional[str] = Field(default=None, description="Optional point label or timestamp")

class ScatterSeries(BaseModel):
    name: str = Field(description="Name of scatter series")
    points: List[ScatterPoint] = Field(description="List of (x, y) coordinate points")
    color: Optional[str] = Field(default=None, description="Point color")

class GaugeConfig(BaseModel):
    current_value: float = Field(description="Current value to show on gauge")
    min_value: float = Field(default=0.0, description="Minimum gauge value")
    max_value: float = Field(description="Maximum gauge value (e.g. 1475.0 kVA for contracted demand)")
    threshold_value: Optional[float] = Field(default=None, description="Warning/alarm threshold line (e.g. 1180.0 kVA)")
    unit: str = Field(default="kVA", description="Unit of the gauge (e.g. 'kVA', '%', 'PF')")
    status: Optional[str] = Field(default="NORMAL", description="Status indicator: 'NORMAL', 'WARNING', 'CRITICAL'")

class HeatmapMatrix(BaseModel):
    x_labels: List[str] = Field(description="X-axis category labels (e.g. hours '00:00' to '23:00')")
    y_labels: List[str] = Field(description="Y-axis category labels (e.g. days 'Mon', 'Tue', 'Wed' or dates)")
    z_matrix: List[List[float]] = Field(description="2D array of intensity values [rows][cols]")
    z_label: str = Field(default="kWh", description="Color bar scale label")

class ChartConfig(BaseModel):
    chart_type: ChartType = Field(
        description="Type of visualization selected as the best representation of user requirements"
    )
    title: str = Field(description="Descriptive, professional title of the graph")
    subtitle: Optional[str] = Field(default=None, description="Contextual subtitle with date, meter, or filter info")
    
    # Standard 1D/2D series
    x_axis_label: Optional[str] = Field(default=None, description="Label for X-axis (e.g. 'Hour of Day', 'Shift', 'Category')")
    x_labels: Optional[List[str]] = Field(default=None, description="Labels for X-axis categories/timestamps")
    y_axis_label: Optional[str] = Field(default=None, description="Label for primary Y-axis (e.g. 'kWh', 'kVA', '₹')")
    secondary_y_axis_label: Optional[str] = Field(default=None, description="Label for secondary Y-axis on composed multi-variate charts (e.g. 'Power Factor', 'kVA')")
    layout: Optional[Literal["horizontal", "vertical"]] = Field(default="horizontal", description="Orientation for bar charts ('horizontal' for side-by-side or 'vertical' for horizontal ranking bars)")
    series: Optional[List[ChartSeries]] = Field(default=None, description="Standard line/bar/area data series")
    
    # Reference and limit lines
    threshold_line: Optional[float] = Field(
        default=None, 
        description="Warning threshold line (e.g. 1180 kVA for peak demand, 5% for THD, 0.90 for PF)"
    )
    threshold_label: Optional[str] = Field(default=None, description="Label for threshold line (e.g. '80% Demand Limit (1180 kVA)')")
    
    # Specialized chart payloads
    scatter_series: Optional[List[ScatterSeries]] = Field(default=None, description="Payload for scatter and pair plots")
    gauge_data: Optional[GaugeConfig] = Field(default=None, description="Payload for gauge / radial charts")
    heatmap_data: Optional[HeatmapMatrix] = Field(default=None, description="Payload for 2D hourly/weekly heatmaps")
    treemap_data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Payload for hierarchical Treemap visual allocation")
    radar_data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Payload for multi-axial Radar / Spider comparisons")
    radial_bar_data: Optional[List[Dict[str, Any]]] = Field(default=None, description="Payload for concentric RadialBar gauge displays")
    
    # Donut center KPI metric
    center_kpi: Optional[Dict[str, Any]] = Field(
        default=None, 
        description="Center KPI text for donut charts (e.g. {'label': 'Total Consumption', 'value': '58,293.9 kWh'})"
    )
    
    # Rationalization for selection
    representation_reason: Optional[str] = Field(
        default=None,
        description="Why this chart type was selected as the best representation for the user's requirement"
    )
