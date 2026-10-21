"""
LangGraph Typed State Definition
Defines state schema for multi-turn execution, tool auditing, and response formatting.
"""

from typing import Annotated, Any, Dict, List, Optional, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from src.schemas.chat import AssistantResponse

class AgentState(BaseModel):
    """Execution state passed through the LangGraph workflow."""
    messages: Annotated[Sequence[BaseMessage], add_messages] = Field(default_factory=list)
    user_id: str = "default_user"
    chat_id: str = "default_chat"
    
    # Workflow routing indicators
    is_security_refusal: bool = False
    is_greeting: bool = False
    is_clarification: bool = False
    is_out_of_domain: bool = False
    loop_count: int = 0
    
    # Tool tracking & outputs
    executed_tools: List[Dict[str, Any]] = Field(default_factory=list)
    structured_response: Optional[AssistantResponse] = None
    error: Optional[str] = None
