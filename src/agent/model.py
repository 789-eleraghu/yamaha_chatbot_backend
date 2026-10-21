"""
LLM Model Factory
Instantiates Bedrock Claude, Qwen3, or OpenAI-compatible models
"""

import os
from langchain_core.language_models.chat_models import BaseChatModel
from src.core.config import settings

def get_llm() -> BaseChatModel:
    """Return the configured LLM client."""
    provider = settings.LLM_PROVIDER.lower()

    if provider == "bedrock":
        from langchain_aws import ChatBedrockConverse

        if settings.AWS_BEARER_TOKEN:
            import boto3
            boto3_client = boto3.client(
                "bedrock-runtime",
                region_name=settings.AWS_REGION,
                aws_access_key_id="",
                aws_secret_access_key="",
            )

            token = settings.AWS_BEARER_TOKEN
            def add_bearer_header(request, **kwargs):
                request.headers["Authorization"] = f"Bearer {token}"

            boto3_client.meta.events.register("before-send.bedrock-runtime.Converse", add_bearer_header)
            boto3_client.meta.events.register("before-send.bedrock-runtime.ConverseStream", add_bearer_header)

            return ChatBedrockConverse(
                client=boto3_client,
                model=settings.BEDROCK_MODEL_ID,
                region_name=settings.AWS_REGION,
                temperature=settings.TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
            )

        return ChatBedrockConverse(
            model=settings.BEDROCK_MODEL_ID,
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY or None,
            aws_session_token=settings.AWS_SESSION_TOKEN or None,
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )

    elif provider in ("qwen", "openai"):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=settings.OPENAI_MODEL_NAME,
            base_url=settings.OPENAI_BASE_URL or None,
            api_key=settings.OPENAI_API_KEY or "dummy_key",
            temperature=settings.TEMPERATURE,
            max_tokens=settings.MAX_TOKENS,
        )

    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {settings.LLM_PROVIDER}")
