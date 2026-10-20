"""
LangGraph Orchestration Pipeline
Orchestrates Tools, Reasoning, and Structured Response Generation
"""

from typing import Literal
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from src.agent.model import get_llm
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.state import AgentState
from src.schemas.chat import AssistantResponse
from src.tools import ALL_TOOLS

def build_agent_graph():
    # Initialize LLM with tools bound
    base_llm = get_llm()
    llm_with_tools = base_llm.bind_tools(ALL_TOOLS)
    structured_llm = base_llm.with_structured_output(AssistantResponse)
    tool_node = ToolNode(ALL_TOOLS)

    def call_model(state: AgentState):
        messages = list(state.messages)
        # Ensure system prompt is prepended
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> Literal["tools", "format_response"]:
        last_message = state.messages[-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "format_response"

    def format_response(state: AgentState):
        # Format the final turn into structured AssistantResponse adhering to Adaptive Depth Protocol
        messages = list(state.messages)
        format_prompt = SystemMessage(
            content=(
                "Synthesize the conversation and tool execution results into an AssistantResponse following the Adaptive Depth Protocol:\n"
                "1. Answer direct consumer queries with the bottom-line metric first (start small, concise, and apt).\n"
                "2. If the user requested prolonged points, root-cause investigations, comparisons, or audits, provide structured technical sections (Executive Summary, Root-Cause Attribution, Calculations/Evidence, Recommendations).\n"
                "3. Populate 'key_metrics' with all core numerical results, attach data quality notes if nulls/exclusions exist, and if the user requested or benefits from visual analysis, attach the optimal 'chart' configuration.\n"
                "4. Maintain strict domain grounding: no external facts or outside common knowledge; only findings derived from tools and the Yamaha EMS knowledge base."
            )
        )
        structured_output = structured_llm.invoke(messages + [format_prompt])
        return {"structured_response": structured_output}

    # Build Graph
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    workflow.add_node("format_response", format_response)

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            "format_response": "format_response"
        }
    )
    workflow.add_edge("tools", "agent")
    workflow.add_edge("format_response", END)

    return workflow.compile()
