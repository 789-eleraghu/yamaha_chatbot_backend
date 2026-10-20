"""
System Instructions and Industrial Constraints for Yamaha Energy Assistant
Loads docs/LLM_SYSTEM_CONSTITUTION.md (High density, ~1,870 tokens)
"""

import os
from pathlib import Path

CONSTITUTION_FILE = Path(__file__).resolve().parent.parent.parent / "docs" / "LLM_SYSTEM_CONSTITUTION.md"

def get_system_prompt() -> str:
    constitution_text = ""
    if CONSTITUTION_FILE.exists():
        with open(CONSTITUTION_FILE, "r", encoding="utf-8") as f:
            constitution_text = f.read()

    base_persona = (
        "You are the Yamaha Energy AI Assistant, an expert industrial energy engineer "
        "querying, analyzing, and diagnosing Yamaha EMS (Energy Management System) data.\n\n"
    )

    graphing_rules = (
        "\n### GRAPHING & STRUCTURED OUTPUT INSTRUCTIONS:\n"
        "Whenever a user query asks for or would benefit from visual analysis (hourly profiles, "
        "shift comparisons, multi-day trends, cost breakdowns, or peak excursions), populate a "
        "clean 'chart' configuration in your structured output with chart_type ('line', 'bar', 'area', 'donut'), "
        "x_labels, series data, and threshold lines (e.g. 1180 kVA for peak demand, 5% for THD).\n"
    )

    if constitution_text:
        return f"{base_persona}\n{constitution_text}\n{graphing_rules}"

    # Fallback minimal prompt
    return f"{base_persona}\nStrict IST timezone. Never sum power. Missing data returns null.\n{graphing_rules}"

SYSTEM_PROMPT = get_system_prompt()
