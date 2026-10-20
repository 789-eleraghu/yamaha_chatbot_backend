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

    # Database
    DB_TYPE: str = Field(default="sqlite")  # 'sqlite' or 'clickhouse'
    SQLITE_DB_PATH: str = Field(default="yamaha_mock.db")

    CLICKHOUSE_HOST: str = Field(default="localhost")
    CLICKHOUSE_PORT: int = Field(default=8123)
    CLICKHOUSE_DATABASE: str = Field(default="yamaha")
    CLICKHOUSE_USER: str = Field(default="default")
    CLICKHOUSE_PASSWORD: str = Field(default="")

    # LLM Settings (AWS Bedrock / Qwen / OpenAI compatible)
    LLM_PROVIDER: str = Field(default="bedrock")  # 'bedrock', 'openai', 'qwen'
    
    # AWS Bedrock
    AWS_REGION: str = Field(default="us-east-1")
    AWS_ACCESS_KEY_ID: str = Field(default="")
    AWS_SECRET_ACCESS_KEY: str = Field(default="")
    AWS_SESSION_TOKEN: str = Field(default="")
    BEDROCK_MODEL_ID: str = Field(default="anthropic.claude-3-5-sonnet-20241022-v2:0")
    
    # OpenAI / Qwen3 / Third-Party OpenAI-compatible endpoints
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_BASE_URL: str = Field(default="")
    OPENAI_MODEL_NAME: str = Field(default="Qwen/Qwen3-235B-A22B-2507")

    # Inference hyperparams
    TEMPERATURE: float = Field(default=0.0)
    MAX_TOKENS: int = Field(default=4096)

    # Reference doc path for RAG
    REFERENCE_DOC_PATH: str = Field(default="energy-ai-assistant-reference.md")

settings = Settings()
