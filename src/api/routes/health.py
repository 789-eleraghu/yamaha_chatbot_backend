"""
Healthcheck Endpoints
"""

from fastapi import APIRouter
from src.core.config import settings
from src.db.sqlite_client import db_client

router = APIRouter(tags=["Health"])

@router.get("/health")
def health_check():
    """Check API and database health status."""
    db_status = "healthy"
    try:
        rows = db_client.execute_query("SELECT 1 AS ok;")
        if not rows or rows[0]["ok"] != 1:
            db_status = "degraded"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "environment": settings.ENVIRONMENT,
        "database_type": settings.DB_TYPE,
        "database_status": db_status,
        "llm_provider": settings.LLM_PROVIDER,
        "bedrock_model_id": settings.BEDROCK_MODEL_ID if settings.LLM_PROVIDER == "bedrock" else settings.OPENAI_MODEL_NAME,
    }
