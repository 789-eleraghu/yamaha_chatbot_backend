"""
Chat Endpoints
"""

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from src.agent.graph import build_agent_graph
from src.schemas.chat import ChatRequest, ChatResponse, AssistantResponse

router = APIRouter(tags=["Chat"])

# Lazy graph compilation
_agent_app = None

def get_agent():
    global _agent_app
    if _agent_app is None:
        _agent_app = build_agent_graph()
    return _agent_app

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Process natural language queries using the LangGraph agent.
    Returns markdown answer, key numerical metrics, and structured chart configs.
    """
    try:
        agent = get_agent()
        initial_state = {
            "messages": [HumanMessage(content=request.message)],
            "structured_response": None
        }
        final_state = agent.invoke(initial_state)

        structured_res = final_state.get("structured_response")
        if not structured_res:
            # Fallback if format_response was bypassed
            last_msg = final_state["messages"][-1].content
            structured_res = AssistantResponse(
                answer_markdown=str(last_msg),
                key_metrics={},
                chart=None
            )

        return ChatResponse(
            session_id=request.session_id,
            response=structured_res
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent Error: {str(e)}")
