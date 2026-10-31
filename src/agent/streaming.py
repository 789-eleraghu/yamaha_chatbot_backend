"""
Streaming Protocol Engine for assistant-ui & Vercel AI SDK
Streams genuine tokens and tool lifecycle events directly from LangGraph.
Integrates NeMo-style guardrails for input/output filtering.
"""

import asyncio
import datetime
import json
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tracers import LangChainTracer
from src.agent.graph import get_agent_graph
from src.agent.response_formatter import response_formatter
from src.core.config import settings
from src.schemas.chat import AssistantResponse
from src.services.chat_service import chat_service
from src.guardrails import guardrails_service, GuardrailsResult
from src.guardrails.guardrails_service import RailType

SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "x-vercel-ai-ui-message-stream": "v1",
    "X-Accel-Buffering": "no",
}

def extract_text_delta(chunk: Any) -> Optional[str]:
    """Extract text delta from Bedrock Converse or LangChain chunk formats."""
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

class StreamingEngine:
    """Streams genuine tool lifecycle events and text tokens to client via SSE."""

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
        **kwargs
    ) -> AsyncGenerator[str, None]:
        text_id = f"text_{int(datetime.datetime.now().timestamp() * 1000)}"
        text_started = False
        text_ended = False
        accumulated_tokens: List[str] = []
        functional_tools: List[Dict[str, Any]] = []
        last_structured_response: Optional[AssistantResponse] = None
        chart_config = None

        # Chat title is saved in DB and returned in HTTP headers (X-Chat-Title).
        # Avoid emitting non-standard chunks into the x-vercel-ai-ui-message-stream.

        # ====================================================================
        # INPUT GUARDRAILS CHECK (Jailbreak, Topic)
        # Runs BEFORE LangGraph execution - blocks with fixed response if needed
        # ====================================================================
        rail_result = await guardrails_service.check_input_async(prompt, convo_history=convo_history)

        if not rail_result.passed:
            # Guardrail blocked - return fixed response without LLM
            blocked_response = rail_result.response or "I can only help with Yamaha plant energy analysis."

            yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
            yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': blocked_response})}\n\n"
            yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"

            # Save blocked response to chat history
            meta = {
                "guardrail_blocked": True,
                "rail_type": rail_result.rail_type.value,
                "should_log": rail_result.should_log
            }
            await chat_service.save_assistant_turn_async(
                chat_id=chat_id,
                content=blocked_response,
                model_name=model_name,
                metadata=meta,
                user_msg_id=user_msg_id
            )

            yield "data: [DONE]\n\n"
            return

        try:
            # Prepare state with full multi-turn conversation context
            messages_to_send = list(convo_history) if convo_history else []
            if not messages_to_send or getattr(messages_to_send[-1], "content", None) != prompt:
                messages_to_send.append(HumanMessage(content=prompt))

            initial_state = {
                "messages": messages_to_send,
                "user_id": user_id,
                "chat_id": chat_id,
                "is_security_refusal": False,
                "is_greeting": False,
                "is_clarification": False,
                "is_out_of_domain": False,
                "loop_count": 0,
                "executed_tools": [],
                "structured_response": None,
                "error": None
            }

            graph = get_agent_graph()
            tracer = LangChainTracer(project_name=settings.LANGCHAIN_PROJECT)

            # Track tool call IDs to ensure input/output events match
            tool_call_id_map: Dict[str, str] = {}

            # Stream real-time events from LangGraph execution
            async for event in graph.astream_events(initial_state, version="v2", config={"callbacks": [tracer]}):
                kind = event["event"]
                name = event.get("name", "")

                # 1. Guardrail & Fast-Exit Interception (Greeting, Clarification, Prompt Leak, Out of Domain)
                if kind == "on_chain_end" and name == "guardrail_and_intent":
                    output = event.get("data", {}).get("output", {})
                    if (
                        output.get("is_greeting")
                        or output.get("is_security_refusal")
                        or output.get("is_clarification")
                        or output.get("is_out_of_domain")
                    ):
                        structured = output.get("structured_response")
                        last_structured_response = structured
                        ans_text = structured.answer_markdown if structured else "Analysis completed."

                        yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                        text_started = True
                        yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': ans_text})}\n\n"
                        accumulated_tokens.append(ans_text)
                        yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"
                        text_ended = True

                # 2. Tool Execution Start Event
                elif kind == "on_tool_start":
                    t_name = event.get("name", "tool")
                    t_input = event.get("data", {}).get("input", {})
                    langgraph_run_id = event.get("run_id", "")

                    # Generate stable tool call ID and store mapping
                    tool_call_id = f"call_{t_name}_{int(datetime.datetime.now().timestamp() * 1000)}"
                    if langgraph_run_id:
                        tool_call_id_map[langgraph_run_id] = tool_call_id

                    yield f"data: {json.dumps({'type': 'tool-input-available', 'toolCallId': tool_call_id, 'toolName': t_name, 'input': t_input})}\n\n"

                # 3. Tool Execution End Event
                elif kind == "on_tool_end":
                    t_name = event.get("name", "tool")
                    t_output_raw = event.get("data", {}).get("output", {})
                    langgraph_run_id = event.get("run_id", "")

                    # Look up the matching tool call ID from on_tool_start
                    tool_call_id = tool_call_id_map.get(langgraph_run_id, f"call_{t_name}_{int(datetime.datetime.now().timestamp() * 1000)}")

                    # Extract content from ToolMessage if needed (LangGraph ToolNode returns ToolMessage)
                    if hasattr(t_output_raw, "content"):
                        # It's a ToolMessage - extract and parse its content
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
                        "call_id": tool_call_id
                    })
                    # Asynchronously persist tool turn (non-blocking)
                    await chat_service.save_tool_turn_async(
                        chat_id=chat_id,
                        tool_name=t_name,
                        tool_input=event.get("data", {}).get("input", {}),
                        tool_output=fmt_output,
                        tool_call_id=tool_call_id,
                        user_msg_id=user_msg_id
                    )

                # 4. Genuine LLM Token Stream
                elif kind == "on_chat_model_stream":
                    delta = extract_text_delta(event.get("data", {}).get("chunk"))
                    if delta:
                        if not text_started:
                            yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                            text_started = True
                        yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': delta})}\n\n"
                        accumulated_tokens.append(delta)

                # 5. Graph Completion Capture
                elif kind == "on_chain_end" and name in ("format_response", "LangGraph"):
                    chain_output = event.get("data", {}).get("output", {})
                    if chain_output and isinstance(chain_output, dict):
                        if chain_output.get("structured_response"):
                            last_structured_response = chain_output.get("structured_response")
                        if chain_output.get("executed_tools") and not functional_tools:
                            functional_tools = chain_output.get("executed_tools")

            # Chart Visualization Injection for Assistant-UI
            if last_structured_response:
                chart_raw = getattr(last_structured_response, "chart", None)
                if chart_raw:
                    chart_config = chart_raw.model_dump() if hasattr(chart_raw, "model_dump") else chart_raw
            if not chart_config and functional_tools:
                extracted = response_formatter.extract_chart_from_tools(functional_tools)
                if extracted:
                    chart_config = extracted

            if chart_config:
                has_chart_event = any(t.get("name") in (
                    "create_visualization",
                    "create_chart",
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
                    "aggregate_energy_telemetry"
                ) for t in functional_tools)

                if not has_chart_event:
                    chart_type = chart_config.get("chart_type", "bar") if isinstance(chart_config, dict) else "bar"
                    tool_fn = "create_breakdown_chart"
                    if chart_type in ("line", "area", "stacked_area"):
                        tool_fn = "create_time_series_chart"
                    elif chart_type == "gauge":
                        tool_fn = "create_demand_utilization_gauge"
                    elif chart_type == "heatmap":
                        tool_fn = "create_load_heatmap"
                    elif chart_type in ("grouped_bar", "stacked_bar"):
                        tool_fn = "create_shift_comparison_chart"

                    chart_call_id = f"chart_{int(datetime.datetime.now().timestamp() * 1000)}"
                    chart_input = {
                        "chart_type": chart_type,
                        "title": chart_config.get("title", "Energy Visualization") if isinstance(chart_config, dict) else "Energy Visualization"
                    }
                    yield f"data: {json.dumps({'type': 'tool-input-available', 'toolCallId': chart_call_id, 'toolName': tool_fn, 'input': chart_input})}\n\n"
                    yield f"data: {json.dumps({'type': 'tool-output-available', 'toolCallId': chart_call_id, 'output': chart_config})}\n\n"
                    await chat_service.save_tool_turn_async(
                        chat_id=chat_id,
                        tool_name=tool_fn,
                        tool_input=chart_input,
                        tool_output=chart_config,
                        tool_call_id=chart_call_id,
                        user_msg_id=user_msg_id
                    )

            # Ensure text lifecycle is cleanly closed
            if not text_started:
                fallback_text = (
                    last_structured_response.answer_markdown
                    if last_structured_response and getattr(last_structured_response, "answer_markdown", None)
                    else "Analysis completed."
                )
                yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
                yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': fallback_text})}\n\n"
                yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"
                accumulated_tokens.append(fallback_text)
                text_ended = True
            elif not text_ended:
                yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"
                text_ended = True

            # ================================================================
            # OUTPUT GUARDRAILS CHECK (Prompt Leak Detection)
            # Runs AFTER LLM generation - blocks if response contains leaks
            # ================================================================
            full_response_text = "".join(accumulated_tokens)

            output_rail = await guardrails_service.check_output_async(full_response_text)
            if not output_rail.passed:
                # Output blocked - this is rare but possible
                # In streaming, we can't unsend tokens, but we log and replace for persistence
                full_response_text = output_rail.response or "Analysis completed."

            # Save assistant turn to database asynchronously
            meta = {
                "key_metrics": getattr(last_structured_response, "key_metrics", {}) if last_structured_response else {},
                "chart": chart_config,
                "data_quality_notes": getattr(last_structured_response, "data_quality_notes", None) if last_structured_response else None,
                "tools_used": [t.get("name") for t in functional_tools],
                "output_rail_blocked": not output_rail.passed
            }
            await chat_service.save_assistant_turn_async(
                chat_id=chat_id,
                content=full_response_text,
                model_name=model_name,
                metadata=meta,
                user_msg_id=user_msg_id
            )

        except asyncio.CancelledError:
            await chat_service.record_error_async(chat_id, "Client disconnected during streaming.", user_msg_id)
            raise
        except Exception as e:
            err_msg = f"Error processing query: {str(e)}"
            if not text_started:
                yield f"data: {json.dumps({'type': 'text-start', 'id': text_id})}\n\n"
            yield f"data: {json.dumps({'type': 'text-delta', 'id': text_id, 'delta': err_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'text-end', 'id': text_id})}\n\n"
            await chat_service.record_error_async(chat_id, str(e), user_msg_id)

        # Stream Finish Terminator
        yield "data: [DONE]\n\n"

streaming_engine = StreamingEngine()
