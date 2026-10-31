"""
ReAct Agent Streaming Protocol Engine
Uses LangGraph's create_react_agent for robust tool-calling with proper
tool result pairing (fixes Bedrock ValidationException errors).

Key Improvements over custom StateGraph:
1. Proper tool call/result message ordering
2. Built-in parallel tool execution
3. Automatic recursion limit
4. Clean message state management
"""

import asyncio
import datetime
import json
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tracers import LangChainTracer

from src.agent.react_agent import (
    get_react_agent,
    prepare_messages_for_agent,
    format_agent_response,
    extract_executed_tools,
    is_simple_greeting,
    generate_greeting_response,
)
from src.agent.history_compressor import history_compressor
from src.agent.intent_classifier import intent_classifier
from src.agent.response_formatter import response_formatter
from src.agent.tool_cache import tool_cache
from src.core.config import settings
from src.schemas.chat import AssistantResponse
from src.services.chat_service import chat_service
from src.guardrails.guardrails_service import guardrails_service


SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "x-vercel-ai-ui-message-stream": "v1",
    "X-Accel-Buffering": "no",
}


def extract_text_delta(chunk: Any) -> Optional[str]:
    """Extract text delta from streaming chunk."""
    if not chunk:
        return None
    content = getattr(chunk, "content", None)
    if not content:
        return None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                txt = part.get("text", "")
                if txt:
                    parts.append(txt)
        if parts:
            return "".join(parts)
    return None


# Reasoning patterns to filter out (model's internal thinking that shouldn't be shown)
REASONING_PATTERNS = [
    "It seems there was a mismatch",
    "Let me correct this",
    "I will now generate",
    "Let me fetch",
    "I need to call",
    "This suggests",
    "Let's fix this",
    "✅ I will now",
    "It appears the system",
    "Let me execute",
    "I'll execute",
    "I'll now call",
    "Let me call",
    "I'm going to",
    "First, I'll",
    "Now I'll",
]


def is_reasoning_text(text: str) -> bool:
    """Check if text contains internal reasoning that shouldn't be shown to user."""
    text_lower = text.lower()
    for pattern in REASONING_PATTERNS:
        if pattern.lower() in text_lower:
            return True
    return False


class ReasoningFilter:
    """
    Buffers streaming text to detect and filter reasoning patterns.
    Reasoning often spans multiple chunks, so we need to buffer.

    Strategy:
    1. Buffer initial text until we have enough context (50+ chars or sentence end)
    2. If reasoning detected, enter reasoning mode and discard until good marker
    3. If no reasoning, output buffered text and switch to pass-through mode
    """

    def __init__(self):
        self.buffer = ""
        self.in_reasoning_block = False
        self.passed_initial_check = False
        self.min_buffer_size = 50  # Buffer this much before deciding
        self.reasoning_end_markers = ["\n\n📊", "\n\n📈", "\n\nHere's", "\n\nHere is",
                                       "📊", "📈", "**Key", "## ", "### "]

    def process(self, delta: str) -> Optional[str]:
        """
        Process a text delta. Returns filtered text or None if buffering/filtering.
        """
        self.buffer += delta

        # If we're in a reasoning block, check for end markers
        if self.in_reasoning_block:
            for marker in self.reasoning_end_markers:
                if marker in self.buffer:
                    # Found end of reasoning, extract good content after marker
                    idx = self.buffer.find(marker)
                    good_content = self.buffer[idx:]
                    self.buffer = ""
                    self.in_reasoning_block = False
                    self.passed_initial_check = True
                    return good_content
            # Still in reasoning, keep buffering (discard if too long)
            if len(self.buffer) > 1000:
                # Too long, discard reasoning and reset
                self.buffer = ""
                self.in_reasoning_block = False
            return None

        # If we've already passed the initial check, just pass through
        if self.passed_initial_check:
            output = self.buffer
            self.buffer = ""
            return output

        # Initial buffering phase - wait for enough context
        # Check for sentence end or sufficient length
        has_sentence_end = any(marker in self.buffer for marker in [". ", ".\n", "!\n", "?\n"])

        if len(self.buffer) >= self.min_buffer_size or has_sentence_end:
            # Now check if buffer contains reasoning
            if is_reasoning_text(self.buffer):
                self.in_reasoning_block = True
                return None
            else:
                # No reasoning, pass through and mark as checked
                self.passed_initial_check = True
                output = self.buffer
                self.buffer = ""
                return output

        # Still buffering, waiting for more context
        return None

    def flush(self) -> str:
        """Flush remaining buffer at end of stream."""
        if self.in_reasoning_block:
            # Don't output reasoning that was being filtered
            self.buffer = ""
            self.in_reasoning_block = False
            return ""
        output = self.buffer
        self.buffer = ""
        self.in_reasoning_block = False
        return output

    def reset(self):
        """Reset internal buffer and state for a new streaming turn or retry."""
        self.buffer = ""
        self.in_reasoning_block = False
        self.passed_initial_check = False


class ReactStreamingEngine:
    """
    Streaming engine using LangGraph's create_react_agent.
    Handles tool result pairing correctly for Bedrock.
    """

    @classmethod
    async def create_event_stream(
        cls,
        prompt: str,
        user_id: str,
        chat_id: str,
        user_msg_id: int,
        convo_history: Optional[List[BaseMessage]] = None,
        model_name: str = "qwen.qwen3-vl-235b-a22b",
        chat_title: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Create SSE event stream using ReAct agent.

        Args:
            chat_title: Optional title string for context/metrics (omitted from UI stream).
        """
        text_id = f"text_{int(datetime.datetime.now().timestamp() * 1000)}"
        text_started = False
        text_ended = False
        accumulated_tokens: List[str] = []
        functional_tools: List[Dict[str, Any]] = []
        chart_config = None

        # Filter to suppress internal reasoning from being shown to user
        reasoning_filter = ReasoningFilter()

        # Performance metrics
        start_time = datetime.datetime.now()

        try:
            # Chat title is saved in DB and returned in HTTP headers (X-Chat-Title).
            # Avoid emitting non-standard chunks into the x-vercel-ai-ui-message-stream.

            # ====================================================================
            # INPUT GUARDRAILS CHECK
            # ====================================================================
            rail_result = await guardrails_service.check_input_async(
                prompt, convo_history=convo_history
            )

            if not rail_result.passed:
                blocked_response = (
                    rail_result.response
                    or "I can only help with Yamaha plant energy analysis."
                )

                yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': blocked_response})}\n\n"
                yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"

                meta = {
                    "guardrail_blocked": True,
                    "rail_type": rail_result.rail_type.value,
                    "should_log": rail_result.should_log,
                }
                await chat_service.save_assistant_turn_async(
                    chat_id=chat_id,
                    content=blocked_response,
                    model_name=model_name,
                    metadata=meta,
                    user_msg_id=user_msg_id,
                )

                yield "data: [DONE]\n\n"
                return

            # ============================================================
            # FAST PATH: Simple greetings (no LLM call needed)
            # ============================================================
            if is_simple_greeting(prompt):
                ans_text = generate_greeting_response(prompt)

                yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': ans_text})}\n\n"
                yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"

                await chat_service.save_assistant_turn_async(
                    chat_id=chat_id,
                    content=ans_text,
                    model_name="fast_path",
                    metadata={"fast_path": True},
                    user_msg_id=user_msg_id,
                )
                yield "data: [DONE]\n\n"
                return

            # ============================================================
            # STANDARD PATH: ReAct Agent Execution
            # ============================================================

            # Prepare messages with proper ordering and system prompt
            raw_history = list(convo_history) if convo_history else []

            # Add current user message
            raw_history.append(HumanMessage(content=prompt))

            # Prepare messages (adds system prompt, compresses history, ensures pairing)
            messages_to_send = prepare_messages_for_agent(
                messages=raw_history,
                user_query=prompt,
                compress_history=True,
                max_recent=4,
            )

            # Classify intent for logging
            intents, confidence = intent_classifier.classify(prompt)

            # Get ReAct agent
            agent = get_react_agent()
            tracer = LangChainTracer(project_name=settings.LANGCHAIN_PROJECT)

            # Track tool call IDs for matching start/end events
            tool_call_id_map: Dict[str, str] = {}

            # Recursion limit config (prevents infinite loops)
            config = {
                "callbacks": [tracer],
                "recursion_limit": 10,  # Max 10 agent iterations
            }

            # Stream events from ReAct agent
            async for event in agent.astream_events(
                {"messages": messages_to_send},
                version="v2",
                config=config,
            ):
                kind = event["event"]
                name = event.get("name", "")

                # Tool execution events
                if kind == "on_tool_start":
                    t_name = event.get("name", "tool")
                    t_input = event.get("data", {}).get("input", {})
                    langgraph_run_id = event.get("run_id", "")

                    # Generate stable tool call ID and store mapping
                    tool_call_id = (
                        f"call_{t_name}_{int(datetime.datetime.now().timestamp() * 1000)}"
                    )
                    if langgraph_run_id:
                        tool_call_id_map[langgraph_run_id] = tool_call_id

                    # If text was already streamed before this subsequent tool call, cleanly close the text part
                    if text_started:
                        yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"
                        text_id = f"text_{int(datetime.datetime.now().timestamp() * 1000)}"
                        text_started = False

                    yield f"data: {json.dumps({'type': 'tool-input-available', 'toolCallId': tool_call_id, 'toolName': t_name, 'input': t_input})}\n\n"

                elif kind == "on_tool_end":
                    t_name = event.get("name", "tool")
                    t_output_raw = event.get("data", {}).get("output", {})
                    langgraph_run_id = event.get("run_id", "")

                    # Look up the matching tool call ID from on_tool_start
                    tool_call_id = tool_call_id_map.get(
                        langgraph_run_id,
                        f"call_{t_name}_{int(datetime.datetime.now().timestamp() * 1000)}",
                    )

                    # Extract content from ToolMessage if needed
                    if hasattr(t_output_raw, "content"):
                        content = t_output_raw.content
                        try:
                            fmt_output = (
                                json.loads(content)
                                if isinstance(content, str)
                                else content
                            )
                        except (json.JSONDecodeError, TypeError):
                            fmt_output = content
                    elif isinstance(t_output_raw, (dict, list)):
                        fmt_output = t_output_raw
                    elif isinstance(t_output_raw, str):
                        try:
                            fmt_output = json.loads(t_output_raw)
                        except (json.JSONDecodeError, TypeError):
                            fmt_output = t_output_raw
                    else:
                        fmt_output = str(t_output_raw)

                    yield f"data: {json.dumps({'type': 'tool-output-available', 'toolCallId': tool_call_id, 'output': fmt_output})}\n\n"

                    functional_tools.append(
                        {
                            "name": t_name,
                            "input": event.get("data", {}).get("input", {}),
                            "output": fmt_output,
                            "call_id": tool_call_id,
                        }
                    )

                    # Async persist (non-blocking)
                    await chat_service.save_tool_turn_async(
                        chat_id=chat_id,
                        tool_name=t_name,
                        tool_input=event.get("data", {}).get("input", {}),
                        tool_output=fmt_output,
                        tool_call_id=tool_call_id,
                        user_msg_id=user_msg_id,
                    )

                # LLM token stream
                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")

                    # Skip if this is a tool call chunk (not text)
                    if chunk and hasattr(chunk, "tool_calls") and chunk.tool_calls:
                        continue

                    delta = extract_text_delta(chunk)
                    if delta:
                        # Filter out internal reasoning before sending to frontend
                        filtered_delta = reasoning_filter.process(delta)
                        # Always accumulate original for history (includes reasoning for debugging)
                        accumulated_tokens.append(delta)

                        # BUFFERED MODE: Only stream text if we have tool calls
                        # This prevents hallucinated responses from being shown
                        # If no tools called, text will be sent after validation at the end
                        if filtered_delta and functional_tools:
                            if not text_started:
                                yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                                text_started = True
                            yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': filtered_delta})}\n\n"

            # Flush any remaining buffered text from reasoning filter
            remaining = reasoning_filter.flush()
            if remaining:
                accumulated_tokens.append(remaining)
                if functional_tools:
                    if not text_started:
                        yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                        text_started = True
                    yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': remaining})}\n\n"

            # Extract chart config from tools
            if functional_tools:
                extracted = response_formatter.extract_chart_from_tools(functional_tools)
                if extracted:
                    chart_config = extracted

            # Inject chart event if needed
            if chart_config:
                chart_tool_names = {
                    "create_visualization",
                    "create_chart",
                    "aggregate_energy_telemetry",
                    "create_breakdown_chart",
                    "create_time_series_chart",
                    "create_demand_utilization_gauge",
                    "create_gauge_chart",
                    "create_load_heatmap",
                    "create_heatmap_chart",
                    "create_shift_comparison_chart",
                    "create_correlation_scatter_plot",
                    "create_power_quality_chart",
                    "create_specialized_chart",
                    "create_comparison_chart",
                }
                has_chart_event = any(
                    t.get("name") in chart_tool_names for t in functional_tools
                )

                if not has_chart_event:
                    chart_type = (
                        chart_config.get("chart_type", "bar")
                        if isinstance(chart_config, dict)
                        else "bar"
                    )
                    tool_fn = "create_breakdown_chart"
                    if chart_type in ("line", "area", "stacked_area"):
                        tool_fn = "create_time_series_chart"
                    elif chart_type == "gauge":
                        tool_fn = "create_demand_utilization_gauge"
                    elif chart_type == "heatmap":
                        tool_fn = "create_load_heatmap"
                    elif chart_type in ("grouped_bar", "stacked_bar"):
                        tool_fn = "create_shift_comparison_chart"

                    chart_call_id = (
                        f"chart_{int(datetime.datetime.now().timestamp() * 1000)}"
                    )
                    chart_input = {
                        "chart_type": chart_type,
                        "title": (
                            chart_config.get("title", "Energy Visualization")
                            if isinstance(chart_config, dict)
                            else "Energy Visualization"
                        ),
                    }

                    yield f"data: {json.dumps({'type': 'tool-input-available', 'toolCallId': chart_call_id, 'toolName': tool_fn, 'input': chart_input})}\n\n"
                    yield f"data: {json.dumps({'type': 'tool-output-available', 'toolCallId': chart_call_id, 'output': chart_config})}\n\n"

                    await chat_service.save_tool_turn_async(
                        chat_id=chat_id,
                        tool_name=tool_fn,
                        tool_input=chart_input,
                        tool_output=chart_config,
                        tool_call_id=chart_call_id,
                        user_msg_id=user_msg_id,
                    )

            # Calculate performance metrics
            elapsed_ms = (
                datetime.datetime.now() - start_time
            ).total_seconds() * 1000
            cache_stats = tool_cache.stats

            raw_accumulated = "".join(accumulated_tokens)

            # ================================================================
            # OUTPUT GUARDRAILS CHECK
            # ================================================================
            output_rail = await guardrails_service.check_output_async(raw_accumulated)
            full_response_text = output_rail.response if not output_rail.passed else raw_accumulated

            # ================================================================
            # HALLUCINATION DETECTION - Block responses with numbers but no tool calls
            # ================================================================
            from src.agent.hallucination_detector import detect_hallucination

            is_hallucination, hallucination_msg = detect_hallucination(
                response_text=full_response_text,
                tool_calls_this_turn=functional_tools,
                user_query=prompt
            )

            if is_hallucination:
                import logging
                logging.warning(
                    f"[HALLUCINATION DETECTED] Query: {prompt[:100]}... "
                    "Triggering silent auto-retry to force telemetry tool execution."
                )

                # Reset token buffers for the retry (user hasn't received any text yet)
                accumulated_tokens.clear()
                reasoning_filter.reset()

                # Build corrective turn forcing tool call (replacing raw prompt with strict system directive)
                retry_prompt = (
                    f"{prompt}\n\n"
                    f"[SYSTEM DIRECTIVE: You MUST execute the appropriate telemetry tool to answer this query. "
                    f"Never provide numerical energy values from memory or conversation history. "
                    f"If the query asks about equipment categories or breakdown, call grouping_energy(date='2026-10-26', group_by='equipment'). "
                    f"If the query asks about power factor, harmonics/THD, peak demand, or instantaneous readings, call get_instantaneous_energy. "
                    f"If the query asks for a chart or visualization, call create_visualization. "
                    f"If asking about cumulative energy, call get_cummulative_energy. Execute the tool call now.]"
                )
                retry_messages = list(messages_to_send[:-1]) + [HumanMessage(content=retry_prompt)]

                # Run ReAct agent retry turn
                async for event in agent.astream_events(
                    {"messages": retry_messages},
                    version="v2",
                    config=config,
                ):
                    kind = event["event"]

                    if kind == "on_tool_start":
                        t_name = event.get("name", "tool")
                        t_input = event.get("data", {}).get("input", {})
                        langgraph_run_id = event.get("run_id", "")
                        tool_call_id = f"call_{t_name}_{int(datetime.datetime.now().timestamp() * 1000)}"
                        if langgraph_run_id:
                            tool_call_id_map[langgraph_run_id] = tool_call_id

                        # If text was already streamed before this subsequent retry tool call, cleanly close the text part
                        if text_started:
                            yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"
                            text_id = f"text_{int(datetime.datetime.now().timestamp() * 1000)}"
                            text_started = False

                        yield f"data: {json.dumps({'type': 'tool-input-available', 'toolCallId': tool_call_id, 'toolName': t_name, 'input': t_input})}\n\n"

                    elif kind == "on_tool_end":
                        t_name = event.get("name", "tool")
                        t_output_raw = event.get("data", {}).get("output", {})
                        langgraph_run_id = event.get("run_id", "")
                        tool_call_id = tool_call_id_map.get(
                            langgraph_run_id,
                            f"call_{t_name}_{int(datetime.datetime.now().timestamp() * 1000)}",
                        )
                        if hasattr(t_output_raw, "content"):
                            content = t_output_raw.content
                            try:
                                fmt_output = json.loads(content) if isinstance(content, str) else content
                            except (json.JSONDecodeError, TypeError):
                                fmt_output = content
                        elif isinstance(t_output_raw, (dict, list)):
                            fmt_output = t_output_raw
                        elif isinstance(t_output_raw, str):
                            try:
                                fmt_output = json.loads(t_output_raw)
                            except (json.JSONDecodeError, TypeError):
                                fmt_output = t_output_raw
                        else:
                            fmt_output = str(t_output_raw)

                        yield f"data: {json.dumps({'type': 'tool-output-available', 'toolCallId': tool_call_id, 'output': fmt_output})}\n\n"
                        functional_tools.append({
                            "name": t_name,
                            "input": event.get("data", {}).get("input", {}),
                            "output": fmt_output,
                            "call_id": tool_call_id,
                        })
                        await chat_service.save_tool_turn_async(
                            chat_id=chat_id,
                            tool_name=t_name,
                            tool_input=event.get("data", {}).get("input", {}),
                            tool_output=fmt_output,
                            tool_call_id=tool_call_id,
                            user_msg_id=user_msg_id,
                        )

                    elif kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk and hasattr(chunk, "tool_calls") and chunk.tool_calls:
                            continue
                        delta = extract_text_delta(chunk)
                        if delta:
                            filtered_delta = reasoning_filter.process(delta)
                            accumulated_tokens.append(delta)
                            if filtered_delta and functional_tools:
                                if not text_started:
                                    yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                                    text_started = True
                                yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': filtered_delta})}\n\n"

                # Flush reasoning filter on retry
                remaining = reasoning_filter.flush()
                if remaining:
                    accumulated_tokens.append(remaining)
                    if functional_tools:
                        if not text_started:
                            yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                            text_started = True
                        yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': remaining})}\n\n"

                # Extract chart from retry tools if available
                if functional_tools:
                    extracted = response_formatter.extract_chart_from_tools(functional_tools)
                    if extracted:
                        chart_config = extracted

                if functional_tools:
                    raw_accumulated = "".join(accumulated_tokens)
                    full_response_text = raw_accumulated
                    is_hallucination = False  # Cleared after successful tool retry
                else:
                    # Safeguard: if retry still produced ungrounded numbers without tools, do not display them
                    is_retry_hallucination, _ = detect_hallucination(
                        response_text="".join(accumulated_tokens),
                        tool_calls_this_turn=functional_tools,
                        user_query=prompt
                    )
                    if is_retry_hallucination:
                        full_response_text = (
                            "I could not retrieve verified telemetry data from the plant meters for this query. "
                            "Please specify a specific date or meter name so I can fetch live metrics."
                        )
                        is_hallucination = True
                    else:
                        full_response_text = "".join(accumulated_tokens)
                        is_hallucination = False

            # Send buffered or completed text
            if not text_started:
                buffered_text = full_response_text.strip()
                if not buffered_text:
                    buffered_text = "Analysis completed."
                yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': buffered_text})}\n\n"
                yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"
                text_started = True
                text_ended = True
                full_response_text = buffered_text
            elif not text_ended:
                yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"
                text_ended = True

            meta = {
                "chart": chart_config,
                "tools_used": [t.get("name") for t in functional_tools],
                "output_rail_blocked": not output_rail.passed,
                "hallucination_blocked": is_hallucination,
                "performance": {
                    "elapsed_ms": round(elapsed_ms, 1),
                    "cache_hit_rate": cache_stats.get("hit_rate", 0),
                    "intents": [i.value for i in intents],
                },
            }

            await chat_service.save_assistant_turn_async(
                chat_id=chat_id,
                content=full_response_text,
                model_name=model_name,
                metadata=meta,
                user_msg_id=user_msg_id,
            )

        except asyncio.CancelledError:
            await chat_service.record_error_async(
                chat_id, "Client disconnected during streaming.", user_msg_id
            )
            raise
        except Exception as e:
            err_msg = f"Error processing query: {str(e)}"
            if not text_started:
                yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
            yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': err_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"
            await chat_service.record_error_async(chat_id, str(e), user_msg_id)

        # Stream finish
        yield "data: [DONE]\n\n"


# Export streaming engine
streaming_engine = ReactStreamingEngine()
