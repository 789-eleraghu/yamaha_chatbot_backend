"""
Tools Package

Consolidated tool registry for Yamaha EMS Chatbot:
- 7 Energy Tools (from energy_tools.py) - Unified 7-tool architecture
- 3 Chart Tools (from chart_tools.py)
- 1 Intelligent Visualization Tool (from visualization_tool.py) — PRIMARY for charts
- 6 Utility Tools (from util_tools.py)

Total: 14 tools (EMS + Visualization + Utilities)
"""

from src.tools.energy_tools import ALL_EMS_TOOLS
from src.tools.chart_tools import ALL_CHART_TOOLS
from src.tools.visualization_tool import ALL_VISUALIZATION_TOOLS
from src.tools.util_tools import ALL_UTIL_TOOLS

# Unified tool registry
# IMPORTANT: create_visualization MUST come FIRST for charts - it auto-selects best chart type
# The legacy chart tools (create_chart, create_power_quality_chart, create_specialized_chart)
# are kept for backward compatibility but create_visualization should be preferred.
ALL_TOOLS = ALL_EMS_TOOLS + ALL_VISUALIZATION_TOOLS + ALL_UTIL_TOOLS
# Note: ALL_CHART_TOOLS removed from primary registry to prevent tool confusion
# If needed, they can be added back: ALL_TOOLS = ALL_EMS_TOOLS + ALL_VISUALIZATION_TOOLS + ALL_CHART_TOOLS + ALL_UTIL_TOOLS

__all__ = [
    "ALL_EMS_TOOLS",
    "ALL_CHART_TOOLS",
    "ALL_VISUALIZATION_TOOLS",
    "ALL_UTIL_TOOLS",
    "ALL_TOOLS",
]
