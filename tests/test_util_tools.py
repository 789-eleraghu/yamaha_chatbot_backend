"""
Unit Tests for Utility Tools (src/tools/util_tools.py)
"""

import pytest
from src.tools.util_tools import (
    get_current_datetime_ist,
    resolve_relative_date_window,
    get_shift_boundaries,
    search_project_files,
    read_project_file,
    search_tag_catalog,
)

def test_get_current_datetime_ist():
    res = get_current_datetime_ist.invoke({})
    assert "current_date" in res
    assert "current_time" in res
    assert res["timezone"] == "Asia/Kolkata"
    assert res["active_shift"] in ("A", "B", "C")
    assert "day_of_week" in res

def test_resolve_relative_date_window():
    # Today
    today_res = resolve_relative_date_window.invoke({"expression": "today"})
    assert today_res["start_date"] == today_res["end_date"]
    assert today_res["days_count"] == 1

    # Yesterday
    yest_res = resolve_relative_date_window.invoke({"expression": "yesterday"})
    assert yest_res["start_date"] == yest_res["end_date"]
    assert yest_res["days_count"] == 1

    # Last 7 days
    res_7d = resolve_relative_date_window.invoke({"expression": "last_7_days"})
    assert res_7d["days_count"] == 8

    # Last month
    last_m = resolve_relative_date_window.invoke({"expression": "last_month"})
    assert last_m["days_count"] in (28, 29, 30, 31)

def test_get_shift_boundaries():
    date_str = "2026-10-15"
    shift_a = get_shift_boundaries.invoke({"date_str": date_str, "shift": "A"})
    assert shift_a["start_timestamp"] == f"{date_str} 08:00:00"
    assert shift_a["end_timestamp"] == f"{date_str} 17:00:00"

    shift_b = get_shift_boundaries.invoke({"date_str": date_str, "shift": "B"})
    assert shift_b["start_timestamp"] == f"{date_str} 17:00:00"
    assert shift_b["end_timestamp"] == "2026-10-16 00:40:00"

    shift_c = get_shift_boundaries.invoke({"date_str": date_str, "shift": "C"})
    assert shift_c["start_timestamp"] == f"{date_str} 00:40:00"
    assert shift_c["end_timestamp"] == f"{date_str} 08:00:00"

def test_search_project_files():
    res = search_project_files.invoke({"pattern": "*.md"})
    assert res["count"] > 0
    filenames = [f["filename"] for f in res["files"]]
    assert "energy-ai-assistant-reference.md" in filenames

    # Test with subdirectory
    res_scripts = search_project_files.invoke({"pattern": "*.py", "sub_dir": "scripts"})
    assert res_scripts["count"] > 0
    script_names = [f["filename"] for f in res_scripts["files"]]
    assert "seed_mock_db.py" in script_names

def test_read_project_file():
    res = read_project_file.invoke({
        "file_path": "energy-ai-assistant-reference.md",
        "start_line": 1,
        "num_lines": 10
    })
    assert res["start_line"] == 1
    assert res["end_line"] == 10
    assert "Energy AI Assistant" in res["content"]

    # Test safety against path traversal
    bad_res = read_project_file.invoke({"file_path": "../../etc/passwd"})
    assert "error" in bad_res

def test_search_tag_catalog():
    res = search_tag_catalog.invoke({"keyword": "chiller"})
    assert res["match_count"] > 0
    tag_ids = [m["tag_id"] for m in res["matches"] if "tag_id" in m]
    assert any("Chiller" in t for t in tag_ids)

    # Category search
    cat_res = search_tag_catalog.invoke({"keyword": "molding"})
    assert cat_res["match_count"] > 0
