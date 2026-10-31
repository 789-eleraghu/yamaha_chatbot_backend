"""
LangGraph Orchestration Pipeline
Defines state graph with agent reasoning, tool execution, and response synthesis.
"""

from typing import Literal
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from src.agent.nodes import (
    agent_node,
    capture_tool_executions,
    format_response_node,
    should_continue,
)
from src.agent.state import AgentState
from src.tools import ALL_TOOLS

# Create LangGraph ToolNode for proper streaming events (on_tool_start, on_tool_end)
# This is critical for frontend tool UI rendering - the ToolNode emits streaming events
# that the frontend uses to display tool execution status and results.
_tool_node = ToolNode(ALL_TOOLS)

def build_agent_graph():
    """Build and compile the multi-turn agent workflow graph."""
    workflow = StateGraph(AgentState)

    # 1. Add Workflow Nodes
    # Using LangGraph's ToolNode directly ensures on_tool_start/on_tool_end events
    # are properly emitted during graph.astream_events() for frontend rendering
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", _tool_node)  # LangGraph ToolNode for proper streaming
    workflow.add_node("capture_tools", capture_tool_executions)  # Track executed tools
    workflow.add_node("format_response", format_response_node)

    # 2. Configure Entry Point & Conditional Edges
    workflow.set_entry_point("agent")

    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "format_response": "format_response",
            "__end__": END
        }
    )

    # After tools execute, capture the execution data, then return to agent
    workflow.add_edge("tools", "capture_tools")
    workflow.add_edge("capture_tools", "agent")
    workflow.add_edge("format_response", END)

    return workflow.compile()

# Lazy singleton
_compiled_graph = None

def get_agent_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
    return _compiled_graph
