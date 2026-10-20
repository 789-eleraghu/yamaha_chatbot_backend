"""
Typo Tolerance & Entity Normalization Engine
Provides fuzzy matching, alias resolution, and resilient date parsing
for natural language inputs with typos, misspellings, and format variations.
"""

import datetime
import difflib
import re
from typing import Dict, List, Optional
from src.core.constants import EQUIPMENT_WISE_CATEGORIES
from src.db.tag_catalog import COST_CENTER_MAPPINGS

# ---------------------------------------------------------
# 1. Date Normalization (Whitespace, Slashes, Ordinals, Words)
# ---------------------------------------------------------

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

def normalize_date_str(date_str: str) -> str:
    """
    Tolerantly parse and normalize a date string into standard 'YYYY-MM-DD'.
    Handles whitespace, slashes ('2026/10/15'), reverse order ('15-10-2026'),
    ordinals ('15th October 2026'), and abbreviated month names ('15 Oct 2026').
    """
    if not date_str:
        return ""
    
    s = str(date_str).strip()
    # Remove ordinal suffixes: 1st, 2nd, 3rd, 14th, 15th
    s_clean = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", s, flags=re.IGNORECASE)

    for fmt in DATE_FORMATS:
        try:
            dt = datetime.datetime.strptime(s_clean, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
            
    # Fallback to regex pattern YYYY-MM-DD if embedded in surrounding noise
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if match:
        y, m, d = match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

    return s

# ---------------------------------------------------------
# 2. Equipment Category Aliases & Fuzzy Matching
# ---------------------------------------------------------

CATEGORY_ALIASES: Dict[str, str] = {
    # British / alternate spellings
    "moulding": "Molding",
    "mould": "Molding",
    "molding press": "Molding",
    "molding presses": "Molding",
    "mold": "Molding",
    "moldng": "Molding",

    # Compressors
    "compressor": "Compressor",
    "compressors": "Compressor",
    "compresor": "Compressor",
    "compreser": "Compressor",
    "air compressor": "Compressor",
    "air compressors": "Compressor",

    # Airconditioning / Chillers
    "ac": "Airconditioning",
    "a/c": "Airconditioning",
    "air condition": "Airconditioning",
    "air conditioning": "Airconditioning",
    "airconditioning": "Airconditioning",
    "air conditioning units": "Airconditioning",
    "air_conditioning": "Airconditioning",
    "chiller": "Airconditioning",
    "chillers": "Airconditioning",
    "ahu": "Airconditioning",
    "hvac": "Airconditioning",

    # Paintshop
    "paint": "Paintshop",
    "paint shop": "Paintshop",
    "paintshop": "Paintshop",
    "paint_shop": "Paintshop",
    "painting": "Paintshop",

    # Lighting
    "lighting": "Lighting",
    "lights": "Lighting",
    "light": "Lighting",
    "lightng": "Lighting",
    "illumination": "Lighting",

    # Dust Collector
    "dust": "Dust_Collector",
    "dust collector": "Dust_Collector",
    "dust collectors": "Dust_Collector",
    "dust_collector": "Dust_Collector",
    "dustcolector": "Dust_Collector",
    "dust collection": "Dust_Collector",

    # Production Power
    "production": "Production_Power",
    "production power": "Production_Power",
    "production_power": "Production_Power",
    "production machines": "Production_Power",
    "machinery": "Production_Power",

    # Others
    "other": "Others",
    "others": "Others",
}

def normalize_category_name(category_query: str) -> Optional[str]:
    """
    Resolve a misspelled or colloquial equipment category name into the canonical 8 categories.
    """
    if not category_query:
        return None

    raw = category_query.strip().lower().replace("-", " ").replace("_", " ")

    # Direct alias lookup
    if raw in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[raw]

    # Partial substring check in aliases
    for alias, canonical in CATEGORY_ALIASES.items():
        if alias in raw:
            return canonical

    # Fuzzy match against canonical categories
    matches = difflib.get_close_matches(category_query.strip(), EQUIPMENT_WISE_CATEGORIES, n=1, cutoff=0.55)
    if matches:
        return matches[0]

    return None

# ---------------------------------------------------------
# 3. Cost Center Aliases & Fuzzy Matching (17 Departments)
# ---------------------------------------------------------

COST_CENTER_ALIASES: Dict[str, str] = {
    "admin": "General Admin",
    "general admin": "General Admin",
    "general administration": "General Admin",
    "office": "General Admin",
    "it": "Information System",
    "information systems": "Information System",
    "info system": "Information System",
    "kiln": "AG KILN Dry",
    "kiln dry": "AG KILN Dry",
    "ag kiln": "AG KILN Dry",
    "wp": "AG WP Process",
    "wp process": "AG WP Process",
    "ag wp": "AG WP Process",
    "ww": "AG WW Assy",
    "ww assy": "AG WW Assy",
    "ag ww": "AG WW Assy",
    "ag paint": "AG Painting",
    "ag painting": "AG Painting",
    "ag assy": "AG Assy",
    "pk paint": "Painting Printing",
    "painting printing": "Painting Printing",
    "pk assy": "PK Assy",
    "pa ww": "PA WW Process",
    "pa ww process": "PA WW Process",
    "wood finish": "PA WW Process",
    "pa paint": "PA Painting",
    "pa painting": "PA Painting",
    "pa assy": "PA Assy",
    "warehouse": "Material W/H",
    "material wh": "Material W/H",
    "material warehouse": "Material W/H",
    "production prepare": "Production Prepare",
    "prepare": "Production Prepare",
    "production improve": "Production Improve",
    "improve": "Production Improve",
    "moulding dept": "Production Improve",
    "inspection": "Process Inspection",
    "process inspection": "Process Inspection",
    "qa": "Process Inspection",
    "oqc": "Process Inspection",
    "logistics": "Logistics & Shipping",
    "shipping": "Logistics & Shipping",
    "dispatch": "Logistics & Shipping",
}

def normalize_cost_center_name(cc_query: str) -> Optional[str]:
    """
    Resolve a misspelled or colloquial department name into one of the 17 Cost Centers.
    """
    if not cc_query:
        return None

    raw = cc_query.strip().lower()

    if raw in COST_CENTER_ALIASES:
        return COST_CENTER_ALIASES[raw]

    for alias, canonical in COST_CENTER_ALIASES.items():
        if alias in raw:
            return canonical

    all_ccs = list(COST_CENTER_MAPPINGS.keys())
    matches = difflib.get_close_matches(cc_query.strip(), all_ccs, n=1, cutoff=0.55)
    if matches:
        return matches[0]

    return None

# ---------------------------------------------------------
# 4. Fuzzy Token Matching Helper
# ---------------------------------------------------------

def is_fuzzy_match(word: str, target: str, cutoff: float = 0.75) -> bool:
    """Check if word is close enough to target (handles character swaps, omissions, additions)."""
    w = word.lower().strip()
    t = target.lower().strip()
    if w == t or w in t or t in w:
        return True
    return difflib.SequenceMatcher(None, w, t).ratio() >= cutoff
