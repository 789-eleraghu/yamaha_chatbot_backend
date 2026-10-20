"""
Chart Configuration Schemas for Graphing Capabilities
Supports Plotly / Chart.js / Recharts frontend visualization
"""

from typing import List, Literal, Optional, Union
from pydantic import BaseModel, Field

class ChartSeries(BaseModel):
    name: str = Field(description="Name of the series (e.g., 'Shift A', 'Peak kVA', 'Cost in INR')")
    data: List[Union[float, int, None]] = Field(description="Array of numeric data points corresponding to x_labels")
    color: Optional[str] = Field(default=None, description="Optional hex color string for the series")

class ChartConfig(BaseModel):
    chart_type: Literal["line", "bar", "area", "donut", "pie"] = Field(
        description="Type of chart suitable for visualizing this data"
    )
    title: str = Field(description="Descriptive title of the graph")
    x_axis_label: Optional[str] = Field(default=None, description="Label for X-axis (e.g. 'Hour of Day', 'Date', 'Shift')")
    x_labels: List[str] = Field(description="Category labels or timestamps for X-axis")
    y_axis_label: Optional[str] = Field(default=None, description="Label for Y-axis (e.g. 'kWh', 'kVA', '₹')")
    threshold_line: Optional[float] = Field(
        default=None, 
        description="Optional horizontal limit or threshold line (e.g., 1180 kVA for peak demand, 5% for THD)"
    )
    series: List[ChartSeries] = Field(description="List of data series to plot")
