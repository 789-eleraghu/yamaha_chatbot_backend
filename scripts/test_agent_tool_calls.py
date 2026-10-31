#!/usr/bin/env python3
"""
🔬 AGENT TOOL CALL ANALYZER
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Runs test queries through the agent and analyzes:
1. Which tools were called
2. What parameters were passed
3. Whether the right tool was selected
4. Tool confusion detection

Usage:
    python scripts/test_agent_tool_calls.py
    python scripts/test_agent_tool_calls.py --query "your custom query"
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import HumanMessage


# ============================================================================
# TEST CASES
# ============================================================================

@dataclass
class TestCase:
    query: str
    expected_tool: str
    expected_params: Dict[str, Any]
    forbidden_tools: List[str]
    category: str
    description: str


TEST_CASES = [
    # === FACILITY ENERGY ===
    TestCase(
        query="What was yesterday's energy consumption?",
        expected_tool="get_cummulative_energy",
        expected_params={},
        forbidden_tools=["grouping_energy"],
        category="facility",
        description="Basic facility energy",
    ),
    TestCase(
        query="Total kWh for 2026-10-20",
        expected_tool="get_cummulative_energy",
        expected_params={},
        forbidden_tools=["grouping_energy"],
        category="facility",
        description="Energy with specific date",
    ),

    # === SOLAR ===
    TestCase(
        query="How much solar did we generate?",
        expected_tool="get_cummulative_energy",
        expected_params={},
        forbidden_tools=[],
        category="solar",
        description="Solar generation",
    ),

    # === POWER QUALITY ===
    TestCase(
        query="What is today's power factor?",
        expected_tool="get_instantaneous_energy",
        expected_params={"parameter": "power_factor"},
        forbidden_tools=["get_cummulative_energy"],
        category="power_quality",
        description="Power factor query",
    ),
    TestCase(
        query="Show THD levels",
        expected_tool="get_instantaneous_energy",
        expected_params={},
        forbidden_tools=["get_cummulative_energy"],
        category="power_quality",
        description="THD query",
    ),
    TestCase(
        query="What is the PF?",
        expected_tool="get_instantaneous_energy",
        expected_params={"parameter": "power_factor"},
        forbidden_tools=["get_cummulative_energy"],
        category="power_quality",
        description="PF abbreviation",
    ),

    # === EQUIPMENT ===
    TestCase(
        query="Compressor energy consumption yesterday",
        expected_tool="get_cummulative_energy",
        expected_params={},
        forbidden_tools=[],
        category="equipment",
        description="Specific equipment",
    ),
    TestCase(
        query="How much did molding machines use?",
        expected_tool="get_cummulative_energy",
        expected_params={},
        forbidden_tools=[],
        category="equipment",
        description="Molding equipment",
    ),
    TestCase(
        query="Show me all equipment breakdown",
        expected_tool="create_visualization",  # "breakdown" implies chart, not raw data
        expected_params={},
        forbidden_tools=[],
        category="equipment",
        description="All equipment (chart)",
    ),

    # === ZONES ===
    TestCase(
        query="AG Assy zone consumption",
        expected_tool="get_cummulative_energy",
        expected_params={},
        forbidden_tools=[],
        category="zones",
        description="Specific zone",
    ),
    TestCase(
        query="Group energy by cost center",
        expected_tool="grouping_energy",
        expected_params={"group_by": "zone"},
        forbidden_tools=[],
        category="zones",
        description="Cost center = Zone",
    ),
    TestCase(
        query="What was the shift consumption yesterday?",
        expected_tool="grouping_energy",
        expected_params={"group_by": "shift"},
        forbidden_tools=[],
        category="facility",
        description="Shift breakdown with grouping",
    ),

    # === TARIFF/COST ===
    TestCase(
        query="What was yesterday's electricity cost?",
        expected_tool="grouping_energy",
        expected_params={"group_by": "tariff"},
        forbidden_tools=["get_cummulative_energy"],
        category="tariff",
        description="Cost query",
    ),
    TestCase(
        query="Show TOD tariff breakdown chart",
        expected_tool="create_visualization",  # "breakdown chart" implies chart
        expected_params={},
        forbidden_tools=[],
        category="tariff",
        description="Tariff breakdown (chart)",
    ),

    # === GENERATOR ===
    TestCase(
        query="DG runtime yesterday",
        expected_tool="get_instantaneous_energy",
        expected_params={},
        forbidden_tools=[],
        category="generator",
        description="Generator query",
    ),

    # === DIAGNOSTICS ===
    TestCase(
        query="Why was consumption high yesterday?",
        expected_tool="diagnose_consumption",
        expected_params={},
        forbidden_tools=["get_cummulative_energy"],
        category="diagnostics",
        description="Root cause analysis",
    ),
    TestCase(
        query="Explain the spike at 2pm",
        expected_tool="explain_hourly_anomaly",
        expected_params={},
        forbidden_tools=[],
        category="diagnostics",
        description="Hourly anomaly",
    ),

    # === VISUALIZATION ===
    TestCase(
        query="Show equipment breakdown chart",
        expected_tool="create_visualization",
        expected_params={},
        forbidden_tools=["get_cummulative_energy"],
        category="visualization",
        description="Equipment chart",
    ),
    TestCase(
        query="Zone comparison bar chart",
        expected_tool="create_visualization",
        expected_params={},
        forbidden_tools=[],
        category="visualization",
        description="Zone chart",
    ),
    TestCase(
        query="Hourly load profile",
        expected_tool="create_visualization",
        expected_params={},
        forbidden_tools=[],
        category="visualization",
        description="Hourly profile",
    ),
    TestCase(
        query="Peak demand gauge",
        expected_tool="create_visualization",
        expected_params={},
        forbidden_tools=["get_instantaneous_energy"],
        category="visualization",
        description="Gauge chart",
    ),
    TestCase(
        query="Show equipment as pie chart",
        expected_tool="create_visualization",
        expected_params={},
        forbidden_tools=[],
        category="visualization",
        description="Chart type change",
    ),

    # === TOOL CONFUSION TESTS ===
    TestCase(
        query="Show me energy chart",
        expected_tool="create_visualization",
        expected_params={},
        forbidden_tools=["get_cummulative_energy"],
        category="confusion",
        description="Chart not data - should use visualization",
    ),
    TestCase(
        query="What was yesterday's power consumption?",
        expected_tool="get_cummulative_energy",
        expected_params={},
        forbidden_tools=["get_instantaneous_energy"],
        category="confusion",
        description="Power consumption = Energy, not PQ",
    ),
]


# ============================================================================
# TOOL CALL CAPTURE
# ============================================================================

async def run_agent_and_capture_tools(query: str) -> Dict[str, Any]:
    """Run a query through the agent and capture all tool calls."""

    from src.agent.graph import get_agent_graph
    from src.agent.state import AgentState

    initial_state = AgentState(
        messages=[HumanMessage(content=query)],
        tool_executions=[],
        response_text="",
    )

    graph = get_agent_graph()
    tool_calls = []

    try:
        async for event in graph.astream_events(initial_state, version="v2"):
            event_type = event.get("event", "")

            # Capture tool start events
            if event_type == "on_tool_start":
                tool_name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                tool_calls.append({
                    "tool": tool_name,
                    "params": tool_input,
                    "event": "start",
                })

            # Capture tool end events
            elif event_type == "on_tool_end":
                tool_name = event.get("name", "unknown")
                tool_output = event.get("data", {}).get("output", {})
                # Find the matching start and add output
                for tc in reversed(tool_calls):
                    if tc["tool"] == tool_name and "output" not in tc:
                        tc["output"] = str(tool_output)[:200]  # Truncate
                        tc["event"] = "complete"
                        break

    except Exception as e:
        return {
            "query": query,
            "error": str(e),
            "tool_calls": [],
        }

    return {
        "query": query,
        "tool_calls": tool_calls,
        "tools_called": [tc["tool"] for tc in tool_calls],
    }


def analyze_result(result: Dict, test_case: TestCase) -> Dict[str, Any]:
    """Analyze whether the agent made correct tool calls."""

    analysis = {
        "test": test_case.description,
        "query": test_case.query,
        "expected_tool": test_case.expected_tool,
        "actual_tools": result.get("tools_called", []),
        "passed": True,
        "issues": [],
        "params_check": {},
    }

    tools_called = result.get("tools_called", [])

    # Check if expected tool was called
    if test_case.expected_tool not in tools_called:
        analysis["passed"] = False
        analysis["issues"].append(f"MISSING: Expected '{test_case.expected_tool}' not called")

    # Check for forbidden tools
    for forbidden in test_case.forbidden_tools:
        if forbidden in tools_called:
            analysis["passed"] = False
            analysis["issues"].append(f"CONFUSION: Forbidden tool '{forbidden}' was called")

    # Check parameters if expected tool was called
    if test_case.expected_tool in tools_called:
        for tc in result.get("tool_calls", []):
            if tc["tool"] == test_case.expected_tool:
                actual_params = tc.get("params", {})
                for param, expected_val in test_case.expected_params.items():
                    if param not in actual_params:
                        analysis["issues"].append(f"PARAM MISSING: '{param}'")
                    else:
                        actual_val = actual_params[param]
                        # Allow valid synonyms
                        if param == "parameter":
                            if str(actual_val).lower() in ("pf", "power_factor") and str(expected_val).lower() in ("pf", "power_factor"):
                                analysis["params_check"][param] = "✓"
                                continue
                            if str(actual_val).lower() in ("thd", "harmonics") and str(expected_val).lower() in ("thd", "harmonics"):
                                analysis["params_check"][param] = "✓"
                                continue
                        if param == "group_by":
                            if str(actual_val).lower() in ("zone", "cost_center", "zones") and str(expected_val).lower() in ("zone", "cost_center"):
                                analysis["params_check"][param] = "✓"
                                continue
                            if str(actual_val).lower() in ("tariff", "tod", "cost") and str(expected_val).lower() in ("tariff", "tod", "cost"):
                                analysis["params_check"][param] = "✓"
                                continue
                        if actual_val != expected_val:
                            analysis["issues"].append(
                                f"PARAM WRONG: '{param}' = '{actual_val}' (expected '{expected_val}')"
                            )
                        else:
                            analysis["params_check"][param] = "✓"
                break

    return analysis


# ============================================================================
# MAIN RUNNER
# ============================================================================

async def run_single_query(query: str):
    """Run a single query and show results."""

    print(f"\n{'='*70}")
    print(f"🔬 Query: {query}")
    print(f"{'='*70}")

    result = await run_agent_and_capture_tools(query)

    if "error" in result:
        print(f"❌ ERROR: {result['error']}")
        return

    print(f"\n📋 Tool Calls Made:")
    for i, tc in enumerate(result["tool_calls"], 1):
        print(f"\n   {i}. {tc['tool']}")
        print(f"      Parameters: {json.dumps(tc['params'], indent=8)}")

    if not result["tool_calls"]:
        print("   (No tools called - agent may have asked for clarification)")


async def run_all_tests():
    """Run all test cases and generate report."""

    print("\n" + "=" * 70)
    print("🔬 AGENT RELIABILITY TEST SUITE")
    print("=" * 70)
    print(f"Running {len(TEST_CASES)} test cases...")
    print()

    results = {
        "total": len(TEST_CASES),
        "passed": 0,
        "failed": 0,
        "by_category": {},
        "failures": [],
        "confusion_detected": [],
    }

    for i, test_case in enumerate(TEST_CASES, 1):
        print(f"[{i:2d}/{len(TEST_CASES)}] {test_case.description}...", end=" ", flush=True)

        try:
            result = await run_agent_and_capture_tools(test_case.query)
            analysis = analyze_result(result, test_case)

            # Track by category
            cat = test_case.category
            if cat not in results["by_category"]:
                results["by_category"][cat] = {"passed": 0, "failed": 0, "tests": []}

            if analysis["passed"]:
                results["passed"] += 1
                results["by_category"][cat]["passed"] += 1
                print("✅")
            else:
                results["failed"] += 1
                results["by_category"][cat]["failed"] += 1
                results["failures"].append(analysis)
                print("❌")

                # Check for confusion
                if any("CONFUSION" in issue for issue in analysis["issues"]):
                    results["confusion_detected"].append({
                        "query": test_case.query,
                        "expected": test_case.expected_tool,
                        "actual": analysis["actual_tools"],
                    })

            results["by_category"][cat]["tests"].append(analysis)

        except Exception as e:
            results["failed"] += 1
            print(f"💥 ERROR: {e}")

    # Print Summary
    print("\n" + "=" * 70)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 70)

    pass_rate = results["passed"] / results["total"] * 100
    print(f"\n   Total:  {results['total']}")
    print(f"   Passed: {results['passed']} ({pass_rate:.1f}%)")
    print(f"   Failed: {results['failed']}")

    # Category breakdown
    print(f"\n📈 BY CATEGORY:")
    print("   " + "-" * 50)
    for cat, stats in sorted(results["by_category"].items()):
        total = stats["passed"] + stats["failed"]
        rate = stats["passed"] / total * 100 if total > 0 else 0
        status = "✅" if stats["failed"] == 0 else "⚠️"
        print(f"   {status} {cat:15s}: {stats['passed']}/{total} ({rate:.0f}%)")

    # Tool confusion report
    if results["confusion_detected"]:
        print(f"\n🚨 TOOL CONFUSION DETECTED ({len(results['confusion_detected'])} cases):")
        print("   " + "-" * 50)
        for conf in results["confusion_detected"]:
            print(f"   Query: \"{conf['query'][:50]}...\"")
            print(f"   Expected: {conf['expected']}")
            print(f"   Called:   {conf['actual']}")
            print()

    # Detailed failures
    if results["failures"]:
        print(f"\n❌ FAILURES DETAIL:")
        print("   " + "-" * 50)
        for fail in results["failures"]:
            print(f"\n   Test: {fail['test']}")
            print(f"   Query: \"{fail['query'][:60]}\"")
            print(f"   Expected: {fail['expected_tool']}")
            print(f"   Actual:   {fail['actual_tools']}")
            for issue in fail["issues"]:
                print(f"   └─ {issue}")

    # Return for programmatic use
    return results


def main():
    parser = argparse.ArgumentParser(description="Test agent tool calling reliability")
    parser.add_argument("--query", "-q", help="Run a single custom query")
    parser.add_argument("--all", "-a", action="store_true", help="Run all test cases")
    args = parser.parse_args()

    if args.query:
        asyncio.run(run_single_query(args.query))
    else:
        asyncio.run(run_all_tests())


if __name__ == "__main__":
    main()
