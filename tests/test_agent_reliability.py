"""
🔬 AGENT RELIABILITY TEST SUITE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tests the LLM agent's ability to:
1. Select the CORRECT tool for each query
2. Extract parameters ACCURATELY from natural language
3. Avoid tool CONFUSION (calling wrong tool)
4. Handle AMBIGUOUS queries appropriately
5. Call MULTIPLE tools when needed

Run: pytest tests/test_agent_reliability.py -v -s
"""

import pytest
import json
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from unittest.mock import patch, MagicMock
from datetime import datetime

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import BaseTool


# ============================================================================
# TEST CASE DEFINITIONS
# ============================================================================

@dataclass
class ToolCallExpectation:
    """Expected tool call for a query."""
    tool_name: str
    required_params: Dict[str, Any] = field(default_factory=dict)
    optional_params: List[str] = field(default_factory=list)
    param_constraints: Dict[str, callable] = field(default_factory=dict)  # Validation functions


@dataclass
class AgentTestCase:
    """Single test case for agent reliability."""
    id: str
    query: str
    expected_tools: List[ToolCallExpectation]
    category: str  # "single_tool", "multi_tool", "ambiguous", "edge_case"
    description: str = ""
    should_ask_clarification: bool = False
    forbidden_tools: List[str] = field(default_factory=list)


# ============================================================================
# TEST CASES - SINGLE TOOL SELECTION
# ============================================================================

SINGLE_TOOL_TESTS: List[AgentTestCase] = [
    # Facility Energy
    AgentTestCase(
        id="ST-001",
        query="What was yesterday's total energy consumption?",
        expected_tools=[ToolCallExpectation(
            tool_name="get_facility_energy",
            required_params={"date": "yesterday"},
        )],
        category="single_tool",
        description="Basic facility energy query",
    ),
    AgentTestCase(
        id="ST-002",
        query="Show me energy consumption for 2026-10-20",
        expected_tools=[ToolCallExpectation(
            tool_name="get_facility_energy",
            required_params={"date": "2026-10-20"},
        )],
        category="single_tool",
        description="Facility energy with specific date",
    ),

    # Solar
    AgentTestCase(
        id="ST-003",
        query="How much solar power did we generate yesterday?",
        expected_tools=[ToolCallExpectation(
            tool_name="get_facility_solar",
        )],
        category="single_tool",
        description="Solar generation query",
        forbidden_tools=["get_facility_energy"],  # Should not confuse with grid energy
    ),

    # Power Quality
    AgentTestCase(
        id="ST-004",
        query="What is the power factor today?",
        expected_tools=[ToolCallExpectation(
            tool_name="get_facility_power_quality",
            required_params={"metric": "power_factor"},
        )],
        category="single_tool",
        description="Power factor query",
    ),
    AgentTestCase(
        id="ST-005",
        query="Show me the THD levels",
        expected_tools=[ToolCallExpectation(
            tool_name="get_facility_power_quality",
            # Should pick either voltage_thd or current_thd
        )],
        category="single_tool",
        description="THD query",
    ),

    # Equipment Energy
    AgentTestCase(
        id="ST-006",
        query="How much energy did the compressors use yesterday?",
        expected_tools=[ToolCallExpectation(
            tool_name="get_equipment_energy",
            required_params={"category": "Compressor"},
        )],
        category="single_tool",
        description="Specific equipment category query",
    ),
    AgentTestCase(
        id="ST-007",
        query="Show molding machine consumption for last week",
        expected_tools=[ToolCallExpectation(
            tool_name="get_equipment_energy",
            required_params={"category": "Molding"},
        )],
        category="single_tool",
        description="Equipment with date range",
    ),

    # Zone Energy
    AgentTestCase(
        id="ST-008",
        query="What is the energy consumption for AG Assy zone?",
        expected_tools=[ToolCallExpectation(
            tool_name="get_zone_energy",
            required_params={"zone": "AG Assy"},
        )],
        category="single_tool",
        description="Specific zone query",
    ),

    # Tariff Cost
    AgentTestCase(
        id="ST-009",
        query="What was yesterday's electricity cost?",
        expected_tools=[ToolCallExpectation(
            tool_name="get_tariff_cost",
        )],
        category="single_tool",
        description="Cost/tariff query",
        forbidden_tools=["get_facility_energy"],  # Should use tariff tool, not energy
    ),

    # Generator
    AgentTestCase(
        id="ST-010",
        query="How long did the DG run yesterday?",
        expected_tools=[ToolCallExpectation(
            tool_name="get_generator_metrics",
        )],
        category="single_tool",
        description="Generator/DG query",
    ),

    # Real-time
    AgentTestCase(
        id="ST-011",
        query="What is the current load on South Utilities transformer?",
        expected_tools=[ToolCallExpectation(
            tool_name="get_realtime_telemetry",
        )],
        category="single_tool",
        description="Real-time/current reading query",
    ),

    # Diagnostics
    AgentTestCase(
        id="ST-012",
        query="Why was energy consumption high yesterday?",
        expected_tools=[ToolCallExpectation(
            tool_name="diagnose_consumption",
        )],
        category="single_tool",
        description="Root cause/why query",
    ),
    AgentTestCase(
        id="ST-013",
        query="Explain the spike at 2pm yesterday",
        expected_tools=[ToolCallExpectation(
            tool_name="explain_hourly_anomaly",
        )],
        category="single_tool",
        description="Hourly anomaly explanation",
    ),
]


# ============================================================================
# TEST CASES - VISUALIZATION TOOL SELECTION
# ============================================================================

VISUALIZATION_TESTS: List[AgentTestCase] = [
    AgentTestCase(
        id="VZ-001",
        query="Show me equipment breakdown chart",
        expected_tools=[ToolCallExpectation(
            tool_name="create_visualization",
            required_params={"intent": lambda x: "equipment" in x.lower()},
        )],
        category="visualization",
        description="Equipment chart request",
    ),
    AgentTestCase(
        id="VZ-002",
        query="I want to see zone comparison as a bar chart",
        expected_tools=[ToolCallExpectation(
            tool_name="create_visualization",
            required_params={"intent": lambda x: "zone" in x.lower()},
        )],
        category="visualization",
        description="Zone chart with type specification",
    ),
    AgentTestCase(
        id="VZ-003",
        query="Show hourly load profile",
        expected_tools=[ToolCallExpectation(
            tool_name="create_visualization",
            required_params={
                "intent": lambda x: "hourly" in x.lower() or "load" in x.lower(),
                "granularity": "hourly",
            },
        )],
        category="visualization",
        description="Hourly profile chart",
    ),
    AgentTestCase(
        id="VZ-004",
        query="Give me a peak demand gauge",
        expected_tools=[ToolCallExpectation(
            tool_name="create_visualization",
            required_params={"intent": lambda x: "gauge" in x.lower() or "demand" in x.lower()},
        )],
        category="visualization",
        description="Gauge visualization",
    ),
    AgentTestCase(
        id="VZ-005",
        query="Visualize this as pie chart",
        expected_tools=[ToolCallExpectation(
            tool_name="create_visualization",
        )],
        category="visualization",
        description="Follow-up chart type change",
    ),
]


# ============================================================================
# TEST CASES - TOOL CONFUSION SCENARIOS
# ============================================================================

TOOL_CONFUSION_TESTS: List[AgentTestCase] = [
    AgentTestCase(
        id="TC-001",
        query="What is the power consumption?",
        expected_tools=[ToolCallExpectation(tool_name="get_facility_energy")],
        category="confusion",
        description="Power vs Energy confusion - should use energy",
        forbidden_tools=["get_facility_power_quality"],  # Power quality is different!
    ),
    AgentTestCase(
        id="TC-002",
        query="Show me the energy chart",
        expected_tools=[ToolCallExpectation(tool_name="create_visualization")],
        category="confusion",
        description="Chart request - should use visualization, not energy tool",
        forbidden_tools=["get_facility_energy", "get_equipment_energy"],
    ),
    AgentTestCase(
        id="TC-003",
        query="What is the cost center wise consumption?",
        expected_tools=[ToolCallExpectation(tool_name="get_zone_energy")],
        category="confusion",
        description="Cost center = Zone, not tariff cost",
        forbidden_tools=["get_tariff_cost"],
    ),
    AgentTestCase(
        id="TC-004",
        query="Show shift A, B, C breakdown",
        expected_tools=[ToolCallExpectation(
            tool_name="create_visualization",
            required_params={"intent": lambda x: "shift" in x.lower()},
        )],
        category="confusion",
        description="Shift breakdown - needs visualization with shift granularity",
    ),
    AgentTestCase(
        id="TC-005",
        query="What is the PF?",
        expected_tools=[ToolCallExpectation(
            tool_name="get_facility_power_quality",
            required_params={"metric": "power_factor"},
        )],
        category="confusion",
        description="PF abbreviation should map to power_factor metric",
    ),
]


# ============================================================================
# TEST CASES - MULTI-TOOL SCENARIOS
# ============================================================================

MULTI_TOOL_TESTS: List[AgentTestCase] = [
    AgentTestCase(
        id="MT-001",
        query="Compare yesterday's consumption with the cost",
        expected_tools=[
            ToolCallExpectation(tool_name="get_facility_energy"),
            ToolCallExpectation(tool_name="get_tariff_cost"),
        ],
        category="multi_tool",
        description="Needs both energy and cost data",
    ),
    AgentTestCase(
        id="MT-002",
        query="Show equipment breakdown and also the solar generation",
        expected_tools=[
            ToolCallExpectation(tool_name="get_equipment_energy"),
            ToolCallExpectation(tool_name="get_facility_solar"),
        ],
        category="multi_tool",
        description="Two different data sources requested",
    ),
]


# ============================================================================
# TEST CASES - AMBIGUOUS QUERIES (should clarify)
# ============================================================================

AMBIGUOUS_TESTS: List[AgentTestCase] = [
    AgentTestCase(
        id="AM-001",
        query="Show consumption",
        expected_tools=[],  # Should ask for clarification
        category="ambiguous",
        description="Missing date - should clarify",
        should_ask_clarification=True,
    ),
    AgentTestCase(
        id="AM-002",
        query="What is the energy?",
        expected_tools=[],
        category="ambiguous",
        description="Too vague - should clarify date/scope",
        should_ask_clarification=True,
    ),
]


# ============================================================================
# TEST CASES - PARAMETER EXTRACTION
# ============================================================================

PARAMETER_TESTS: List[AgentTestCase] = [
    AgentTestCase(
        id="PM-001",
        query="Show compressor energy for October 15th to 20th",
        expected_tools=[ToolCallExpectation(
            tool_name="get_equipment_energy",
            required_params={
                "category": "Compressor",
                "start_date": lambda x: "10-15" in x or "10/15" in x,
                "end_date": lambda x: "10-20" in x or "10/20" in x,
            },
        )],
        category="parameter",
        description="Date range extraction",
    ),
    AgentTestCase(
        id="PM-002",
        query="Yesterday's hourly consumption for molding",
        expected_tools=[ToolCallExpectation(
            tool_name="get_equipment_energy",
            required_params={
                "category": "Molding",
                "date": "yesterday",
                "granularity": "hourly",
            },
        )],
        category="parameter",
        description="Granularity extraction",
    ),
    AgentTestCase(
        id="PM-003",
        query="AG Painting zone energy last 3 days",
        expected_tools=[ToolCallExpectation(
            tool_name="get_zone_energy",
            required_params={
                "zone": lambda x: "AG Painting" in x or "ag painting" in x.lower(),
            },
        )],
        category="parameter",
        description="Zone name extraction with typo tolerance",
    ),
]


# ============================================================================
# TOOL CALL INTERCEPTOR
# ============================================================================

class ToolCallInterceptor:
    """Intercepts and records tool calls made by the agent."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []
        self.call_sequence: List[str] = []

    def record_call(self, tool_name: str, args: Dict[str, Any]):
        """Record a tool call."""
        self.calls.append({
            "tool": tool_name,
            "args": args,
            "timestamp": datetime.now().isoformat(),
        })
        self.call_sequence.append(tool_name)

    def get_calls_for_tool(self, tool_name: str) -> List[Dict[str, Any]]:
        """Get all calls for a specific tool."""
        return [c for c in self.calls if c["tool"] == tool_name]

    def was_tool_called(self, tool_name: str) -> bool:
        """Check if a tool was called."""
        return tool_name in self.call_sequence

    def get_tool_args(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Get arguments for first call of a tool."""
        calls = self.get_calls_for_tool(tool_name)
        return calls[0]["args"] if calls else None

    def clear(self):
        """Clear recorded calls."""
        self.calls = []
        self.call_sequence = []


# ============================================================================
# AGENT TEST HARNESS
# ============================================================================

class AgentTestHarness:
    """Test harness for agent reliability testing."""

    def __init__(self):
        self.interceptor = ToolCallInterceptor()
        self._setup_mocks()

    def _setup_mocks(self):
        """Setup tool mocks to intercept calls."""
        from src.tools import ALL_TOOLS
        self.original_tools = {t.name: t for t in ALL_TOOLS}
        self.mock_tools = {}

        for tool in ALL_TOOLS:
            mock = MagicMock()
            mock.name = tool.name
            mock.description = tool.description
            mock.args_schema = getattr(tool, 'args_schema', None)

            def make_invoke(tool_name):
                def invoke(args):
                    self.interceptor.record_call(tool_name, args)
                    return {"status": "mocked", "tool": tool_name}
                return invoke

            mock.invoke = make_invoke(tool.name)
            self.mock_tools[tool.name] = mock

    async def run_query(self, query: str) -> Dict[str, Any]:
        """Run a query through the agent and capture tool calls."""
        self.interceptor.clear()

        from src.agent.graph import get_agent_graph
        from src.agent.state import AgentState

        # Create initial state
        initial_state = AgentState(
            messages=[HumanMessage(content=query)],
            tool_executions=[],
            response_text="",
        )

        graph = get_agent_graph()

        # Run with tool interception
        tool_calls_made = []

        async for event in graph.astream_events(initial_state, version="v2"):
            if event["event"] == "on_tool_start":
                tool_name = event["name"]
                tool_input = event.get("data", {}).get("input", {})
                self.interceptor.record_call(tool_name, tool_input)
                tool_calls_made.append({
                    "tool": tool_name,
                    "input": tool_input,
                })

        return {
            "query": query,
            "tool_calls": tool_calls_made,
            "call_sequence": self.interceptor.call_sequence,
        }

    def analyze_result(
        self,
        result: Dict[str, Any],
        expected: AgentTestCase
    ) -> Dict[str, Any]:
        """Analyze test result against expectations."""

        analysis = {
            "test_id": expected.id,
            "query": expected.query,
            "passed": True,
            "issues": [],
            "tool_calls": result["tool_calls"],
        }

        # Check forbidden tools
        for forbidden in expected.forbidden_tools:
            if self.interceptor.was_tool_called(forbidden):
                analysis["passed"] = False
                analysis["issues"].append(f"FORBIDDEN tool called: {forbidden}")

        # Check expected tools were called
        for exp_tool in expected.expected_tools:
            if not self.interceptor.was_tool_called(exp_tool.tool_name):
                analysis["passed"] = False
                analysis["issues"].append(f"MISSING expected tool: {exp_tool.tool_name}")
                continue

            # Check parameters
            actual_args = self.interceptor.get_tool_args(exp_tool.tool_name)
            if actual_args:
                for param, expected_val in exp_tool.required_params.items():
                    if param not in actual_args:
                        analysis["passed"] = False
                        analysis["issues"].append(f"MISSING param '{param}' in {exp_tool.tool_name}")
                    elif callable(expected_val):
                        # Validation function
                        if not expected_val(actual_args[param]):
                            analysis["passed"] = False
                            analysis["issues"].append(
                                f"INVALID param '{param}'={actual_args[param]} in {exp_tool.tool_name}"
                            )
                    elif actual_args[param] != expected_val:
                        analysis["passed"] = False
                        analysis["issues"].append(
                            f"WRONG param '{param}': expected={expected_val}, got={actual_args[param]}"
                        )

        return analysis


# ============================================================================
# PYTEST TEST CLASSES
# ============================================================================

class TestSingleToolSelection:
    """Test single tool selection accuracy."""

    @pytest.fixture
    def harness(self):
        return AgentTestHarness()

    @pytest.mark.parametrize("test_case", SINGLE_TOOL_TESTS, ids=lambda c: c.id)
    @pytest.mark.asyncio
    async def test_single_tool(self, harness, test_case):
        result = await harness.run_query(test_case.query)
        analysis = harness.analyze_result(result, test_case)

        if not analysis["passed"]:
            print(f"\n❌ FAILED: {test_case.id}")
            print(f"   Query: {test_case.query}")
            print(f"   Issues: {analysis['issues']}")
            print(f"   Actual calls: {result['tool_calls']}")

        assert analysis["passed"], f"Issues: {analysis['issues']}"


class TestVisualizationSelection:
    """Test visualization tool selection."""

    @pytest.fixture
    def harness(self):
        return AgentTestHarness()

    @pytest.mark.parametrize("test_case", VISUALIZATION_TESTS, ids=lambda c: c.id)
    @pytest.mark.asyncio
    async def test_visualization(self, harness, test_case):
        result = await harness.run_query(test_case.query)
        analysis = harness.analyze_result(result, test_case)

        assert analysis["passed"], f"Issues: {analysis['issues']}"


class TestToolConfusion:
    """Test that agent doesn't confuse similar tools."""

    @pytest.fixture
    def harness(self):
        return AgentTestHarness()

    @pytest.mark.parametrize("test_case", TOOL_CONFUSION_TESTS, ids=lambda c: c.id)
    @pytest.mark.asyncio
    async def test_no_confusion(self, harness, test_case):
        result = await harness.run_query(test_case.query)
        analysis = harness.analyze_result(result, test_case)

        # Extra check for forbidden tools
        for forbidden in test_case.forbidden_tools:
            assert forbidden not in result["call_sequence"], \
                f"TOOL CONFUSION: Called {forbidden} instead of {test_case.expected_tools[0].tool_name}"

        assert analysis["passed"], f"Issues: {analysis['issues']}"


# ============================================================================
# COMPREHENSIVE REPORT GENERATOR
# ============================================================================

async def generate_reliability_report():
    """Run all tests and generate comprehensive reliability report."""

    harness = AgentTestHarness()
    all_tests = (
        SINGLE_TOOL_TESTS +
        VISUALIZATION_TESTS +
        TOOL_CONFUSION_TESTS +
        PARAMETER_TESTS
    )

    results = {
        "total": len(all_tests),
        "passed": 0,
        "failed": 0,
        "by_category": {},
        "failures": [],
        "tool_usage": {},
    }

    print("\n" + "=" * 70)
    print("🔬 AGENT RELIABILITY TEST REPORT")
    print("=" * 70)

    for test in all_tests:
        try:
            result = await harness.run_query(test.query)
            analysis = harness.analyze_result(result, test)

            # Track tool usage
            for call in result["tool_calls"]:
                tool = call["tool"]
                if tool not in results["tool_usage"]:
                    results["tool_usage"][tool] = 0
                results["tool_usage"][tool] += 1

            # Track by category
            cat = test.category
            if cat not in results["by_category"]:
                results["by_category"][cat] = {"passed": 0, "failed": 0}

            if analysis["passed"]:
                results["passed"] += 1
                results["by_category"][cat]["passed"] += 1
                print(f"✅ {test.id}: {test.description}")
            else:
                results["failed"] += 1
                results["by_category"][cat]["failed"] += 1
                results["failures"].append(analysis)
                print(f"❌ {test.id}: {test.description}")
                for issue in analysis["issues"]:
                    print(f"   └─ {issue}")

        except Exception as e:
            results["failed"] += 1
            print(f"💥 {test.id}: ERROR - {e}")

    # Summary
    print("\n" + "=" * 70)
    print("📊 SUMMARY")
    print("=" * 70)
    print(f"Total Tests:  {results['total']}")
    print(f"Passed:       {results['passed']} ({results['passed']/results['total']*100:.1f}%)")
    print(f"Failed:       {results['failed']} ({results['failed']/results['total']*100:.1f}%)")

    print("\n📈 BY CATEGORY:")
    for cat, stats in results["by_category"].items():
        total = stats["passed"] + stats["failed"]
        rate = stats["passed"] / total * 100 if total > 0 else 0
        print(f"   {cat}: {stats['passed']}/{total} ({rate:.0f}%)")

    print("\n🔧 TOOL USAGE:")
    for tool, count in sorted(results["tool_usage"].items(), key=lambda x: -x[1]):
        print(f"   {tool}: {count} calls")

    return results


# Entry point for manual testing
if __name__ == "__main__":
    asyncio.run(generate_reliability_report())
