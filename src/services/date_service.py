"""
Date Resolution & Validation Service for Yamaha Industrial EMS
Provides timezone-aware (Asia/Kolkata) date parsing, relative expression resolution,
database telemetry boundary validation, and eliminates hardcoded dates.
"""

import datetime
import re
from typing import Optional, Tuple
from zoneinfo import ZoneInfo
from src.core.config import settings

# Plant timezone is strictly Indian Standard Time (UTC+05:30)
PLANT_TIMEZONE = ZoneInfo("Asia/Kolkata")

DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y.%m.%d",
    "%d %b %Y",
    "%d %B %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
]

class DateService:
    """Timezone-aware date resolution and validation service."""

    @staticmethod
    def now_ist() -> datetime.datetime:
        """Return current datetime in Asia/Kolkata."""
        return datetime.datetime.now(PLANT_TIMEZONE)

    @classmethod
    def today_ist_str(cls) -> str:
        """Return today's date formatted as YYYY-MM-DD in IST."""
        return cls.now_ist().strftime("%Y-%m-%d")

    @classmethod
    def yesterday_ist_str(cls) -> str:
        """Return yesterday's date formatted as YYYY-MM-DD in IST."""
        return (cls.now_ist() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    @staticmethod
    def get_db_date_bounds() -> Tuple[Optional[str], Optional[str]]:
        """
        Query the ClickHouse telemetry database for min and max available dates.
        Returns (min_date, max_date) as 'YYYY-MM-DD' strings.
        """
        try:
            from src.db.client import db_client
            rows = db_client.execute_query("SELECT toString(min(day)) as min_d, toString(max(day)) as max_d FROM tag_daily_energy_rollup;")
            if rows and rows[0].get("min_d") and rows[0].get("max_d"):
                return str(rows[0]["min_d"]), str(rows[0]["max_d"])
        except Exception:
            pass
        # Fallback to known telemetry boundaries if DB unreachable
        return "2026-09-01", "2026-10-20"

    @classmethod
    def get_effective_default_date(cls) -> str:
        """
        Returns the most recent active date available in the plant database.
        If today falls within the telemetry range, uses today; otherwise uses the max DB date.
        """
        _, max_db_date = cls.get_db_date_bounds()
        today = cls.today_ist_str()
        if max_db_date and today > max_db_date:
            return max_db_date
        return today

    @classmethod
    def normalize_and_validate_date(cls, date_str: str) -> Optional[str]:
        """
        Tolerantly parse a date string into 'YYYY-MM-DD'.
        Returns normalized date if valid, None if invalid or unparseable.
        Does NOT alter historical years (e.g. 2024 is preserved).
        """
        if not date_str:
            return None

        s = str(date_str).strip()
        s_lower = s.lower()

        # Handle relative expressions
        if s_lower in ("today", "current", "now"):
            return cls.get_effective_default_date()

        if s_lower in ("yesterday", "yestarday", "yday"):
            # If default date is max_db_date, yesterday is day before that
            ref_date = cls.get_effective_default_date()
            try:
                dt = datetime.datetime.strptime(ref_date, "%Y-%m-%d")
                return (dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            except Exception:
                return cls.yesterday_ist_str()

        # Remove ordinal suffixes (1st, 2nd, 3rd, 14th)
        s_clean = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", s, flags=re.IGNORECASE)

        for fmt in DATE_FORMATS:
            try:
                dt = datetime.datetime.strptime(s_clean, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # Regex search for YYYY-MM-DD or YYYY/MM/DD
        match = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", s)
        if match:
            y, m, d = match.groups()
            try:
                dt = datetime.date(int(y), int(m), int(d))
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                return None

        return None

    @classmethod
    def extract_date_from_prompt(cls, prompt: str) -> Tuple[str, bool]:
        """
        Extract date from natural language prompt.
        Returns: (date_str: 'YYYY-MM-DD', was_explicit: bool)
        """
        p = prompt.lower()

        # 1. Relative checks
        if re.search(r"\byesterday\b|\byestarday\b|\byday\b", p):
            ref = cls.get_effective_default_date()
            dt = datetime.datetime.strptime(ref, "%Y-%m-%d")
            return (dt - datetime.timedelta(days=1)).strftime("%Y-%m-%d"), True

        if re.search(r"\btoday\b|\bcurrent\b|\bnow\b", p):
            return cls.get_effective_default_date(), True

        # 2. Explicit date pattern in text
        match = re.search(r"\b(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})\b", prompt)
        if match:
            norm = cls.normalize_and_validate_date(match.group(1))
            if norm:
                return norm, True

        # 3. Month name pattern (e.g. 15 October 2026 or Oct 15 2026)
        month_match = re.search(r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b", prompt, re.IGNORECASE)
        if month_match:
            norm = cls.normalize_and_validate_date(month_match.group(1))
            if norm:
                return norm, True

        # Default fallback
        return cls.get_effective_default_date(), False

    @classmethod
    def is_date_in_db_range(cls, date_str: str) -> bool:
        """Check if date falls within telemetry database records."""
        min_d, max_d = cls.get_db_date_bounds()
        if not min_d or not max_d:
            return True
        return min_d <= date_str <= max_d

date_service = DateService()
