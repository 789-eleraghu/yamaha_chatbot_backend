"""
Authoritative Tag Catalog & Device Registry
From: energy-ai-assistant-reference.md (Section 11, 12, 13, 14)
"""

from typing import Dict, List, Set
from src.core.constants import CATEGORY_EXCLUDED_TAGS

# 17 Organizational Cost Centers (Section 13)
COST_CENTER_MAPPINGS: Dict[str, List[str]] = {
    "General Admin": [
        "Airconditioning.PDB-3_Office/Energies/Real Energy/Real Energy Into the Load",
        "Airconditioning.PDB-4_Canteen/Energies/Real Energy/Real Energy Into the Load",
        "Airconditioning.PDB-8_Nursery/Energies/Real Energy/Real Energy Into the Load",
        "Compressor.Compressor_1/Energies/Real Energy/Real Energy Into the Load",
        "Compressor.Compressor_2/Energies/Real Energy/Real Energy Into the Load",
        "Compressor.Compressor_3/Energies/Real Energy/Real Energy Into the Load",
        "Compressor.PDB-12_Compressor/Energies/Real Energy/Real Energy Into the Load",
        "Lighting.SDB-9_L_Office/Energies/Real Energy/Real Energy Into the Load",
        "Lighting.SDB_Ext_Lighting_GH_1/Energies/Real Energy/Real Energy Into the Load",
        "Other.350kVAR_Capacitor/Energies/Real Energy/Real Energy Into the Load",
        "Other.700_kVAR_Capacitor/Energies/Real Energy/Real Energy Into the Load",
        "Other.PDB-10_North_LT_Room/Energies/Real Energy/Real Energy Into the Load",
        "Other.PDB-2_South_LT_Room/Energies/Real Energy/Real Energy Into the Load",
        "Other.PDB-5_Pump_Room/Energies/Real Energy/Real Energy Into the Load",
        "Other.PDB-6_Water_Supply_PUMP_Room/Energies/Real Energy/Real Energy Into the Load",
        "Other.PDB_1_Part_RS_SWH/Energies/Real Energy/Real Energy Into the Load",
        "Other.PDB_YMIN_Site_Office/Energies/Real Energy/Real Energy Into the Load",
        "Other.PP-ETP/Energies/Real Energy/Real Energy Into the Load",
        "Other.SDB-10_Nuresy/Energies/Real Energy/Real Energy Into the Load",
        "Other.SDB-7_L-P_GH2/Energies/Real Energy/Real Energy Into the Load",
        "Other.SDB-8A_P_Canteen/Energies/Real Energy/Real Energy Into the Load",
        "Other.SDB-9A_Office_Power/Energies/Real Energy/Real Energy Into the Load",
        "Other.Vendor_Yard/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PDB-9_RS/Energies/Real Energy/Real Energy Into the Load",
    ],
    "Information System": [
        "Airconditioning.Air_Conditioning-3/Energies/Energy/Active Energy Delivered",
        "Airconditioning.Air_Conditioning-4/Energies/Energy/Active Energy Delivered",
    ],
    "AG KILN Dry": [
        "Airconditioning.AC_Control_Room_Indoor/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G0-1_Dry_Space_2/Energies/Real Energy/Real Energy Into the Load",
    ],
    "AG WP Process": [
        "Dust_Collector.G0_143_Dust_Collector/Energies/Real Energy/Real Energy Into the Load",
        "Lighting.SDB-3_L_AG_WW/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.CNC_Machine_AG_WW/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G1-1_380V_AG_WW/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G1-2_380V_AG_WW/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G1-3_240V_AG_WW/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.SDB-4_P_AG_WW/Energies/Real Energy/Real Energy Into the Load",
    ],
    "AG WW Assy": [
        "Dust_Collector.G0_146_Dust_Collector/Energies/Real Energy/Real Energy Into the Load",
        "Lighting.SDB-18_L/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G2-1_380V_AG_FA/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G2-2_240V_AG_FA/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G2-2_415V_AG_FA/Energies/Real Energy/Real Energy Into the Load",
    ],
    "AG Painting": [
        "Airconditioning.AC_Seasoning_Room_Outdoor/Energies/Energy/Active Energy Delivered",
        "Dust_Collector.PP-G0-142_Dust_Collector/Energies/Real Energy/Real Energy Into the Load",
        "Lighting.SDB-15_L_AG_Paint/Energies/Real Energy/Real Energy Into the Load",
        "Paintshop.PP-G4-118_AG_AHU_AG_Paint/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.AG_5kVA_Fire_Paint_UPS/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.AG_Paint_High_Speed_Shutter1/Energies/Energy/Active Energy Delivered",
        "Production_Power.AG_Paint_High_Speed_Shutter2/Energies/Energy/Active Energy Delivered",
        "Production_Power.AG_Paint_High_Speed_Shutter3/Energies/Energy/Active Energy Delivered",
        "Production_Power.AG_Paint_High_Speed_Shutter4/Energies/Energy/Active Energy Delivered",
        "Production_Power.AG_Paintshop_lighting/Energies/Energy/Active Energy Delivered",
        "Production_Power.Acetone_Industrial_Socket/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.Acetone_Recycler_Machine/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G3-2_415V_AG_Paint/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.SDB-16_P_AG_Paint/Energies/Real Energy/Real Energy Into the Load",
    ],
    "AG Assy": [
        "Production_Power.PP-G3-1_380V_AG_Paint/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G3-2_240V_AG_Paint/Energies/Real Energy/Real Energy Into the Load",
    ],
    "Painting Printing": [
        "Airconditioning.AC_PK_Paint_Shop/Energies/Real Energy/Real Energy Into the Load",
        "Airconditioning.PP_PK_Paint_Chiller/Energies/Real Energy/Real Energy Into the Load",
        "Paintshop.PP-PK_Paint/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PK_Paint_Sliding_Door_1_And_2/Energies/Real Energy/Real Energy Into the Load",
    ],
    "PK Assy": [
        "Airconditioning.PK_Inspection_Box2-AC/Energies/Real Energy/Real Energy Into the Load",
        "Airconditioning.PK_Inspection_Box4-AC/Energies/Real Energy/Real Energy Into the Load",
        "Airconditioning.PK_Inspection_Box5-Ac/Energies/Real Energy/Real Energy Into the Load",
        "Lighting.SDB-11_L_Paint/Energies/Real Energy/Real Energy Into the Load",
        "Other.SDB_18_P_UPS/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-PK1_PK_Assembly/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.SDB-12_P_Paint/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.SDB-21_P_PK_Assembly_Extn/Energies/Real Energy/Real Energy Into the Load",
    ],
    "PA WW Process": [
        "Dust_Collector.G0_144_Dust_Collector/Energies/Real Energy/Real Energy Into the Load",
        "Lighting.SDB-20_L_PA_WW/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-PA-1_Wood_Finish/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-PA1-Wood_Work/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.SDB-20_P_PA_WW/Energies/Real Energy/Real Energy Into the Load",
    ],
    "PA Painting": [
        "Dust_Collector.Dust_Collector/Energies/Real Energy/Real Energy Into the Load",
        "Lighting.SDB-19_L_PA_Paint/Energies/Real Energy/Real Energy Into the Load",
        "Paintshop.PP-PA_Paint_240V/Energies/Real Energy/Real Energy Into the Load",
        "Paintshop.PP-PA_Paint_415V/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PA_HighSpeed_Paint_Shutter/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PA_High_Speed_Paint_Shutter/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PA_Paint_High_Speed_Shutter-5kVA_UPS/Energies/Energy/Active Energy Delivered",
        "Production_Power.SDB-20_P_PA_Paint/Energies/Real Energy/Real Energy Into the Load",
    ],
    "PA Assy": [
        "Airconditioning.PA_FA_Inspection_Box-AC/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PA_FA_12kVA_UPS/Energies/Energy/Active Energy Delivered",
    ],
    "Material W/H": [
        "Lighting.SDB-5_L_Hazardous_W_H/Energies/Real Energy/Real Energy Into the Load",
        "Other.PDB-7_Forklift/Energies/Real Energy/Real Energy Into the Load",
        "Other.SDB-2_P_SWH/Energies/Real Energy/Real Energy Into the Load",
    ],
    "Production Prepare": [
        "Production_Power.Butt_Welding_Machine/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G1-3_AG_WW/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-G5_380V_Maintenance/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.Universal_Grinding_Tool/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.Wood_Mizer_Blade_Grinder/Energies/Real Energy/Real Energy Into the Load",
    ],
    "Production Improve": [
        "Airconditioning.Chiller_1/Energies/Real Energy/Real Energy Into the Load",
        "Airconditioning.Chiller_2/Energies/Real Energy/Real Energy Into the Load",
        "Airconditioning.Chiller_3/Energies/Real Energy/Real Energy Into the Load",
        "Lighting.SDB-13_L_Moulding/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-10_450T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-11_650T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-12_850T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-13AB_1300T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-13_1300T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-16_230T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-17_280T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-18_350T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-19_350T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-20AB_1600T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-20_1600T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-3_100T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-5_180T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-8_350T/Energies/Real Energy/Real Energy Into the Load",
        "Molding.PP-PK2-9_450T/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PDB-11_PK_Moulding/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-PK2-15_Crush_Room/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-PK2-1_Moulding_Chiller/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PP-PK3-1_Mould_Maintenance/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.SDB-14_P_Moulding/Energies/Real Energy/Real Energy Into the Load",
    ],
    "Process Inspection": [
        "Airconditioning.Chiller/Energies/Real Energy/Real Energy Into the Load",
        "Airconditioning.PA_OQC_Inspection_Box_AC/Energies/Real Energy/Real Energy Into the Load",
        "Airconditioning.PP-G3-3_415V_Chamber_AG_Paint/Energies/Real Energy/Real Energy Into the Load",
        "Other.PDB-15_QA_Room/Energies/Real Energy/Real Energy Into the Load",
        "Production_Power.PA_OQC_5kVA_UPS/Energies/Real Energy/Real Energy Into the Load",
    ],
    "Logistics & Shipping": [
        "Lighting.SDB-1_L_SWH/Energies/Real Energy/Real Energy Into the Load",
        "Other.SDB_SWH/Energies/Real Energy/Real Energy Into the Load",
    ],
}

# 11 Equipment Category Configs (Section 11)
CATEGORY_CONFIG = {
    "HT_Room": {"prefix": "HT_Room.", "suffix": "/Energy/kWh del"},
    "North_Utilities": {"prefix": "Incomer.North_Utilities_2000KVA_Transformer/", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
    "Lighting": {"prefix": "Lighting.", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
    "Molding": {"prefix": "Molding.", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
    "Dust_Collector": {"prefix": "Dust_Collector.", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
    "Compressor": {"prefix": "Compressor.", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
    "Paintshop": {"prefix": "Paintshop.", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
    "Other": {"prefix": "Other.", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
    "Others": {"prefix": "Others.", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
    "Airconditioning": {"prefix": "Airconditioning.", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
    "Production_Power": {"prefix": "Production_Power.", "suffix": "Energies/Real Energy/Real Energy Into the Load"},
}

def get_cost_center_tags(cost_center: str) -> List[str]:
    """Retrieve explicit tag list for a given cost center."""
    return COST_CENTER_MAPPINGS.get(cost_center, [])

def get_all_cost_centers() -> List[str]:
    """Return all 17 cost center names."""
    return list(COST_CENTER_MAPPINGS.keys())

def is_tag_excluded_from_category(tag_id: str) -> bool:
    """Check if tag is excluded from its equipment category total."""
    return tag_id in CATEGORY_EXCLUDED_TAGS
