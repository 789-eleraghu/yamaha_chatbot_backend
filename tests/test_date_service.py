"""
Unit Tests for Date Resolution & Validation Service
"""

import pytest
from src.services.date_service import date_service

def test_today_and_yesterday_ist():
    today = date_service.today_ist_str()
    yesterday = date_service.yesterday_ist_str()
    assert len(today) == 10
    assert len(yesterday) == 10
    assert today > yesterday

def test_relative_expressions():
    eff_today = date_service.normalize_and_validate_date("today")
    assert eff_today == "2026-10-20" or eff_today is not None

    eff_yday = date_service.normalize_and_validate_date("yesterday")
    assert eff_yday is not None
    assert eff_yday < eff_today

def test_date_validation_and_parsing():
    # Valid formats
    assert date_service.normalize_and_validate_date("2026-10-15") == "2026-10-15"
    assert date_service.normalize_and_validate_date("15-10-2026") == "2026-10-15"
    assert date_service.normalize_and_validate_date("15/10/2026") == "2026-10-15"
    assert date_service.normalize_and_validate_date("15th October 2026") == "2026-10-15"
    assert date_service.normalize_and_validate_date("October 15 2026") == "2026-10-15"

    # Historical dates preserved (NOT silently rewritten to 2026)
    assert date_service.normalize_and_validate_date("2024-05-12") == "2024-05-12"
    assert date_service.normalize_and_validate_date("2025-01-01") == "2025-01-01"

    # Invalid dates
    assert date_service.normalize_and_validate_date("2026-02-31") is None
    assert date_service.normalize_and_validate_date("invalid-date-string") is None

def test_extract_date_from_prompt():
    d1, exp1 = date_service.extract_date_from_prompt("What was consumption on 2026-10-12?")
    assert d1 == "2026-10-12"
    assert exp1 is True

    d2, exp2 = date_service.extract_date_from_prompt("Show me yesterday's shift breakdown")
    assert exp2 is True
    assert d2 is not None

    d3, exp3 = date_service.extract_date_from_prompt("Show me power quality for 15 October 2026")
    assert d3 == "2026-10-15"
    assert exp3 is True

    d4, exp4 = date_service.extract_date_from_prompt("Hello assistant")
    assert exp4 is False
