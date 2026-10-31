"""
Healthcheck Endpoints
"""

from fastapi import APIRouter
from src.core.config import settings
from src.db.client import db_client
from src.db.postgres_client import pg_client

router = APIRouter(tags=["Health"])

@router.get("/health")
def health_check():
    """Check API and database health status."""
    # Check ClickHouse (Telemetry)
    clickhouse_status = "healthy"
    try:
        rows = db_client.execute_query("SELECT 1 AS ok;")
        if not rows or rows[0]["ok"] != 1:
            clickhouse_status = "degraded"
    except Exception as e:
        clickhouse_status = f"unhealthy: {str(e)[:50]}"

    # Check PostgreSQL (Chat Management)
    postgres_status = "healthy"
    try:
        if pg_client.test_connection():
            postgres_status = "healthy"
        else:
            postgres_status = "degraded"
    except Exception as e:
        postgres_status = f"unhealthy: {str(e)[:50]}"

    overall_status = "healthy"
    if "unhealthy" in clickhouse_status or "unhealthy" in postgres_status:
        overall_status = "unhealthy"
    elif "degraded" in clickhouse_status or "degraded" in postgres_status:
        overall_status = "degraded"

    return {
        "status": overall_status,
        "environment": settings.ENVIRONMENT,
        "database_status": clickhouse_status,
        "database_type": "clickhouse",
        "databases": {
            "clickhouse": {
                "status": clickhouse_status,
                "purpose": "telemetry"
            },
            "postgresql": {
                "status": postgres_status,
                "purpose": "chat_management"
            }
        },
        "llm_provider": settings.LLM_PROVIDER,
        "model_id": settings.BEDROCK_MODEL_ID if settings.LLM_PROVIDER == "bedrock" else settings.OPENAI_MODEL_NAME,
    }
