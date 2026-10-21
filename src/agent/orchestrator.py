"""
Conversation Orchestrator
Coordinates conversation context, LangSmith tracing, and LangGraph execution.
"""

from typing import Any, Dict, List, Optional
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tracers import LangChainTracer
from langsmith import traceable
from src.agent.graph import get_agent_graph
from src.agent.response_formatter import response_formatter
from src.core.config import settings
from src.schemas.chat import AssistantResponse

class ConversationOrchestrator:
    """Orchestrates LangGraph agent execution."""

    @classmethod
    @traceable(name="Yamaha EMS Assistant Run", project_name=settings.LANGCHAIN_PROJECT)
    async def run(
        cls,
        prompt: str,
        user_id: str,
        chat_id: str,
        conversation_history: Optional[List[BaseMessage]] = None
    ) -> Dict[str, Any]:
        """
        Execute the conversation through LangGraph with full multi-turn context.
        """
        history = list(conversation_history) if conversation_history else []
        messages_to_send = list(history)
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

        try:
            graph = get_agent_graph()
            tracer = LangChainTracer(project_name=settings.LANGCHAIN_PROJECT)
            state = await graph.ainvoke(initial_state, config={"callbacks": [tracer]})

            # Fast exit for guardrail, greeting, clarification, or out-of-domain
            if (
                state.get("is_security_refusal")
                or state.get("is_greeting")
                or state.get("is_clarification")
                or state.get("is_out_of_domain")
            ):
                structured: Optional[AssistantResponse] = state.get("structured_response")
                ans_text = structured.answer_markdown if structured else "Analysis completed."
                return {
                    "all_tools": [],
                    "tool_name": "direct_response",
                    "tool_input": {},
                    "tool_output": {},
                    "answer_markdown": ans_text,
                    "key_metrics": {},
                    "chart": None,
                    "data_quality_notes": None,
                    "structured_response": structured
                }

            executed_tools = state.get("executed_tools", [])
            structured: Optional[AssistantResponse] = state.get("structured_response")

            # Extract answer text from the graph execution
            last_msg = state.get("messages", [])[-1] if state.get("messages") else None
            text = ""
            if structured and getattr(structured, "answer_markdown", None):
                text = structured.answer_markdown
            elif last_msg and hasattr(last_msg, "content"):
                if isinstance(last_msg.content, str):
                    text = last_msg.content
                elif isinstance(last_msg.content, list):
                    text = " ".join([p.get("text", "") for p in last_msg.content if isinstance(p, dict) and p.get("type") == "text"])

            if not text:
                text = "Analysis completed."

            structured_resp = response_formatter.build_assistant_response(
                answer_markdown=str(text),
                executed_tools=executed_tools,
                structured_response=structured
            )
            return {
                "all_tools": executed_tools,
                "tool_name": executed_tools[0]["name"] if executed_tools else "direct_response",
                "tool_input": executed_tools[0].get("input", {}) if executed_tools else {},
                "tool_output": executed_tools[0].get("output", {}) if executed_tools else {},
                "answer_markdown": structured_resp.answer_markdown,
                "key_metrics": structured_resp.key_metrics,
                "chart": structured_resp.chart.model_dump() if hasattr(structured_resp.chart, "model_dump") else structured_resp.chart,
                "data_quality_notes": structured_resp.data_quality_notes,
                "structured_response": structured_resp
            }
        except Exception as e:
            import traceback
            print(f"[Orchestrator LangGraph execution error]: {e}")
            traceback.print_exc()
            return {
                "all_tools": [],
                "tool_name": "error",
                "tool_input": {},
                "tool_output": {"error": str(e)},
                "answer_markdown": f"An error occurred while analyzing telemetry: {str(e)}",
                "key_metrics": {},
                "chart": None,
                "data_quality_notes": f"System error: {str(e)}",
                "structured_response": None
            }

orchestrator = ConversationOrchestrator()
