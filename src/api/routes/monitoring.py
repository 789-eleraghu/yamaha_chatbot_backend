"""
Monitoring & Cache Management Endpoints
Provides observability into agent performance and cache efficiency.
"""

from fastapi import APIRouter, Query
from typing import Optional

from src.agent import get_cache_stats, clear_cache, cleanup_expired_cache, USE_OPTIMIZED
from src.agent.intent_classifier import intent_classifier

router = APIRouter(tags=["Monitoring"])


@router.get("/monitoring/optimization-status")
async def get_optimization_status():
    """Check if optimized agent implementation is active."""
    return {
        "optimized_enabled": USE_OPTIMIZED,
        "cache_enabled": USE_OPTIMIZED,
        "intent_classification_enabled": USE_OPTIMIZED,
        "history_compression_enabled": USE_OPTIMIZED,
    }


@router.get("/monitoring/cache/stats")
async def get_cache_statistics():
    """
    Get tool result cache statistics.
    Returns hit rate, size, and cache efficiency metrics.
    """
    return get_cache_stats()


@router.post("/monitoring/cache/clear")
async def clear_tool_cache(tool_name: Optional[str] = Query(default=None)):
    """
    Clear tool result cache.
    If tool_name provided, only clears entries for that tool.
    Returns count of invalidated entries.
    """
    count = clear_cache(tool_name)
    return {
        "status": "cleared",
        "tool_filter": tool_name,
        "entries_invalidated": count
    }


@router.post("/monitoring/cache/cleanup")
async def cleanup_expired_entries():
    """
    Remove expired cache entries.
    Returns count of removed entries.
    """
    count = cleanup_expired_cache()
    return {
        "status": "cleaned",
        "expired_entries_removed": count
    }


@router.post("/monitoring/classify-intent")
async def classify_query_intent(query: str = Query(...)):
    """
    Debug endpoint: classify a query and show intent detection results.
    Useful for tuning intent patterns.
    """
    intents, confidence = intent_classifier.classify(query)
    tools, _, _ = intent_classifier.get_optimized_tools(query)

    return {
        "query": query,
        "intents": [i.value for i in intents],
        "confidence": round(confidence, 3),
        "tools_selected": len(tools),
        "tool_names": [t.name for t in tools] if tools else []
    }


@router.get("/monitoring/token-estimate")
async def estimate_tokens_for_query(
    query: str = Query(...),
    history_turns: int = Query(default=8)
):
    """
    Estimate token usage for a query with given history depth.
    Compares original vs optimized implementation.
    """
    from src.agent.intent_classifier import intent_classifier
    from src.agent.history_compressor import estimate_tokens

    # Classify intent
    intents, confidence = intent_classifier.classify(query)
    tools, _, _ = intent_classifier.get_optimized_tools(query)

    # Estimate system prompt tokens
    original_system_tokens = 3000  # Fixed estimate

    # Optimized system prompt varies by intent
    if intents == {"greeting"}:
        optimized_system_tokens = 350
    elif confidence > 0.6:
        optimized_system_tokens = 800
    else:
        optimized_system_tokens = 1200

    # Tool schemas
    original_tool_tokens = 4000  # ~20 tools
    optimized_tool_tokens = len(tools) * 180  # ~180 tokens per tool

    # History tokens (estimated)
    avg_turn_tokens = 600
    original_history_tokens = min(history_turns, 8) * avg_turn_tokens
    optimized_history_tokens = (
        4 * avg_turn_tokens +  # Recent turns uncompressed
        min(history_turns - 4, 4) * 150  # Older turns compressed
    ) if history_turns > 4 else history_turns * avg_turn_tokens

    # Query tokens
    query_tokens = estimate_tokens(query)

    # Totals
    original_total = original_system_tokens + original_tool_tokens + original_history_tokens + query_tokens
    optimized_total = optimized_system_tokens + optimized_tool_tokens + optimized_history_tokens + query_tokens

    savings_pct = round((1 - optimized_total / original_total) * 100, 1) if original_total > 0 else 0

    return {
        "query": query,
        "history_turns": history_turns,
        "original": {
            "system_prompt": original_system_tokens,
            "tool_schemas": original_tool_tokens,
            "history": original_history_tokens,
            "query": query_tokens,
            "total": original_total
        },
        "optimized": {
            "system_prompt": optimized_system_tokens,
            "tool_schemas": optimized_tool_tokens,
            "history": optimized_history_tokens,
            "query": query_tokens,
            "total": optimized_total
        },
        "savings": {
            "tokens": original_total - optimized_total,
            "percentage": savings_pct
        }
    }
