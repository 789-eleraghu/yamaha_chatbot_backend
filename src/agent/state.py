"""
LangGraph State Schema
"""

from typing import Annotated, Any, Dict, List, Optional, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from src.schemas.chat import AssistantResponse

class AgentState(BaseModel):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    structured_response: Optional[AssistantResponse] = None
