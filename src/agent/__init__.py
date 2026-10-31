"""
Agent Package
Exports LangGraph agent components.

Configuration Flags:
- AGENT_USE_REACT=true (default) - Use official LangGraph create_react_agent
- AGENT_USE_REACT=false - Use custom StateGraph implementation
- AGENT_USE_OPTIMIZED=false - Fallback to original (non-optimized) implementation
"""

import os

# Configuration flags
USE_REACT = os.getenv("AGENT_USE_REACT", "true").lower() != "false"
USE_OPTIMIZED = os.getenv("AGENT_USE_OPTIMIZED", "true").lower() != "false"

if USE_REACT:
    # Use official LangGraph ReAct agent (recommended)
    # This handles tool result pairing correctly for Bedrock
    from src.agent.react_agent import (
        build_react_agent as build_agent_graph,
        get_react_agent as get_agent_graph,
        handle_simple_greeting,
    )
    from src.agent.streaming_react import (
        streaming_engine,
        SSE_HEADERS,
    )
    from src.agent.intent_classifier import intent_classifier, QueryIntent
    from src.agent.tool_cache import tool_cache, cached_tool_execute
    from src.agent.history_compressor import history_compressor

    # Cache management functions
    def get_cache_stats():
        return tool_cache.stats

    def clear_cache(tool_name=None):
        return tool_cache.invalidate(tool_name)

    def cleanup_expired_cache():
        return tool_cache.cleanup_expired()

    # Stub nodes for compatibility (ReAct agent handles these internally)
    agent_node = None
    tools_node = None
    format_response_node = None
    should_continue = None

elif USE_OPTIMIZED:
    # Use custom optimized StateGraph implementation
    from src.agent.graph_optimized import (
        build_agent_graph,
        get_agent_graph,
        get_cache_stats,
        clear_cache,
        cleanup_expired_cache,
        handle_simple_greeting,
    )
    from src.agent.streaming_optimized import (
        streaming_engine,
        SSE_HEADERS,
    )
    from src.agent.nodes_optimized import (
        agent_node,
        tools_node,
        format_response_node,
        should_continue,
    )
    from src.agent.intent_classifier import intent_classifier, QueryIntent
    from src.agent.tool_cache import tool_cache, cached_tool_execute
    from src.agent.history_compressor import history_compressor
else:
    # Fallback to original implementations
    from src.agent.graph import build_agent_graph, get_agent_graph
    from src.agent.streaming import streaming_engine, SSE_HEADERS
    from src.agent.nodes import (
        agent_node,
        tools_node,
        format_response_node,
        should_continue,
    )

    # Stubs for optimized features
    def get_cache_stats():
        return {"status": "disabled", "reason": "using original implementation"}

    def clear_cache(tool_name=None):
        return 0

    def cleanup_expired_cache():
        return 0

    async def handle_simple_greeting(prompt, user_id, chat_id):
        return None

# Always export these
from src.agent.state import AgentState
from src.agent.orchestrator import orchestrator, ConversationOrchestrator
from src.agent.response_formatter import response_formatter, ResponseFormatter
from src.agent.model import get_llm

__all__ = [
    # Graph
    "build_agent_graph",
    "get_agent_graph",
    # Streaming
    "streaming_engine",
    "SSE_HEADERS",
    # Nodes
    "agent_node",
    "tools_node",
    "format_response_node",
    "should_continue",
    # State
    "AgentState",
    # Orchestrator
    "orchestrator",
    "ConversationOrchestrator",
    # Response
    "response_formatter",
    "ResponseFormatter",
    # Model
    "get_llm",
    # Optimization features
    "get_cache_stats",
    "clear_cache",
    "cleanup_expired_cache",
    "handle_simple_greeting",
    # Flags
    "USE_REACT",
    "USE_OPTIMIZED",
]
