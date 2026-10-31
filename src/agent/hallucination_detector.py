"""
Hallucination Detector
Detects when the model generates numeric energy data without calling tools.
Returns an error instead of hallucinated data.
"""

import re
from typing import List, Dict, Any, Tuple

# Patterns that indicate energy-related numeric data
ENERGY_PATTERNS = [
    r'\b\d+(?:,\d{3})*(?:\.\d+)?\s*kWh\b',      # 1,234.5 kWh
    r'\b\d+(?:,\d{3})*(?:\.\d+)?\s*kVA\b',      # 1,234.5 kVA
    r'\b\d+(?:,\d{3})*(?:\.\d+)?\s*kW\b',       # 1,234.5 kW
    r'\b\d+(?:,\d{3})*(?:\.\d+)?\s*kVAR\b',     # 1,234.5 kVAR
    r'\b\d+(?:,\d{3})*(?:\.\d+)?\s*MW\b',       # 1,234.5 MW
    r'\b\d+(?:,\d{3})*(?:\.\d+)?\s*MWh\b',      # 1,234.5 MWh
    r'₹\s*\d+(?:,\d{3})*(?:\.\d+)?',            # ₹1,234.50
    r'\bINR\s*\d+(?:,\d{3})*(?:\.\d+)?',        # INR 1,234.50
    r'\b\d+(?:\.\d+)?%\s*(?:utilization|efficiency|THD|power factor)', # 85.5% utilization
    r'\b(?:power\s*factor|pf)\s*(?:is|was|of|:|\b)?\s*0\.\d{2,4}\b',  # power factor: 0.92
    r'\b0\.\d{2,4}\s*(?:power\s*factor|pf)\b',                          # 0.92 power factor
    r'\b(?:avg|average|min|max)\s*(?:power\s*factor|pf)\b[^\d\n]{0,20}\b0\.\d{2,4}\b',
]

# Patterns that indicate the response is about energy queries
ENERGY_QUERY_INDICATORS = [
    r'\b(?:solar|consumption|generation|energy|power|demand|tariff|shift|equipment)\b',
    r'\b(?:yesterday|today|last\s+week|last\s+month|daily|hourly|monthly)\b',
    r'\b(?:facility|grid|DG|diesel\s+generator|rooftop)\b',
    r'\b(?:power\s*factor|pf|thd|harmonics|reactive|kvarh|steam)\b',
]

# Patterns to exclude (these are OK without tool calls)
EXCLUDE_PATTERNS = [
    r'contracted\s+demand.*1475\s*kVA',  # Static info
    r'threshold.*1180\s*kVA',             # Static info
    r'100\s*kW\s*rooftop\s*solar',        # Static capacity
    r'300\s*kVA\s*(?:DG|generator)',      # Static capacity
    r'maximum.*365\s*days',               # Error messages
    r'IEEE\s*519',                         # Standards
]


def contains_energy_numbers(text: str) -> Tuple[bool, List[str]]:
    """
    Check if text contains energy-related numeric values.
    Returns (has_numbers, list of matched patterns)
    """
    if not text:
        return False, []

    # Check for exclusions first
    text_lower = text.lower()
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            # Remove the excluded portion and continue checking
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    matches = []
    for pattern in ENERGY_PATTERNS:
        found = re.findall(pattern, text, re.IGNORECASE)
        if found:
            matches.extend(found)

    return len(matches) > 0, matches


def is_energy_query(text: str) -> bool:
    """Check if the query/response is about energy data."""
    if not text:
        return False

    text_lower = text.lower()
    for pattern in ENERGY_QUERY_INDICATORS:
        if re.search(pattern, text_lower):
            return True

    # Also check for plant equipment and zone keywords
    plant_keywords = [
        "compressor", "molding", "lighting", "airconditioning", "paintshop",
        "dust_collector", "production_power", "incomer", "transformer", "boiler"
    ]
    return any(k in text_lower for k in plant_keywords)


def detect_hallucination(
    response_text: str,
    tool_calls_this_turn: List[Dict[str, Any]],
    user_query: str = ""
) -> Tuple[bool, str]:
    """
    Detect if response contains hallucinated energy data.

    Args:
        response_text: The assistant's response text
        tool_calls_this_turn: List of tools called in THIS turn (not history)
        user_query: The user's query for this turn

    Returns:
        (is_hallucination, error_message)
    """
    # If tools were called this turn, the data is legitimate
    if tool_calls_this_turn:
        # Check if any energy-related tool was called
        energy_tools = {
            'get_cummulative_energy', 'get_instantaneous_energy', 'grouping_energy',
            'create_visualization', 'aggregate_energy_telemetry', 'diagnose_consumption',
            'search_knowledge_base', 'execute_custom_sql',
        }

        called_tool_names = {tc.get('name', '') for tc in tool_calls_this_turn}
        if called_tool_names & energy_tools:
            return False, ""

    # Check if response contains numeric energy data
    has_numbers, matches = contains_energy_numbers(response_text)

    if has_numbers:
        # If response has verified energy units or metrics without tool calls, flag as hallucination
        if (
            is_energy_query(user_query)
            or is_energy_query(response_text)
            or any('kwh' in m.lower() or 'kva' in m.lower() or 'kw' in m.lower() or 'factor' in m.lower() or 'pf' in m.lower() for m in matches)
        ):
            error_msg = (
                "⚠️ I need to fetch the actual data from the database. "
                "Let me query the telemetry system for accurate figures."
            )
            return True, error_msg

    return False, ""


def get_hallucination_error_response() -> str:
    """Get a standard error response when hallucination is detected."""
    return (
        "I apologize, but I need to retrieve the actual data from our telemetry system "
        "to provide accurate figures. Please let me make the appropriate tool call to "
        "fetch the current information."
    )
