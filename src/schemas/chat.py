"""
Chat & Assistant Schemas
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator
from src.schemas.charts import ChartConfig

class ChatRequest(BaseModel):
    message: str = Field(description="User natural language question or instruction")
    session_id: Optional[str] = Field(default="default-session", description="Unique conversation session identifier")

class AssistantResponse(BaseModel):
    answer_markdown: str = Field(
        description="Detailed, human-readable response formatted in Markdown, with calculations, explanations, and insights"
    )
    key_metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Key numerical results extracted from calculations (e.g. {'total_kwh': 41548.1, 'cost_inr': 332676.55})"
    )
    chart: Optional[ChartConfig] = Field(
        default=None,
        description="Optional structured chart configuration if the response benefits from visual representation"
    )
    data_quality_notes: Optional[str] = Field(
        default=None,
        description="Explanations of any data gaps, exclusions, sensor anomalies, or missing data (null)"
    )

    @field_validator("chart", mode="before")
    @classmethod
    def clean_chart(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, dict):
            if not v or not v.get("chart_type"):
                return None
        return v

class ChatResponse(BaseModel):
    session_id: str
    response: AssistantResponse
