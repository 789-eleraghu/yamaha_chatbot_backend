"""
Conversation History Compressor
Reduces token cost by compressing older turns while preserving context.
Uses extractive summarization (no LLM call needed).
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

# Configuration
MAX_RECENT_TURNS = 4  # Keep last N turns uncompressed
MAX_COMPRESSED_TURNS = 4  # Max older turns to summarize
MAX_TOOL_OUTPUT_TOKENS = 150  # Truncate tool outputs in history
MAX_ASSISTANT_TOKENS = 200  # Truncate assistant responses in history


def estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token average)."""
    return len(text) // 4


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximate token limit."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 20] + "... [truncated]"


def compress_tool_output(output: Any) -> str:
    """
    Compress tool output to essential information.
    Extracts key metrics, removes verbose chart configs.
    """
    if isinstance(output, str):
        return truncate_to_tokens(output, MAX_TOOL_OUTPUT_TOKENS)

    if not isinstance(output, dict):
        return truncate_to_tokens(str(output), MAX_TOOL_OUTPUT_TOKENS)

    # Extract key fields, skip verbose ones
    compressed = {}

    # Priority fields to keep
    priority_keys = [
        "energy_kwh", "total_kwh", "true_daily_kwh",
        "shift_a_kwh", "shift_b_kwh", "shift_c_kwh", "total_shifts_kwh",
        "peak_kva", "utilization_percent", "status",
        "total_cost_inr", "date", "error",
        "categories", "cost_centers", "band_summary",
    ]

    # Fields to skip (verbose, reconstructable)
    skip_keys = [
        "chart_config", "series", "x_labels", "hourly_breakdown",
        "hourly_profile", "heatmap_data", "scatter_series",
        "gauge_data", "mermaid_code", "representation_reason",
    ]

    for key in priority_keys:
        if key in output:
            value = output[key]
            # Truncate lists
            if isinstance(value, list) and len(value) > 5:
                value = value[:5] + [f"... +{len(value) - 5} more"]
            compressed[key] = value

    # Add other keys (not skipped, not priority)
    for key, value in output.items():
        if key in skip_keys or key in priority_keys:
            continue
        if key.startswith("_"):
            continue
        # Only add simple values
        if isinstance(value, (str, int, float, bool, type(None))):
            compressed[key] = value

    result = json.dumps(compressed, default=str)
    return truncate_to_tokens(result, MAX_TOOL_OUTPUT_TOKENS)


def compress_assistant_message(content: str) -> str:
    """
    Compress assistant response to key information.
    Removes markdown formatting, keeps first paragraph + key metrics.
    """
    if not content:
        return ""

    # Remove markdown formatting
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', content)  # Bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)  # Italic
    text = re.sub(r'#+\s*', '', text)  # Headers
    text = re.sub(r'\n{3,}', '\n\n', text)  # Multiple newlines
    text = re.sub(r'[-*]\s+', '• ', text)  # List markers

    # Extract first paragraph and any numeric values
    paragraphs = text.strip().split('\n\n')
    if not paragraphs:
        return truncate_to_tokens(text, MAX_ASSISTANT_TOKENS)

    # Keep first paragraph
    first = paragraphs[0].strip()

    # Find key metrics in remaining text
    metrics_pattern = r'(\d[\d,]*\.?\d*)\s*(kWh|kVA|INR|₹|%|hours?|kg)'
    all_metrics = re.findall(metrics_pattern, content)

    if len(paragraphs) > 1 and all_metrics:
        metrics_str = " | ".join([f"{m[0]} {m[1]}" for m in all_metrics[:5]])
        return truncate_to_tokens(f"{first} [Key: {metrics_str}]", MAX_ASSISTANT_TOKENS)

    return truncate_to_tokens(first, MAX_ASSISTANT_TOKENS)


def create_summary_message(older_turns: List[BaseMessage]) -> Optional[HumanMessage]:
    """
    Create a summary message for older conversation turns.
    Returns a single HumanMessage containing the compressed context.
    """
    if not older_turns:
        return None

    summaries = []
    for msg in older_turns:
        role = "User" if isinstance(msg, HumanMessage) else "Assistant"
        content = getattr(msg, "content", "")

        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            # Handle structured content
            text = " ".join([
                p.get("text", "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ])
        else:
            text = str(content)

        if isinstance(msg, HumanMessage):
            # Keep user queries mostly intact (usually short)
            compressed = truncate_to_tokens(text, 100)
        else:
            compressed = compress_assistant_message(text)

        if compressed:
            summaries.append(f"[{role}]: {compressed}")

    if not summaries:
        return None

    summary_text = (
        "[Prior conversation summary]\n" +
        "\n".join(summaries) +
        "\n[End of summary - continue from here]"
    )

    return HumanMessage(content=summary_text)


class HistoryCompressor:
    """
    Compresses conversation history to reduce token usage.
    Strategy:
    1. Keep last N turns uncompressed (most relevant)
    2. Summarize older turns into a single context message
    3. Truncate tool outputs and assistant responses
    """

    @staticmethod
    def compress_history(
        messages: List[BaseMessage],
        max_recent: int = MAX_RECENT_TURNS,
        max_compressed: int = MAX_COMPRESSED_TURNS
    ) -> List[BaseMessage]:
        """
        Compress conversation history.
        Returns optimized message list with reduced token count.
        """
        if not messages:
            return []

        # Separate system messages
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        convo_msgs = [m for m in messages if not isinstance(m, SystemMessage)]

        if len(convo_msgs) <= max_recent:
            # No compression needed
            return messages

        # Split into older and recent
        split_point = len(convo_msgs) - max_recent
        older_msgs = convo_msgs[:split_point]
        recent_msgs = convo_msgs[split_point:]

        # Limit how many old messages to summarize
        if len(older_msgs) > max_compressed:
            older_msgs = older_msgs[-max_compressed:]

        # Create summary of older messages
        summary_msg = create_summary_message(older_msgs)

        # Build compressed history
        result = list(system_msgs)
        if summary_msg:
            result.append(summary_msg)
        result.extend(recent_msgs)

        return result

    @staticmethod
    def compress_for_bedrock(
        messages: List[BaseMessage],
        max_recent: int = MAX_RECENT_TURNS
    ) -> List[BaseMessage]:
        """
        Compress history specifically for Bedrock Converse API.
        Ensures message alternation (user/assistant/user/assistant).
        Always preserves ToolMessage paired with AIMessage(tool_calls).
        """
        compressed = HistoryCompressor.compress_history(messages, max_recent)

        # Ensure proper alternation for Bedrock
        result = []
        last_role = None

        for msg in compressed:
            if isinstance(msg, SystemMessage):
                result.append(msg)
                continue

            # ToolMessage is vital for tool-calling loops and must NEVER be dropped
            if isinstance(msg, ToolMessage):
                result.append(msg)
                last_role = "tool"
                continue

            current_role = "user" if isinstance(msg, HumanMessage) else "assistant"

            # Skip consecutive same-role messages (keep first), except across tool boundaries
            if current_role == last_role and last_role != "tool":
                continue

            result.append(msg)
            last_role = current_role

        # Ensure starts with user message (after system)
        non_system = [m for m in result if not isinstance(m, SystemMessage)]
        if non_system and not isinstance(non_system[0], HumanMessage):
            # Remove leading assistant message
            result = [m for m in result if isinstance(m, SystemMessage)] + non_system[1:]

        return result

    @staticmethod
    def estimate_history_tokens(messages: List[BaseMessage]) -> int:
        """Estimate total tokens in message history."""
        total = 0
        for msg in messages:
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                total += estimate_tokens(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total += estimate_tokens(str(part))
        return total


history_compressor = HistoryCompressor()
