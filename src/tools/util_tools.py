"""
Utility Tools for Yamaha Energy Assistant
Provides Date/Time utils (IST timezone aware, shift resolvers), File searching, and Tag catalog lookups.
"""

import datetime
import fnmatch
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo
from langchain_core.tools import tool

from src.core.constants import TIMEZONE
from src.db.tag_catalog import COST_CENTER_MAPPINGS, CATEGORY_CONFIG

IST = ZoneInfo(TIMEZONE)

# ---------------------------------------------------------
# Date & Time Tools (IST Aware)
# ---------------------------------------------------------

@tool
def get_current_datetime_ist() -> Dict[str, Any]:
    """
    Get the current date, time, weekday, and currently active industrial shift in IST (Asia/Kolkata).
    Crucial for resolving relative terms like 'today', 'now', or determining the active shift.
    """
    now = datetime.datetime.now(IST)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    hour = now.hour
    minute = now.minute

    # Determine active shift based on Section 9 rules:
    # Shift C: 00:40 to 08:00
    # Shift A: 08:00 to 17:00
    # Shift B: 17:00 to 00:40 (next day)
    minutes_from_midnight = hour * 60 + minute
    if 40 <= minutes_from_midnight < 480:
        active_shift = "C"
        shift_window = "00:40 - 08:00"
    elif 480 <= minutes_from_midnight < 1020:
        active_shift = "A"
        shift_window = "08:00 - 17:00"
    else:
        active_shift = "B"
        shift_window = "17:00 - 00:40 next day"

    return {
        "current_date": date_str,
        "current_time": time_str,
        "current_datetime_iso": now.isoformat(),
        "timezone": TIMEZONE,
        "day_of_week": now.strftime("%A"),
        "is_weekend": now.weekday() in (5, 6),
        "current_month": now.strftime("%Y-%m"),
        "current_year": now.year,
        "active_shift": active_shift,
        "active_shift_window": shift_window
    }

@tool
def resolve_relative_date_window(
    expression: Literal[
        "today",
        "yesterday",
        "this_week",
        "last_week",
        "this_month",
        "last_month",
        "last_7_days",
        "last_30_days"
    ]
) -> Dict[str, Any]:
    """
    Resolve common relative time expressions ('today', 'yesterday', 'this_week', 'last_week',
    'this_month', 'last_month', 'last_7_days', 'last_30_days') into exact IST start and end dates.

    For more complex queries (e.g., "last 3 months Mondays"), use resolve_advanced_date_query instead.
    """
    now = datetime.datetime.now(IST)
    today = now.date()

    if expression == "today":
        start_date = today
        end_date = today
    elif expression == "yesterday":
        start_date = today - datetime.timedelta(days=1)
        end_date = start_date
    elif expression == "last_7_days":
        start_date = today - datetime.timedelta(days=7)
        end_date = today
    elif expression == "last_30_days":
        start_date = today - datetime.timedelta(days=30)
        end_date = today
    elif expression == "this_week":
        # Monday of current week to today
        start_date = today - datetime.timedelta(days=today.weekday())
        end_date = today
    elif expression == "last_week":
        # Monday to Sunday of previous week
        start_date = today - datetime.timedelta(days=today.weekday() + 7)
        end_date = start_date + datetime.timedelta(days=6)
    elif expression == "this_month":
        start_date = today.replace(day=1)
        end_date = today
    elif expression == "last_month":
        # First to last day of previous month
        first_of_this_month = today.replace(day=1)
        end_date = first_of_this_month - datetime.timedelta(days=1)
        start_date = end_date.replace(day=1)
    else:
        return {"error": f"Unsupported relative date expression: {expression}"}

    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    days_count = (end_date - start_date).days + 1

    return {
        "expression": expression,
        "start_date": start_str,
        "end_date": end_str,
        "start_timestamp": f"{start_str} 00:00:00",
        "end_timestamp": f"{end_str} 23:59:59",
        "days_count": days_count,
        "timezone": TIMEZONE
    }


# Day of week mapping
DAY_NAME_TO_NUM = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def _parse_period_expression(period: str, today: datetime.date) -> tuple:
    """
    Parse period expressions like 'last_3_months', 'last_6_weeks', 'this_quarter', etc.
    Returns (start_date, end_date) tuple.
    """
    period_lower = period.lower().replace(" ", "_").replace("-", "_")

    # Handle "last_N_days/weeks/months"
    import re
    match = re.match(r"last_(\d+)_(day|days|week|weeks|month|months)", period_lower)
    if match:
        n = int(match.group(1))
        unit = match.group(2).rstrip("s")  # Normalize to singular

        if unit == "day":
            start_date = today - datetime.timedelta(days=n)
            end_date = today - datetime.timedelta(days=1)  # Exclude today
        elif unit == "week":
            start_date = today - datetime.timedelta(weeks=n)
            end_date = today - datetime.timedelta(days=1)
        elif unit == "month":
            # Go back N months
            year = today.year
            month = today.month - n
            while month <= 0:
                month += 12
                year -= 1
            start_date = datetime.date(year, month, 1)
            # End at last day of previous month
            first_of_this_month = today.replace(day=1)
            end_date = first_of_this_month - datetime.timedelta(days=1)
        return start_date, end_date

    # Handle quarters
    if period_lower in ("this_quarter", "current_quarter"):
        q = (today.month - 1) // 3
        start_month = q * 3 + 1
        start_date = datetime.date(today.year, start_month, 1)
        end_date = today
        return start_date, end_date

    if period_lower == "last_quarter":
        q = (today.month - 1) // 3
        if q == 0:
            # Q4 of previous year
            start_date = datetime.date(today.year - 1, 10, 1)
            end_date = datetime.date(today.year - 1, 12, 31)
        else:
            start_month = (q - 1) * 3 + 1
            end_month = q * 3
            start_date = datetime.date(today.year, start_month, 1)
            # Last day of end_month
            if end_month == 12:
                end_date = datetime.date(today.year, 12, 31)
            else:
                end_date = datetime.date(today.year, end_month + 1, 1) - datetime.timedelta(days=1)
        return start_date, end_date

    # Handle year
    if period_lower == "this_year":
        start_date = datetime.date(today.year, 1, 1)
        end_date = today
        return start_date, end_date

    if period_lower == "last_year":
        start_date = datetime.date(today.year - 1, 1, 1)
        end_date = datetime.date(today.year - 1, 12, 31)
        return start_date, end_date

    # Handle specific months (last_october, etc.)
    month_names = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
        "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12
    }

    match = re.match(r"last_(\w+)", period_lower)
    if match:
        month_name = match.group(1)
        if month_name in month_names:
            target_month = month_names[month_name]
            # Determine year (if target month is in future, use previous year)
            if target_month >= today.month:
                year = today.year - 1
            else:
                year = today.year
            start_date = datetime.date(year, target_month, 1)
            if target_month == 12:
                end_date = datetime.date(year, 12, 31)
            else:
                end_date = datetime.date(year, target_month + 1, 1) - datetime.timedelta(days=1)
            return start_date, end_date

    return None, None


def _filter_dates_by_day_of_week(start_date: datetime.date, end_date: datetime.date,
                                   day_filter: Optional[str]) -> List[str]:
    """
    Generate list of dates between start and end, optionally filtered by day of week.
    day_filter: 'monday', 'weekdays', 'weekends', or None (all days)
    """
    dates = []
    current = start_date

    # Parse day filter
    target_days = None
    if day_filter:
        day_lower = day_filter.lower()
        if day_lower in DAY_NAME_TO_NUM:
            target_days = {DAY_NAME_TO_NUM[day_lower]}
        elif day_lower == "weekdays":
            target_days = {0, 1, 2, 3, 4}  # Mon-Fri
        elif day_lower == "weekends":
            target_days = {5, 6}  # Sat-Sun
        elif day_lower.endswith("s") and day_lower[:-1] in DAY_NAME_TO_NUM:
            # Handle plurals like "mondays"
            target_days = {DAY_NAME_TO_NUM[day_lower[:-1]]}

    while current <= end_date:
        if target_days is None or current.weekday() in target_days:
            dates.append(current.strftime("%Y-%m-%d"))
        current += datetime.timedelta(days=1)

    return dates


@tool
def resolve_advanced_date_query(
    period: str,
    day_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """
    🗓️ ADVANCED DATE RESOLVER — ONLY for day-of-week filtering (Mondays, weekends, etc.)

    ⚠️ WHEN TO USE THIS TOOL vs OTHER TOOLS:

    ✅ USE THIS TOOL ONLY FOR:
    - "last 3 months Mondays consumption" → day_filter="monday" is REQUIRED
    - "last quarter weekends" → day_filter="weekends" is REQUIRED
    - "last 6 weeks Fridays" → day_filter="friday" is REQUIRED

    ❌ DO NOT USE THIS TOOL FOR:
    - "last 1 year zone consumption" → Use grouping_energy(group_by="zone") with date range
    - "last month equipment breakdown" → Use grouping_energy(group_by="equipment")
    - "total consumption this quarter" → Use get_cummulative_energy with start_date/end_date
    - Any query WITHOUT a specific day-of-week filter

    PERIOD OPTIONS:
    - last_N_days, last_N_weeks, last_N_months (e.g., "last_3_months", "last_6_weeks")
    - this_quarter, last_quarter
    - this_year, last_year (⚠️ but only if day_filter is specified!)

    DAY_FILTER OPTIONS (REQUIRED for this tool to make sense):
    - monday, tuesday, wednesday, thursday, friday, saturday, sunday
    - weekdays (Mon-Fri)
    - weekends (Sat-Sun)

    RETURNS:
    - filtered_dates: List of specific dates matching the day_filter (max 100)

    WORKFLOW for "last 3 months Monday's top consuming zone":
    1. resolve_advanced_date_query(period="last_3_months", day_filter="monday") → get 12-13 dates
    2. aggregate_multi_date(dates=[...], group_by="zone") → rank zones by total
    """
    now = datetime.datetime.now(IST)
    today = now.date()

    # Try to parse the period expression
    start_date, end_date = _parse_period_expression(period, today)

    # Fallback to simple expressions
    if start_date is None:
        period_lower = period.lower().replace(" ", "_").replace("-", "_")
        simple_map = {
            "today": (today, today),
            "yesterday": (today - datetime.timedelta(days=1), today - datetime.timedelta(days=1)),
            "this_week": (today - datetime.timedelta(days=today.weekday()), today),
            "last_week": (
                today - datetime.timedelta(days=today.weekday() + 7),
                today - datetime.timedelta(days=today.weekday() + 1)
            ),
            "this_month": (today.replace(day=1), today),
            "last_month": (
                (today.replace(day=1) - datetime.timedelta(days=1)).replace(day=1),
                today.replace(day=1) - datetime.timedelta(days=1)
            ),
        }
        if period_lower in simple_map:
            start_date, end_date = simple_map[period_lower]
        else:
            return {
                "error": f"Could not parse period expression: {period}",
                "hint": "Try formats like 'last_3_months', 'last_6_weeks', 'last_quarter', 'this_year'"
            }

    # Generate filtered dates
    filtered_dates = _filter_dates_by_day_of_week(start_date, end_date, day_filter)

    # Build response
    result = {
        "period": period,
        "day_filter": day_filter,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "filtered_dates": filtered_dates,
        "days_count": len(filtered_dates),
        "timezone": TIMEZONE,
    }

    # Add helpful hints for aggregation
    if day_filter:
        day_name = day_filter.title().rstrip("s")
        result["usage_hint"] = f"Use these {len(filtered_dates)} {day_name} dates to query consumption data, then aggregate and rank."

    return result

@tool
def get_shift_boundaries(date_str: str, shift: Literal["A", "B", "C"]) -> Dict[str, Any]:
    """
    Get exact start and end boundary timestamps in IST for a given shift on date (YYYY-MM-DD):
    - Shift C: D 00:40:00 to D 08:00:00
    - Shift A: D 08:00:00 to D 17:00:00
    - Shift B: D 17:00:00 to D+1 00:40:00 (spans midnight into next day)
    """
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    next_dt = dt + datetime.timedelta(days=1)
    next_date_str = next_dt.strftime("%Y-%m-%d")

    if shift == "A":
        start_ts = f"{date_str} 08:00:00"
        end_ts = f"{date_str} 17:00:00"
        desc = "Day Shift (08:00 - 17:00 IST)"
    elif shift == "B":
        start_ts = f"{date_str} 17:00:00"
        end_ts = f"{next_date_str} 00:40:00"
        desc = f"Evening Shift (17:00 - {next_date_str} 00:40 IST)"
    elif shift == "C":
        start_ts = f"{date_str} 00:40:00"
        end_ts = f"{date_str} 08:00:00"
        desc = "Night Shift (00:40 - 08:00 IST)"
    else:
        return {"error": f"Invalid shift: {shift}. Choose 'A', 'B', or 'C'."}

    return {
        "date": date_str,
        "shift": shift,
        "start_timestamp": start_ts,
        "end_timestamp": end_ts,
        "description": desc,
        "note": "Per Section 9: 00:00-00:40 belongs to previous day's Shift B"
    }

# ---------------------------------------------------------
# File Searching & Reading Tools
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".cache"}

@tool
def search_project_files(pattern: str, sub_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Search for files in the project workspace matching a filename or glob pattern (e.g. '*.md', '*reference*', '*.sql').
    Optional sub_dir restricts search to a subdirectory like 'scripts', 'src', or 'tests'.
    """
    target_dir = PROJECT_ROOT
    if sub_dir:
        # Prevent path traversal
        clean_subdir = os.path.normpath(sub_dir).lstrip("/")
        candidate = (PROJECT_ROOT / clean_subdir).resolve()
        if PROJECT_ROOT in candidate.parents or candidate == PROJECT_ROOT:
            target_dir = candidate
        else:
            return {"error": "Invalid sub_dir: access outside project root is not permitted."}

    matched_files = []
    pattern_lower = pattern.lower()

    for root, dirs, files in os.walk(target_dir):
        # Prune ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for file in files:
            file_lower = file.lower()
            if fnmatch.fnmatch(file_lower, pattern_lower) or pattern_lower in file_lower:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(PROJECT_ROOT)
                matched_files.append({
                    "relative_path": str(rel_path),
                    "filename": file,
                    "size_bytes": full_path.stat().st_size,
                    "modified": datetime.datetime.fromtimestamp(full_path.stat().st_mtime, IST).strftime("%Y-%m-%d %H:%M:%S")
                })

    return {
        "pattern": pattern,
        "search_directory": str(target_dir.relative_to(PROJECT_ROOT)) if target_dir != PROJECT_ROOT else ".",
        "count": len(matched_files),
        "files": matched_files[:50]
    }

@tool
def read_project_file(file_path: str, start_line: int = 1, num_lines: int = 100) -> Dict[str, Any]:
    """
    Read content of a file within the project workspace.
    Safe against directory traversal. Supports pagination via start_line and num_lines.
    """
    clean_path = os.path.normpath(file_path).lstrip("/")
    target = (PROJECT_ROOT / clean_path).resolve()

    # Safety check
    if PROJECT_ROOT not in target.parents and target != PROJECT_ROOT:
        return {"error": "Access denied: cannot read files outside the project root directory."}

    if not target.exists() or not target.is_file():
        return {"error": f"File not found: {file_path}"}

    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)
        start_idx = max(0, start_line - 1)
        end_idx = min(total_lines, start_idx + num_lines)
        selected_lines = all_lines[start_idx:end_idx]

        return {
            "file_path": str(target.relative_to(PROJECT_ROOT)),
            "start_line": start_idx + 1,
            "end_line": end_idx,
            "total_lines": total_lines,
            "has_more": end_idx < total_lines,
            "content": "".join(selected_lines)
        }
    except Exception as e:
        return {"error": f"Failed to read file: {str(e)}"}

# ---------------------------------------------------------
# Tag Catalog Search Tool
# ---------------------------------------------------------

from src.core.normalizers import (
    normalize_category_name,
    normalize_cost_center_name,
    is_fuzzy_match
)

@tool
def search_tag_catalog(keyword: str) -> Dict[str, Any]:
    """
    Search the authoritative Yamaha tag catalog by meter name, machine, or keyword
    (e.g. 'chiller', 'molding', 'transformer', 'dust_collector', 'steam', 'solar').
    Tolerates typographical errors, misspellings ('chiler', 'mouldng', 'compreser'),
    and colloquial aliases ('ac', 'lights', 'admin').
    Returns exact tag IDs and their associated Cost Center or Equipment Category.
    """
    kw = keyword.lower().strip()
    results = []
    seen_tags = set()

    # Normalize aliases if applicable (e.g. 'moulding' -> 'Molding', 'ac' -> 'Airconditioning')
    resolved_cat = normalize_category_name(kw)
    resolved_cc = normalize_cost_center_name(kw)

    # 1. Search in Cost Centers
    for cc_name, tags in COST_CENTER_MAPPINGS.items():
        is_cc_target = (
            kw in cc_name.lower() or 
            (resolved_cc and resolved_cc.lower() == cc_name.lower()) or
            is_fuzzy_match(kw, cc_name, cutoff=0.7)
        )
        for t in tags:
            t_lower = t.lower()
            tokens = [tok for tok in t_lower.replace('/', '_').replace('.', '_').split('_') if tok]
            has_token_match = any(is_fuzzy_match(kw, tok, cutoff=0.75) for tok in tokens)
            
            if is_cc_target or kw in t_lower or has_token_match:
                if t not in seen_tags:
                    seen_tags.add(t)
                    results.append({
                        "tag_id": t,
                        "mapping_type": "Cost Center",
                        "group_name": cc_name
                    })

    # 2. Search in Category Configs
    for cat_name, cfg in CATEGORY_CONFIG.items():
        prefix = cfg["prefix"]
        is_cat_target = (
            kw in cat_name.lower() or
            kw in prefix.lower() or
            (resolved_cat and resolved_cat.lower() == cat_name.lower()) or
            is_fuzzy_match(kw, cat_name, cutoff=0.7)
        )
        if is_cat_target:
            results.append({
                "tag_prefix": prefix,
                "suffix": cfg["suffix"],
                "mapping_type": "Equipment Category",
                "group_name": cat_name
            })

    return {
        "keyword": keyword,
        "resolved_alias": resolved_cat or resolved_cc or None,
        "match_count": len(results),
        "matches": results[:40]
    }

ALL_UTIL_TOOLS = [
    get_current_datetime_ist,
    resolve_relative_date_window,
    resolve_advanced_date_query,  # Advanced date resolver with day-of-week filtering
    get_shift_boundaries,
    search_project_files,
    read_project_file,
    search_tag_catalog,
]
