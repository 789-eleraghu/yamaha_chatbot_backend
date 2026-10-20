"""
Domain Constants for Yamaha EMS
Derived from: energy-ai-assistant-reference.md
"""

# Timezone definition (Section 1)
TIMEZONE = "Asia/Kolkata"

# Tariff HT_1 Configuration (Section 3)
# Band Rates in ₹/kWh:
# 00:00–04:59 (Off-Peak): 7.125
# 05:00–05:59 (Normal):   7.500
# 06:00–09:59 (Peak):     9.375
# 10:00–17:59 (Normal):   7.500
# 18:00–21:59 (Peak):     9.375
# 22:00–23:59 (Off-Peak): 7.125
HOURLY_TARIFF_RATES = {
    0: 7.125, 1: 7.125, 2: 7.125, 3: 7.125, 4: 7.125,
    5: 7.500,
    6: 9.375, 7: 9.375, 8: 9.375, 9: 9.375,
    10: 7.500, 11: 7.500, 12: 7.500, 13: 7.500, 14: 7.500, 15: 7.500, 16: 7.500, 17: 7.500,
    18: 9.375, 19: 9.375, 20: 9.375, 21: 9.375,
    22: 7.125, 23: 7.125
}

# Peak Demand Constants (Section 4)
CONTRACTED_DEMAND_KVA = 1475.0
PEAK_DEMAND_THRESHOLD_KVA = 1180.0  # 1475 * 0.8
AUTHORITATIVE_TRANSFORMER_PREFIX = "HT_Room.South_Utilities_1000kVA_Transformer/"
PEAK_DEMAND_TAG = f"{AUTHORITATIVE_TRANSFORMER_PREFIX}Powers/Apparent Power/Apparent Power Total"

# DG Run Detection Constants (Section 5)
DG_DEVICE_PREFIX = "Incomer.DG_Incomer_300kVA/"
DG_ENERGY_TAG = f"{DG_DEVICE_PREFIX}Energies/Real Energy/Real Energy Into the Load"
DG_POWER_TAG = f"{DG_DEVICE_PREFIX}Powers/Real Power/Real Power Total"
DG_RUN_THRESHOLD_KW = 1.0

# Power Quality & THD Limits (Section 6)
VOLTAGE_THD_LIMIT_PERCENT = 5.0
CURRENT_THD_LIMIT_PERCENT = 8.0
VOLTAGE_THD_TAGS = [
    f"{AUTHORITATIVE_TRANSFORMER_PREFIX}Power Quality/THD Voltage/THD Voltage A-N",
    f"{AUTHORITATIVE_TRANSFORMER_PREFIX}Power Quality/THD Voltage/THD Voltage B-N",
    f"{AUTHORITATIVE_TRANSFORMER_PREFIX}Power Quality/THD Voltage/THD Voltage C-N",
    f"{AUTHORITATIVE_TRANSFORMER_PREFIX}Power Quality/THD Voltage/THD Voltage L-N",
]
CURRENT_THD_TAGS = [
    f"{AUTHORITATIVE_TRANSFORMER_PREFIX}Power Quality/THD Current/THD Current A",
    f"{AUTHORITATIVE_TRANSFORMER_PREFIX}Power Quality/THD Current/THD Current B",
    f"{AUTHORITATIVE_TRANSFORMER_PREFIX}Power Quality/THD Current/THD Current C",
]

# Reactive Energy Trustworthy Meters (Section 7)
REACTIVE_ENERGY_TAGS = {
    "HT_Room": f"{AUTHORITATIVE_TRANSFORMER_PREFIX}Energies/Reactive Energy/Reactive Energy Into the Load",
    "North_Utilities": "Incomer.North_Utilities_2000KVA_Transformer/Energies/Reactive Energy/Reactive Energy Into the Load"
}

# Steam System Tags (Section 8)
STEAM_FLOW_RATE_TAG = "Flowmeter-Gate1.Blower_Room_Steam/Flow Rate"
STEAM_PRESSURE_TAG = "Flowmeter-Gate1.Blower_Room_Steam/Pressure"
STEAM_TOTALIZER_TAG = "Flowmeter-Gate1.Blower_Room_Steam/Totalizer"

# Shift Wise Consumption (Section 9)
SHIFT_ENERGY_TAG = "HT_Room.11kV_Main_Incomer/Energy/kWh del"

# Category Rollup Exclusions (Section 11 & 15)
CATEGORY_EXCLUDED_TAGS = {
    "Dust_Collector.G0_144_Dust_Collector/Energies/Real Energy/Real Energy Into the Load",
    "Airconditioning.PA_FA_Inspection_Box-AC/Energies/Real Energy/Real Energy Into the Load"
}

# 8 Equipment-wise Categories (Section 12)
EQUIPMENT_WISE_CATEGORIES = [
    "Lighting",
    "Molding",
    "Dust_Collector",
    "Compressor",
    "Paintshop",
    "Others",
    "Airconditioning",
    "Production_Power"
]
