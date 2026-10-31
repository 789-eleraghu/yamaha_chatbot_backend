"""
Application Settings & Environment Configuration
"""

import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Environment
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")

    # Database - ClickHouse (Telemetry)
    CLICKHOUSE_HOST: str = Field(default="localhost")
    CLICKHOUSE_PORT: int = Field(default=8123)
    CLICKHOUSE_DATABASE: str = Field(default="yamaha")
    CLICKHOUSE_USER: str = Field(default="default")
    CLICKHOUSE_PASSWORD: str = Field(default="")

    # Database - PostgreSQL (Chat Management)
    POSTGRES_HOST: str = Field(default="localhost")
    POSTGRES_PORT: int = Field(default=5432)
    POSTGRES_DATABASE: str = Field(default="yamaha")
    POSTGRES_USER: str = Field(default="chat_app_user")
    POSTGRES_PASSWORD: str = Field(default="")

    # JWT Authentication
    JWT_SECRET_KEY: str = Field(default="yamaha-energy-assistant-dev-secret-key-2024")
    JWT_ALGORITHM: str = Field(default="HS256")
    JWT_EXPIRY_DAYS: int = Field(default=365)  # Long expiry for development

    # LLM Settings (AWS Bedrock / Qwen / OpenAI compatible)
    LLM_PROVIDER: str = Field(default="bedrock")  # 'bedrock', 'openai', 'qwen'
    
    # AWS Bedrock
    AWS_REGION: str = Field(default="ap-south-1")
    AWS_ACCESS_KEY_ID: str = Field(default="")
    AWS_SECRET_ACCESS_KEY: str = Field(default="")
    AWS_SESSION_TOKEN: str = Field(default="")
    AWS_BEARER_TOKEN: str = Field(default="")
    BEDROCK_MODEL_ID: str = Field(default="qwen.qwen3-vl-235b-a22b")
    
    # OpenAI / Qwen3 / Third-Party OpenAI-compatible endpoints
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_BASE_URL: str = Field(default="")
    OPENAI_MODEL_NAME: str = Field(default="Qwen/Qwen3-235B-A22B-2507")

    # Inference hyperparams
    TEMPERATURE: float = Field(default=0.0)
    MAX_TOKENS: int = Field(default=4096)

    # Reference doc path for RAG
    REFERENCE_DOC_PATH: str = Field(default="energy-ai-assistant-reference.md")

    # LangSmith / LangChain Observability
    LANGCHAIN_TRACING_V2: bool = Field(default=True)
    LANGCHAIN_PROJECT: str = Field(default="yamaha-energy-chatbot")
    LANGCHAIN_API_KEY: str = Field(default="")
    LANGCHAIN_ENDPOINT: str = Field(default="https://api.smith.langchain.com")

settings = Settings()

# Ensure LangSmith environment variables are propagated into os.environ for LangChain tracer
if settings.LANGCHAIN_TRACING_V2 and settings.LANGCHAIN_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = settings.LANGCHAIN_PROJECT
    os.environ["LANGCHAIN_API_KEY"] = settings.LANGCHAIN_API_KEY
    os.environ["LANGCHAIN_ENDPOINT"] = settings.LANGCHAIN_ENDPOINT
