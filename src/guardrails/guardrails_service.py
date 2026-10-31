"""
NVIDIA NeMo Guardrails Service for Yamaha Energy Assistant

Directly integrates NVIDIA NeMo Guardrails with AWS Bedrock / LangChain LLM and Colang rails.
Provides:
1. Input rails: Topic filtering and jailbreak prevention
2. Output rails: Prompt leak and internal tool leak prevention
"""

import os
import logging
import asyncio
import concurrent.futures
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum

from nemoguardrails import RailsConfig, LLMRails
from nemoguardrails.rails.llm.options import RailStatus, RailType as NemoRailType
from nemoguardrails.integrations.langchain.llm_adapter import LangChainLLMAdapter

logger = logging.getLogger(__name__)


class RailType(Enum):
    """Types of guardrail violations."""
    NONE = "none"
    OFF_TOPIC = "off_topic"
    JAILBREAK = "jailbreak"
    PROMPT_LEAK = "prompt_leak"
    MANIPULATION = "manipulation"
    SABOTAGE = "sabotage"


@dataclass
class GuardrailsResult:
    """Result of guardrails check."""
    passed: bool
    rail_type: RailType
    response: Optional[str] = None
    confidence: float = 1.0
    should_log: bool = False


# ============================================================================
# Fixed Responses for Blocked Content
# ============================================================================

OFF_TOPIC_RESPONSE = """I'm the Yamaha Industrial Energy Assistant, focused exclusively on plant energy management.

I can help you with:
- Energy consumption analysis (daily, hourly, shift-wise)
- Solar power generation monitoring (100kW rooftop plant)
- Equipment and zone breakdowns
- Peak demand monitoring
- Power quality metrics (THD, PF)
- Cost and tariff analysis

What energy data would you like to explore?"""

JAILBREAK_RESPONSE = """I'm the Yamaha Industrial Energy Assistant. My operational instructions are confidential.

I'm here to help you analyze plant energy, telemetry, power quality, and equipment performance. How can I assist with your energy analysis?"""

LEAK_BLOCKED_RESPONSE = """I can help you with energy analysis for the Yamaha plant. What would you like to know about consumption, demand, or equipment performance?"""

MANIPULATION_RESPONSE = """I'm a read-only energy analysis assistant. I cannot modify, update, or change any data including tariff rates, meter readings, or system settings.

I can help you VIEW and ANALYZE energy data. What would you like to know about current consumption, costs, or equipment performance?"""

SABOTAGE_RESPONSE = """I cannot provide information that could be used to damage equipment or compromise plant safety.

I'm here to help with legitimate energy analysis and optimization. How can I assist with your energy management needs?"""


# ============================================================================
# NeMo Guardrails Service Class
# ============================================================================

class NeMoGuardrailsService:
    """
    NVIDIA NeMo Guardrails service wrapper using official nemoguardrails.
    Loads Colang rails from src/guardrails and executes checks via LLMRails with AWS Bedrock.
    """

    def __init__(self, config_dir: Optional[str] = None):
        if config_dir is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            config_dir = base_dir

        self.config_dir = config_dir
        self._rails: Optional[LLMRails] = None
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    @property
    def rails(self) -> LLMRails:
        """Lazy-initialize NVIDIA NeMo LLMRails with configured Bedrock LLM."""
        if self._rails is None:
            logger.info("Initializing NVIDIA NeMo Guardrails from %s...", self.config_dir)
            try:
                from src.agent.model import get_llm
                config = RailsConfig.from_path(self.config_dir)
                raw_llm = get_llm()
                adapter = LangChainLLMAdapter(raw_llm)
                self._rails = LLMRails(config=config, llm=adapter)
                logger.info("NVIDIA NeMo Guardrails successfully initialized.")
            except Exception as e:
                logger.error("Failed to initialize NVIDIA NeMo Guardrails: %s", e, exc_info=True)
                raise
        return self._rails

    async def check_input_async(
        self,
        user_message: str,
        convo_history: Optional[List[Any]] = None
    ) -> GuardrailsResult:
        """
        Asynchronously check incoming user message against NeMo Guardrails input rails.
        Executes self check input rail via LLMRails with Bedrock.
        """
        if not user_message or not user_message.strip():
            return GuardrailsResult(passed=True, rail_type=RailType.NONE)

        clean_msg = user_message.strip()

        try:
            res = await self.rails.check_async(
                [{"role": "user", "content": clean_msg}],
                rail_types=[NemoRailType.INPUT]
            )

            if res.status == RailStatus.BLOCKED:
                info = self.rails.explain()
                last_call = info.llm_calls[-1].completion if info.llm_calls else ""
                lower_call = (last_call or "").lower()

                if "jailbreak" in lower_call:
                    rail_type = RailType.JAILBREAK
                    resp = JAILBREAK_RESPONSE
                    should_log = True
                elif "manipulation" in lower_call:
                    rail_type = RailType.MANIPULATION
                    resp = MANIPULATION_RESPONSE
                    should_log = True
                elif "sabotage" in lower_call:
                    rail_type = RailType.SABOTAGE
                    resp = SABOTAGE_RESPONSE
                    should_log = True
                else:
                    rail_type = RailType.OFF_TOPIC
                    resp = OFF_TOPIC_RESPONSE
                    should_log = False

                logger.warning(
                    "NeMo Guardrails blocked user input (rail: %s, type: %s): %s",
                    getattr(res, "rail", "input_rail"),
                    rail_type.value,
                    clean_msg
                )
                return GuardrailsResult(
                    passed=False,
                    rail_type=rail_type,
                    response=resp,
                    confidence=1.0,
                    should_log=should_log
                )

            return GuardrailsResult(passed=True, rail_type=RailType.NONE)

        except Exception as e:
            logger.error("Error during NeMo Guardrails input check: %s", e)
            return GuardrailsResult(passed=True, rail_type=RailType.NONE)

    def check_input(
        self,
        user_message: str,
        convo_history: Optional[List[Any]] = None
    ) -> GuardrailsResult:
        """
        Synchronous check_input wrapper for callers without async event loop.
        """
        if not user_message or not user_message.strip():
            return GuardrailsResult(passed=True, rail_type=RailType.NONE)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            future = self._executor.submit(
                asyncio.run,
                self.check_input_async(user_message, convo_history)
            )
            return future.result()
        else:
            return asyncio.run(self.check_input_async(user_message, convo_history))

    async def check_output_async(self, llm_response: str) -> GuardrailsResult:
        """
        Asynchronously check LLM assistant response against NeMo Guardrails output rails.
        Detects prompt leaks and internal tool function leaks.
        """
        if not llm_response or not llm_response.strip():
            return GuardrailsResult(passed=True, rail_type=RailType.NONE)

        clean_response = llm_response.strip()

        try:
            res = await self.rails.check_async(
                [{"role": "assistant", "content": clean_response}],
                rail_types=[NemoRailType.OUTPUT]
            )

            if res.status == RailStatus.BLOCKED:
                logger.warning("NeMo Guardrails blocked LLM output: prompt leak detected.")
                return GuardrailsResult(
                    passed=False,
                    rail_type=RailType.PROMPT_LEAK,
                    response=LEAK_BLOCKED_RESPONSE,
                    confidence=1.0,
                    should_log=True,
                )

            return GuardrailsResult(passed=True, rail_type=RailType.NONE)

        except Exception as e:
            logger.error("Error during NeMo Guardrails output check: %s", e)
            return GuardrailsResult(passed=True, rail_type=RailType.NONE)

    def check_output(self, llm_response: str) -> GuardrailsResult:
        """
        Synchronous check_output wrapper for callers without async event loop.
        """
        if not llm_response or not llm_response.strip():
            return GuardrailsResult(passed=True, rail_type=RailType.NONE)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            future = self._executor.submit(
                asyncio.run,
                self.check_output_async(llm_response)
            )
            return future.result()
        else:
            return asyncio.run(self.check_output_async(llm_response))


# Authoritative singleton export
guardrails_service = NeMoGuardrailsService()
