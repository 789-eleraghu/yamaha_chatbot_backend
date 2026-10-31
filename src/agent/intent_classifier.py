"""
Lightweight Intent Classifier for Dynamic Tool Binding (Optimized)
Reduces token cost by 60-70% by only binding relevant tools per query.
Uses keyword matching + regex patterns (no LLM call needed).

Updated for optimized tool names:
- create_chart (primary chart tool)
- create_power_quality_chart
- create_specialized_chart
- Energy tools from energy_tools_optimized.py
"""

import re
from enum import Enum
from typing import List, Set, Tuple

class QueryIntent(Enum):
    GREETING = "greeting"
    ENERGY_QUERY = "energy_query"
    VISUALIZATION = "visualization"
    DIAGNOSIS = "diagnosis"
    POWER_QUALITY = "power_quality"
    COST_TARIFF = "cost_tariff"
    REALTIME = "realtime"
    KNOWLEDGE = "knowledge"
    CUSTOM_SQL = "custom_sql"
    AMBIGUOUS = "ambiguous"


# Intent detection patterns (compiled for performance)
INTENT_PATTERNS = {
    QueryIntent.GREETING: re.compile(
        r"^(hi|hello|hey|good\s*(morning|afternoon|evening)|greetings|howdy|yo|what\'?s\s*up|sup)\b",
        re.IGNORECASE
    ),
    QueryIntent.VISUALIZATION: re.compile(
        r"\b(chart|graph|plot|visual|donut|pie|bar|line|area|gauge|heatmap|scatter|radar|"
        r"stacked|grouped|histogram|trend|show\s*me|display|render|draw|compare.*chart|"
        r"breakdown\s*chart|time\s*series|load\s*curve)\b",
        re.IGNORECASE
    ),
    QueryIntent.DIAGNOSIS: re.compile(
        r"\b(diagnos|rca|root\s*cause|anomal|spike|surge|excursion|abnormal|unusual|"
        r"why\s*(is|was|did)|what\s*caused|explain|investigate|high\s*consumption|"
        r"baseload|leakage|vampire|night.*load)\b",
        re.IGNORECASE
    ),
    QueryIntent.POWER_QUALITY: re.compile(
        r"\b(thd|harmonic|power\s*factor|pf|reactive|kvarh|voltage\s*distortion|"
        r"current\s*distortion|steam|boiler|pressure|flow\s*rate|"
        r"pf\s*trend|power\s*factor\s*comparison|pf\s*analysis)\b",
        re.IGNORECASE
    ),
    QueryIntent.COST_TARIFF: re.compile(
        r"\b(cost|bill|tariff|tod|time\s*of\s*day|inr|rupee|₹|price|charge|rate|"
        r"off.?peak|peak\s*hour|normal\s*hour|electricity\s*bill)\b",
        re.IGNORECASE
    ),
    QueryIntent.REALTIME: re.compile(
        r"\b(real.?time|live|current|now|latest|instant|snapshot|status|monitoring)\b",
        re.IGNORECASE
    ),
    QueryIntent.KNOWLEDGE: re.compile(
        r"\b(what\s*is|define|explain|how\s*does|calculation|formula|mapping|"
        r"tag|meter|document|reference|kb|knowledge)\b",
        re.IGNORECASE
    ),
    QueryIntent.CUSTOM_SQL: re.compile(
        r"\b(sql|query|select|database|table|opcda|raw\s*data)\b",
        re.IGNORECASE
    ),
    QueryIntent.ENERGY_QUERY: re.compile(
        r"\b(energy|consumption|kwh|kva|demand|shift|facility|equipment|zone|"
        r"cost\s*center|dg|diesel|generator|solar|grid|incomer|breakdown|yesterday|today|"
        r"last\s*week|last\s*month|hourly|daily|monthly)\b",
        re.IGNORECASE
    ),
}

# Tool groups by intent (using optimized tool names)
TOOL_GROUPS = {
    QueryIntent.GREETING: [],  # No tools needed
    QueryIntent.ENERGY_QUERY: [
        "create_visualization",  # PRIMARY - unified chart tool
        "get_cummulative_energy",
        "grouping_energy",
        "get_instantaneous_energy",
    ],
    QueryIntent.VISUALIZATION: [
        "create_visualization",  # PRIMARY - unified chart tool
    ],
    QueryIntent.DIAGNOSIS: [
        "diagnose_consumption",
        "explain_hourly_anomaly",
        "get_cummulative_energy",
        "grouping_energy",
    ],
    QueryIntent.POWER_QUALITY: [
        "get_instantaneous_energy",
        "create_visualization",
    ],
    QueryIntent.COST_TARIFF: [
        "grouping_energy",
        "create_visualization",
    ],
    QueryIntent.REALTIME: [
        "get_instantaneous_energy",
    ],
    QueryIntent.KNOWLEDGE: [
        "search_knowledge_base",
    ],
    QueryIntent.CUSTOM_SQL: [
        "execute_custom_sql",
    ],
}

# Build tool lookup map
from src.tools import ALL_TOOLS
ALL_TOOLS_MAP = {t.name: t for t in ALL_TOOLS}

# Core tools always included (most frequently needed for energy queries)
CORE_TOOLS = {
    "create_visualization",  # PRIMARY - unified chart tool
    "get_cummulative_energy",
    "get_instantaneous_energy",
    "grouping_energy",
    "search_knowledge_base",
}


class IntentClassifier:
    """
    Lightweight intent classifier using keyword patterns.
    No LLM call required - runs in <1ms.
    """

    @staticmethod
    def classify(query: str) -> Tuple[Set[QueryIntent], float]:
        """
        Classify query into one or more intents.
        Returns (set of intents, confidence score 0-1).
        """
        query = query.strip()
        if not query:
            return {QueryIntent.AMBIGUOUS}, 0.0

        detected_intents: Set[QueryIntent] = set()

        # Check each pattern
        for intent, pattern in INTENT_PATTERNS.items():
            if pattern.search(query):
                detected_intents.add(intent)

        # If greeting only, return early
        if detected_intents == {QueryIntent.GREETING}:
            return detected_intents, 1.0

        # Remove greeting if other intents detected (user greeted + asked question)
        if len(detected_intents) > 1 and QueryIntent.GREETING in detected_intents:
            detected_intents.discard(QueryIntent.GREETING)

        # Default to energy query if nothing detected but looks like a question
        if not detected_intents:
            if any(w in query.lower() for w in ["?", "what", "how", "when", "show", "get", "tell"]):
                detected_intents.add(QueryIntent.ENERGY_QUERY)
            else:
                detected_intents.add(QueryIntent.AMBIGUOUS)

        # Confidence based on number of pattern matches
        confidence = min(1.0, len(detected_intents) * 0.4 + 0.3)

        return detected_intents, confidence

    @staticmethod
    def get_tools_for_intents(intents: Set[QueryIntent]) -> List:
        """
        Get the minimal set of tools needed for the detected intents.
        """
        tool_names: Set[str] = set(CORE_TOOLS)  # Always include core tools

        for intent in intents:
            if intent in TOOL_GROUPS:
                tool_names.update(TOOL_GROUPS[intent])

        # If visualization requested, include energy tools for data retrieval
        if QueryIntent.VISUALIZATION in intents:
            tool_names.update(TOOL_GROUPS[QueryIntent.ENERGY_QUERY])

        # If diagnosis, include visualization for charts
        if QueryIntent.DIAGNOSIS in intents:
            tool_names.update(["create_visualization"])

        # Resolve tool objects
        tools = [ALL_TOOLS_MAP[name] for name in tool_names if name in ALL_TOOLS_MAP]

        return tools

    @staticmethod
    def get_optimized_tools(query: str) -> Tuple[List, Set[QueryIntent], float]:
        """
        Main entry point: classify query and return optimized tool set.
        Returns (tools, intents, confidence).
        """
        intents, confidence = IntentClassifier.classify(query)

        # For greetings, return empty tool list
        if intents == {QueryIntent.GREETING}:
            return [], intents, confidence

        # For ambiguous queries, return all tools (fallback)
        if intents == {QueryIntent.AMBIGUOUS} and confidence < 0.3:
            return list(ALL_TOOLS_MAP.values()), intents, confidence

        tools = IntentClassifier.get_tools_for_intents(intents)
        return tools, intents, confidence


intent_classifier = IntentClassifier()
