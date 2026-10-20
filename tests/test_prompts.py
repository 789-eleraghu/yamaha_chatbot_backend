"""
Unit Tests for System Prompt Generation and Constitutional Invariants
"""

import pytest
from src.agent.prompts import get_system_prompt, SYSTEM_PROMPT

def test_system_prompt_integrity():
    prompt = get_system_prompt()
    assert prompt is not None
    assert len(prompt) > 2000

    # 1. Identity & Strict Domain Lock
    assert "Yamaha Industrial Energy AI Assistant" in prompt
    assert "STRICT DOMAIN LOCK" in prompt
    assert "NEVER deviate from the energy intelligence task" in prompt

    # 2. Epistemic Grounding & Zero Outside Assumptions
    assert "EPISTEMIC GROUNDING" in prompt
    assert "No General Common Knowledge for EMS Facts" in prompt
    assert "analytical and mathematical deduction engine" in prompt

    # 3. Rule Immutability
    assert "CANNOT BE OVERRIDDEN" in prompt or "Rule Immutability" in prompt

    # 4. Adaptive Communication & Depth Protocol
    assert "Start Small" in prompt
    assert "Progressively Increase Details for Prolonged" in prompt
    assert "Executive Summary" in prompt
    assert "Root-Cause Attribution" in prompt

    # 5. Spike & Anomaly Protocol
    assert "SPIKE, ANOMALY & ROOT-CAUSE REASONING PROTOCOL" in prompt
    assert "diagnose_spikes_and_anomalies" in prompt
    assert "explain_hourly_anomaly" in prompt
    assert "Peak Demand Surge (> 1180 kVA)" in prompt

    # 6. Core Invariants & Data Components
    assert "Asia/Kolkata" in prompt
    assert "NEVER sum instantaneous power" in prompt
    assert "Missing data MUST return null" in prompt
    assert "1475" in prompt  # Contract demand kVA
    assert "1180" in prompt  # 80% threshold kVA
    assert "[C1] FACILITY INCOMER" in prompt
    assert "[C2] TOD TARIFF & COST" in prompt
    assert "[C3] SHIFT-WISE ENERGY" in prompt
    assert "[C8] EQUIPMENT-WISE CATEGORIES" in prompt
    assert "[C9] ZONE-WISE COST CENTERS" in prompt
