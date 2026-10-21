"""
LangGraph Orchestration Pipeline
Defines state graph with agent reasoning, tool execution, and response synthesis.
"""

from typing import Literal
from langgraph.graph import END, StateGraph
from src.agent.nodes import (
    agent_node,
    format_response_node,
    should_continue,
    tools_node,
)
from src.agent.state import AgentState

def build_agent_graph():
    """Build and compile the multi-turn agent workflow graph."""
    workflow = StateGraph(AgentState)

    # 1. Add Workflow Nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", tools_node)
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

    # Cycle tool output back into agent for synthesis or next tool call
    workflow.add_edge("tools", "agent")
    workflow.add_edge("format_response", END)

    return workflow.compile()

# Lazy singleton
_compiled_graph = None

def get_agent_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
    return _compiled_graph
