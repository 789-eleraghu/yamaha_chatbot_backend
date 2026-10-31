"""
Unit Tests for Typo Tolerance, Entity Normalization, and Resilient Parsing
"""

import pytest
from src.core.normalizers import (
    normalize_date_str,
    normalize_category_name,
    normalize_cost_center_name,
    is_fuzzy_match,
)
from src.tools.util_tools import search_tag_catalog
from src.rag.retriever import ems_kb
from src.services.telemetry import facility_telemetry
from src.services.tariff_service import TariffService

def test_normalize_date_str_variations():
    expected = "2026-10-15"
    variations = [
        " 2026-10-15 ",
        "2026/10/15",
        "15-10-2026",
        "15/10/2026",
        "2026.10.15",
        "15 Oct 2026",
        "October 15 2026",
        "15th October 2026",
        "15th Oct 2026",
    ]
    for v in variations:
        assert normalize_date_str(v) == expected, f"Failed on: {v}"

def test_normalize_category_typos_and_aliases():
    cases = {
        "moulding": "Molding",
        "moldng": "Molding",
        "compresor": "Compressor",
        "compreser": "Compressor",
        "air condition": "Airconditioning",
        "ac": "Airconditioning",
        "chiller": "Airconditioning",
        "paint shop": "Paintshop",
        "lightng": "Lighting",
        "lights": "Lighting",
        "dust colector": "Dust_Collector",
        "production power": "Production_Power",
    }
    for typo, expected in cases.items():
        assert normalize_category_name(typo) == expected, f"Failed for typo: {typo}"

def test_normalize_cost_center_aliases():
    cases = {
        "admin": "General Admin",
        "general admin": "General Admin",
        "general administration": "General Admin",
        "it": "Information System",
        "kiln": "AG KILN Dry",
        "warehouse": "Material W/H",
        "material wh": "Material W/H",
        "shipping": "Logistics & Shipping",
        "logistics": "Logistics & Shipping",
        "inspection": "Process Inspection",
        "qa": "Process Inspection",
    }
    for alias, expected in cases.items():
        assert normalize_cost_center_name(alias) == expected, f"Failed for alias: {alias}"

def test_search_tag_catalog_with_typos():
    # Misspelled keywords should still return tags
    res_chiller = search_tag_catalog.invoke({"keyword": "chiler"})
    assert res_chiller["match_count"] > 0

    res_moulding = search_tag_catalog.invoke({"keyword": "mouldng"})
    assert res_moulding["match_count"] > 0

    res_compresor = search_tag_catalog.invoke({"keyword": "compreser"})
    assert res_compresor["match_count"] > 0

def test_ems_kb_search_with_typos():
    # Documentation retriever with slightly misspelled terms
    res = ems_kb.search("tarff rescaling", top_k=2)
    assert len(res) > 0

    res_demand = ems_kb.search("peack demnd limits", top_k=2)
    assert len(res) > 0

def test_services_with_varied_date_inputs():
    # Service calls with non-canonical date formats
    res_energy = facility_telemetry.get_grid_energy(" 2026-10-15 ")
    assert res_energy["energy_kwh"] > 0

    res_shift = facility_telemetry.get_grid_shift_energy("15-10-2026")
    assert res_shift["total_shifts_kwh"] > 0

    res_tariff = TariffService.calculate_daily_cost("2026/10/15")
    assert res_tariff["total_cost_inr"] > 0
