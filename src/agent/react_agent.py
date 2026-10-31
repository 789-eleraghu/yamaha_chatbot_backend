"""
LangGraph ReAct Agent Implementation
Uses the official create_react_agent() for robust tool-calling with Bedrock.

This replaces the custom StateGraph implementation with LangGraph's built-in
ReAct pattern which properly handles:
- Tool call/result message ordering (fixes Bedrock ValidationException)
- Parallel tool execution
- Recursive loop control
- Proper streaming events
"""

from typing import Any, Dict, List, Optional, Literal
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

from src.agent.model import get_llm
from src.agent.intent_classifier import QueryIntent, intent_classifier
from src.agent.history_compressor import history_compressor
from src.agent.prompts_optimized import build_system_prompt, get_tool_selection_hint
from src.agent.response_formatter import response_formatter
from src.schemas.chat import AssistantResponse
from src.services.date_service import date_service
from src.tools import ALL_TOOLS

# Maximum iterations for ReAct loop
MAX_ITERATIONS = 5


def build_react_agent():
    """
    Build the ReAct agent using LangGraph's create_react_agent.

    This is the recommended approach for tool-calling agents as it:
    1. Properly handles tool call/result pairing (fixes Bedrock errors)
    2. Supports parallel tool execution
    3. Manages message history correctly
    4. Provides proper streaming events (on_tool_start, on_tool_end)
    """
    llm = get_llm()

    # Create the ReAct agent with all tools
    # The agent will automatically bind tools and handle the loop
    agent = create_react_agent(
        model=llm,
        tools=ALL_TOOLS,
        # Optional: add memory for multi-turn conversations
        # checkpointer=MemorySaver(),
    )

    return agent


def get_optimized_system_prompt(user_query: str) -> str:
    """
    Build an optimized system prompt based on intent classification.
    This reduces token usage by only including relevant instructions.
    """
    # Classify intent
    intents, confidence = intent_classifier.classify(user_query)

    # Get effective dates
    eff_date = date_service.get_effective_default_date()
    eff_yesterday = date_service.normalize_and_validate_date("yesterday")

    # Determine if we need full constitution
    include_full = confidence < 0.4 or QueryIntent.AMBIGUOUS in intents

    system_prompt = build_system_prompt(
        intents=intents,
        effective_date=eff_date,
        yesterday_date=eff_yesterday,
        include_full_constitution=include_full
    )

    # Add tool selection hints
    tools, _, _ = intent_classifier.get_optimized_tools(user_query)
    if tools:
        system_prompt += get_tool_selection_hint(intents)

    return system_prompt


def prepare_messages_for_agent(
    messages: List[BaseMessage],
    user_query: str,
    compress_history: bool = True,
    max_recent: int = 4
) -> List[BaseMessage]:
    """
    Prepare messages for the ReAct agent:
    1. Add optimized system prompt
    2. Compress history if needed
    3. Ensure proper message ordering
    """
    # Get optimized system prompt
    system_prompt = get_optimized_system_prompt(user_query)

    # Filter out existing system messages
    non_system = [m for m in messages if not isinstance(m, SystemMessage)]

    # Apply history compression if enabled
    if compress_history and len(non_system) > max_recent * 2:
        non_system = history_compressor.compress_for_bedrock(non_system, max_recent=max_recent)

    # Ensure tool calls have matching tool results
    non_system = ensure_tool_result_pairing(non_system)

    # Build final message list
    return [SystemMessage(content=system_prompt)] + non_system


def ensure_tool_result_pairing(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Ensure every tool call has a corresponding tool result.
    This fixes Bedrock ValidationException errors.
    """
    result = []
    pending_tool_calls: Dict[str, dict] = {}

    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
            # Track pending tool calls
            for tc in msg.tool_calls:
                tool_id = tc.get('id')
                if tool_id:
                    pending_tool_calls[tool_id] = tc
            result.append(msg)

        elif isinstance(msg, ToolMessage):
            # Match tool result to call
            tool_call_id = getattr(msg, 'tool_call_id', None)
            if tool_call_id and tool_call_id in pending_tool_calls:
                del pending_tool_calls[tool_call_id]
            result.append(msg)

        else:
            # If there are pending tool calls without results, add placeholder results
            if pending_tool_calls:
                for tool_id, tc in pending_tool_calls.items():
                    result.append(ToolMessage(
                        content="[Tool execution incomplete or skipped]",
                        tool_call_id=tool_id,
                        name=tc.get('name', 'unknown')
                    ))
                pending_tool_calls.clear()
            result.append(msg)

    # Handle any remaining pending tool calls at the end
    for tool_id, tc in pending_tool_calls.items():
        result.append(ToolMessage(
            content="[Tool execution incomplete or skipped]",
            tool_call_id=tool_id,
            name=tc.get('name', 'unknown')
        ))

    return result


def format_agent_response(
    messages: List[BaseMessage],
    executed_tools: List[Dict[str, Any]]
) -> AssistantResponse:
    """
    Format the agent's response into a structured AssistantResponse.
    Extracts the final AI message and any tool outputs.
    """
    # Find the last AI message that's not a tool call
    final_text = ""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            # Skip if this message only has tool calls
            if hasattr(msg, 'tool_calls') and msg.tool_calls and not msg.content:
                continue

            if isinstance(msg.content, str):
                final_text = msg.content
                break
            elif isinstance(msg.content, list):
                parts = [
                    p.get('text', '')
                    for p in msg.content
                    if isinstance(p, dict) and p.get('type') == 'text'
                ]
                final_text = ' '.join(parts).strip()
                if final_text:
                    break

    if not final_text:
        final_text = "Analysis completed."

    # Build structured response
    return response_formatter.build_assistant_response(
        answer_markdown=final_text,
        executed_tools=executed_tools
    )


def extract_executed_tools(messages: List[BaseMessage]) -> List[Dict[str, Any]]:
    """
    Extract executed tool information from message history.
    """
    executed = []
    tool_calls_by_id: Dict[str, dict] = {}

    # First pass: collect all tool calls
    for msg in messages:
        if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_id = tc.get('id')
                if tool_id:
                    tool_calls_by_id[tool_id] = {
                        'name': tc.get('name', 'unknown'),
                        'input': tc.get('args', {}),
                        'call_id': tool_id
                    }

    # Second pass: match with results
    for msg in messages:
        if isinstance(msg, ToolMessage):
            tool_call_id = getattr(msg, 'tool_call_id', None)
            if tool_call_id and tool_call_id in tool_calls_by_id:
                tool_info = tool_calls_by_id[tool_call_id]

                # Parse content
                try:
                    import json
                    content = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                except (json.JSONDecodeError, TypeError):
                    content = msg.content

                executed.append({
                    'name': tool_info['name'],
                    'input': tool_info['input'],
                    'output': content,
                    'call_id': tool_call_id
                })

    return executed


# ============================================================================
# Quick Response Path for Greetings
# ============================================================================

def is_simple_greeting(query: str) -> bool:
    """Check if query is a simple greeting that doesn't need tools."""
    intents, confidence = intent_classifier.classify(query)
    return intents == {QueryIntent.GREETING} and confidence > 0.8


def generate_greeting_response(query: str) -> str:
    """Generate a simple greeting response without LLM call."""
    query_lower = query.lower().strip()

    greetings = {
        "hi": "Hello! I'm the Yamaha Energy Assistant. How can I help you with plant energy analysis today?",
        "hello": "Hi there! I'm ready to help with energy consumption, demand analysis, or equipment monitoring. What would you like to know?",
        "hey": "Hey! I'm your Yamaha Industrial Energy Assistant. Ask me about facility consumption, shift breakdowns, or power quality.",
        "good morning": "Good morning! Ready to help with your energy management queries. What can I analyze for you?",
        "good afternoon": "Good afternoon! How can I assist with plant energy analysis?",
        "good evening": "Good evening! What energy insights can I provide for you?",
    }

    for key, response in greetings.items():
        if query_lower.startswith(key):
            return response

    return "Hello! I'm the Yamaha Industrial Energy Assistant. I can help with energy consumption analysis, demand monitoring, shift breakdowns, and power quality. What would you like to know?"


async def handle_simple_greeting(prompt: str, user_id: str, chat_id: str) -> Optional[Dict[str, Any]]:
    """
    Fast path for simple greetings - bypasses agent entirely.
    Returns None if not a simple greeting.
    """
    if not is_simple_greeting(prompt):
        return None

    response_text = generate_greeting_response(prompt)

    return {
        "all_tools": [],
        "tool_name": "direct_response",
        "tool_input": {},
        "tool_output": {},
        "answer_markdown": response_text,
        "key_metrics": {},
        "chart": None,
        "data_quality_notes": None,
        "structured_response": AssistantResponse(
            answer_markdown=response_text,
            key_metrics={},
            chart=None,
            data_quality_notes=None
        ),
        "_fast_path": True
    }


# ============================================================================
# Singleton Agent Instance
# ============================================================================

_react_agent = None


def get_react_agent():
    """Get or create the singleton ReAct agent."""
    global _react_agent
    if _react_agent is None:
        _react_agent = build_react_agent()
    return _react_agent


# ============================================================================
# Backwards Compatibility Aliases
# ============================================================================

def get_agent_graph():
    """Alias for backwards compatibility."""
    return get_react_agent()


def get_optimized_graph():
    """Alias for backwards compatibility."""
    return get_react_agent()


def build_agent_graph():
    """Alias for backwards compatibility."""
    return build_react_agent()


def build_optimized_graph():
    """Alias for backwards compatibility."""
    return build_react_agent()
