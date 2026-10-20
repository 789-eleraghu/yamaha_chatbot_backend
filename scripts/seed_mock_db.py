#!/usr/bin/env python3
"""
Seed Script for Yamaha EMS Mock Data (SQLite)
Based on: energy-ai-assistant-reference.md

Generates 50 days of realistic industrial EMS data adhering to:
1. opcda_readings (raw readings)
2. tag_daily_energy_rollup (daily aggregates: date, tag_id, min_value, max_value, energy)
3. Full tag inventory:
   - 17 Cost Centers (Section 13)
   - 11 Equipment Categories & 8-category subset (Section 11 & 12)
   - Exclusions: G0_144_Dust_Collector & PA_FA_Inspection_Box-AC
   - Peak Demand excursions (> 1180 kVA on transformer, Section 4)
   - DG runs (> 1.0 kW real power, runtime, start/stop, energy, Section 5)
   - Harmonics / THD (Voltage limit 5%, Current limit 8%, Section 6)
   - Reactive Energy (HT_Room and North_Utilities, Section 7)
   - Steam Flow Rate, Pressure, Totalizer (Section 8)
   - Shift-wise consumption: Shift A, B, C with 00:40 boundary (Section 9)
   - Time of Day (TOD) Tariff bands (HT_1, Section 3)
   - Power Factor scaling (0-100 scale, Section 14)
"""

import argparse
import datetime
import math
import os
import random
import sqlite3
import sys
import time

# ---------------------------------------------------------
# Tag Catalog Definitions
# ---------------------------------------------------------

# 17 Cost Center Tag Mappings (Section 13)
COST_CENTER_TAGS = {
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

# Unmapped / conflict devices (Section 13 & 15)
UNMAPPED_TAGS = [
    "Airconditioning.Air_Conditioning-1/Energies/Energy/Active Energy Delivered",
    "Airconditioning.Air_Conditioning-2/Energies/Energy/Active Energy Delivered",
]

# Additional category tags & Incomers
ADDITIONAL_CATEGORY_ENERGY_TAGS = [
    # Others category
    "Others.Server_Room/Energies/Real Energy/Real Energy Into the Load",
    # HT_Room (Main Incomer and South Utilities Transformer)
    "HT_Room.11kV_Main_Incomer/Energy/kWh del",
    "HT_Room.11kV_Main_Incomer/Energy/kVAh del",
    "HT_Room.South_Utilities_1000kVA_Transformer/Energy/kWh del",
    "HT_Room.South_Utilities_1000kVA_Transformer/Energy/kVAh del",
    # North Utilities Transformer
    "Incomer.North_Utilities_2000KVA_Transformer/Energies/Real Energy/Real Energy Into the Load",
    "Incomer.North_Utilities_2000KVA_Transformer/Energies/Apparent Energy/Apparent Energy Into the Load",
    # Facility Source Meters (Section 11)
    "Incomer.Incomer_Solar_100kW/Energies/Real Energy/Real Energy Into the Load",
    "Incomer.DG_Incomer_300kVA/Energies/Real Energy/Real Energy Into the Load",
]

# Reactive Energy Tags (Section 7)
REACTIVE_ENERGY_TAGS = [
    "HT_Room.South_Utilities_1000kVA_Transformer/Energies/Reactive Energy/Reactive Energy Into the Load",
    "Incomer.North_Utilities_2000KVA_Transformer/Energies/Reactive Energy/Reactive Energy Into the Load",
]

# Peak Demand & Power Quality (Authoritative Transformer, Section 4 & 6)
TRANSFORMER_PREFIX = "HT_Room.South_Utilities_1000kVA_Transformer/"
APPARENT_POWER_TAG = f"{TRANSFORMER_PREFIX}Powers/Apparent Power/Apparent Power Total"
REAL_POWER_TOTAL_TAG = f"{TRANSFORMER_PREFIX}Powers/Real Power/Real Power Total"
REACTIVE_POWER_TOTAL_TAG = f"{TRANSFORMER_PREFIX}Powers/Reactive Power/Reactive Power Total"
POWER_FACTOR_TAG = f"{TRANSFORMER_PREFIX}Power Factors/Power Factor Total/Power Factor Total"
FREQUENCY_TAG = f"{TRANSFORMER_PREFIX}Miscellaneous/Frequency/Frequency"
VOLTAGE_LN_AVG_TAG = f"{TRANSFORMER_PREFIX}Voltages/Voltage/Voltage L-N Avg"
VOLTAGE_AN_TAG = f"{TRANSFORMER_PREFIX}Voltages/Voltage/Voltage A-N"
VOLTAGE_BN_TAG = f"{TRANSFORMER_PREFIX}Voltages/Voltage/Voltage B-N"
VOLTAGE_CN_TAG = f"{TRANSFORMER_PREFIX}Voltages/Voltage/Voltage C-N"
CURRENT_AVG_TAG = f"{TRANSFORMER_PREFIX}Currents/Current/Current Avg"
CURRENT_A_TAG = f"{TRANSFORMER_PREFIX}Currents/Current/Current A"
CURRENT_B_TAG = f"{TRANSFORMER_PREFIX}Currents/Current/Current B"
CURRENT_C_TAG = f"{TRANSFORMER_PREFIX}Currents/Current/Current C"

VOLTAGE_THD_TAGS = [
    f"{TRANSFORMER_PREFIX}Power Quality/THD Voltage/THD Voltage A-N",
    f"{TRANSFORMER_PREFIX}Power Quality/THD Voltage/THD Voltage B-N",
    f"{TRANSFORMER_PREFIX}Power Quality/THD Voltage/THD Voltage C-N",
    f"{TRANSFORMER_PREFIX}Power Quality/THD Voltage/THD Voltage L-N",
]

CURRENT_THD_TAGS = [
    f"{TRANSFORMER_PREFIX}Power Quality/THD Current/THD Current A",
    f"{TRANSFORMER_PREFIX}Power Quality/THD Current/THD Current B",
    f"{TRANSFORMER_PREFIX}Power Quality/THD Current/THD Current C",
]

# DG Real Power Tag for Run Detection (Section 5)
DG_REAL_POWER_TAG = "Incomer.DG_Incomer_300kVA/Powers/Real Power/Real Power Total"

# Steam Tags (Section 8)
STEAM_FLOW_RATE_TAG = "Flowmeter-Gate1.Blower_Room_Steam/Flow Rate"
STEAM_PRESSURE_TAG = "Flowmeter-Gate1.Blower_Room_Steam/Pressure"
STEAM_TOTALIZER_TAG = "Flowmeter-Gate1.Blower_Room_Steam/Totalizer"

# Representative Live Monitoring Devices (Section 14)
REPRESENTATIVE_LIVE_DEVICES = {
    "Incomer.North_Utilities_2000KVA_Transformer/": {
        "kw": 450.0,
        "pf_path": "Power Factors/Power Factor Total/Power Factor Total",
        "freq_path": "Miscellaneous/Frequency/Frequency",
    },
    "Lighting.SDB-9_L_Office/": {
        "kw": 18.0,
        "pf_path": "Power Factors/Power Factor/Power Factor Total",
        "freq_path": "Power Meters/Power Meter/Frequency",
    },
    "Molding.PP-PK2-20_1600T/": {
        "kw": 140.0,
        "pf_path": "Power Factors/Power Factor/Power Factor Total",
        "freq_path": "Power Meters/Power Meter/Frequency",
    },
    "Compressor.Compressor_1/": {
        "kw": 75.0,
        "pf_path": "Power Factors/Power Factor/Power Factor Total",
        "freq_path": "Power Meters/Power Meter/Frequency",
    },
    "Paintshop.PP-G4-118_AG_AHU_AG_Paint/": {
        "kw": 45.0,
        "pf_path": "Power Factors/Power Factor/Power Factor Total",
        "freq_path": "Power Meters/Power Meter/Frequency",
    },
    "Airconditioning.Chiller/": {
        "kw": 110.0,
        "pf_path": "Power Factors/Power Factor Total/Power Factor Total",
        "freq_path": "Miscellaneous/Frequency/Frequency",
    },
    "Production_Power.PP-G1-1_380V_AG_WW/": {
        "kw": 60.0,
        "pf_path": "Power Factors/Power Factor/Power Factor Total",
        "freq_path": "Power Meters/Power Meter/Frequency",
    },
    "Incomer.Incomer_Solar_100kW/": {
        "kw": 40.0,
        "pf_path": "Power Factors/Power Factor Total/Power Factor Total",
        "freq_path": "Miscellaneous/Frequency/Frequency",
    },
}

# ---------------------------------------------------------
# Helper Functions for Realistic Data Generation
# ---------------------------------------------------------

def get_day_type(date_obj):
    """0-4: Weekday, 5: Saturday, 6: Sunday."""
    weekday = date_obj.weekday()
    if weekday == 6:
        return "sunday"
    elif weekday == 5:
        return "saturday"
    return "weekday"


def get_tariff_band(hour):
    """
    Tariff Bands (HT_1):
    00:00-04:59: Off-Peak (7.125)
    05:00-05:59: Normal (7.500)
    06:00-09:59: Peak (9.375)
    10:00-17:59: Normal (7.500)
    18:00-21:59: Peak (9.375)
    22:00-23:59: Off-Peak (7.125)
    """
    if (0 <= hour <= 4) or (22 <= hour <= 23):
        return "off_peak", 7.125
    elif (6 <= hour <= 9) or (18 <= hour <= 21):
        return "peak", 9.375
    else:
        return "normal", 7.500


def get_hourly_load_factor(hour, day_type):
    """Returns load factor (0.0 to 1.5) depending on hour and day type."""
    if day_type == "sunday":
        base = 0.35 + 0.1 * math.sin((hour - 8) / 12 * math.pi)
        return max(0.25, base)

    # Shift patterns:
    # Shift C (00:40 - 08:00): base load ~0.55 - 0.70
    # Shift A (08:00 - 17:00): peak production ~1.10 - 1.35
    # Shift B (17:00 - 00:40): evening production ~0.85 - 1.05
    if 0 <= hour < 8:
        base = 0.55 + 0.1 * math.sin(hour / 8 * math.pi)
    elif 8 <= hour < 17:
        base = 1.15 + 0.15 * math.sin((hour - 8) / 9 * math.pi)
    else:
        base = 0.90 + 0.12 * math.sin((hour - 17) / 7 * math.pi)

    if day_type == "saturday":
        base *= 0.85
    return max(0.4, base)


# ---------------------------------------------------------
# Main Seeder Class
# ---------------------------------------------------------

class MockDatabaseSeeder:
    def __init__(self, db_path, days=50, end_date=None):
        self.db_path = db_path
        self.days = days
        if end_date:
            self.end_date = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            self.end_date = datetime.date(2026, 10, 20)
        self.start_date = self.end_date - datetime.timedelta(days=self.days - 1)
        self.conn = None

    def connect(self):
        # Remove existing db if needed, or connect
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA synchronous = OFF;")
        self.conn.execute("PRAGMA journal_mode = MEMORY;")
        self.conn.execute("PRAGMA cache_size = 100000;")

    def create_schema(self):
        cursor = self.conn.cursor()
        print("Creating SQLite tables matching ClickHouse schema...")
        cursor.execute("""
            CREATE TABLE opcda_readings (
                tag_id TEXT NOT NULL,
                reading_timestamp TEXT NOT NULL,
                value REAL NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE tag_daily_energy_rollup (
                date TEXT NOT NULL,
                tag_id TEXT NOT NULL,
                min_value REAL NOT NULL,
                max_value REAL NOT NULL,
                energy REAL NOT NULL
            );
        """)
        self.conn.commit()

    def build_all_energy_tags(self):
        """Collect all distinct cumulative energy tags and assign nominal ratings."""
        all_tags = {}

        # 1. Cost Center tags
        for cc_name, tags in COST_CENTER_TAGS.items():
            for t in tags:
                if "Compressor" in t:
                    nominal_kw = 55.0
                elif "Chiller" in t or "Moulding" in t or "1600T" in t or "1300T" in t:
                    nominal_kw = 80.0
                elif "AC" in t or "Airconditioning" in t or "Air_Conditioning" in t:
                    nominal_kw = 18.0
                elif "Lighting" in t or "SDB" in t:
                    nominal_kw = 6.0
                elif "Dust_Collector" in t:
                    nominal_kw = 22.0
                elif "Paint" in t:
                    nominal_kw = 35.0
                elif "UPS" in t:
                    nominal_kw = 8.0
                else:
                    nominal_kw = 15.0
                all_tags[t] = nominal_kw

        # 2. Unmapped / conflict tags
        for t in UNMAPPED_TAGS:
            all_tags[t] = 16.0

        # 3. Additional category tags
        for t in ADDITIONAL_CATEGORY_ENERGY_TAGS:
            if "11kV_Main_Incomer" in t or "South_Utilities" in t or "North_Utilities" in t:
                nominal_kw = 450.0
            elif "Solar" in t:
                nominal_kw = 45.0  # solar generation
            elif "DG" in t:
                nominal_kw = 0.0   # handled by DG runs
            else:
                nominal_kw = 25.0
            all_tags[t] = nominal_kw

        # 4. Reactive energy tags
        for t in REACTIVE_ENERGY_TAGS:
            all_tags[t] = 120.0  # kVAR nominal

        return all_tags

    def generate_dg_schedule(self):
        """
        Generate 5 distinct DG test / emergency runs across 50 days (Section 5).
        Returns dict: day_idx -> list of (start_min, duration_min, power_kw)
        """
        # Spread runs across dates: e.g. Day 8, Day 19, Day 31, Day 42, Day 48
        dg_runs = {
            7: [(600, 65, 85.0)],     # Day 8, 10:00 IST, 65 mins, 85 kW
            18: [(840, 90, 115.0)],   # Day 19, 14:00 IST, 90 mins, 115 kW
            30: [(480, 45, 70.0)],    # Day 31, 08:00 IST, 45 mins, 70 kW
            41: [(960, 120, 140.0)],  # Day 42, 16:00 IST, 120 mins, 140 kW
            47: [(660, 50, 95.0)],    # Day 48, 11:00 IST, 50 mins, 95 kW
        }
        return dg_runs

    def generate_peak_demand_schedule(self):
        """
        Generate peak events exceeding threshold 1180 kVA on transformer (Section 4).
        Contracted = 1475 kVA, threshold = 1180 kVA.
        Spread 4 peak events across 50 days.
        Returns dict: day_idx -> list of (start_min, duration_min, peak_kva)
        """
        peak_events = {
            10: (630, 35, 1245.0),  # Day 11: 10:30 IST, 35 mins, 1245 kVA
            22: (870, 40, 1285.0),  # Day 23: 14:30 IST, 40 mins, 1285 kVA
            35: (690, 25, 1210.0),  # Day 36: 11:30 IST, 25 mins, 1210 kVA
            46: (910, 45, 1315.0),  # Day 47: 15:10 IST, 45 mins, 1315 kVA
        }
        return peak_events

    def seed_data(self):
        start_time = time.time()
        print(f"Generating mock data for {self.days} days:")
        print(f"  Range: {self.start_date} to {self.end_date} (IST)")

        energy_tags = self.build_all_energy_tags()
        print(f"  Total cumulative energy tags: {len(energy_tags)}")

        # Initialize cumulative counters with realistic non-zero bases
        random.seed(42)
        counters = {}
        for tag, nominal in energy_tags.items():
            counters[tag] = random.uniform(150000.0, 850000.0)

        # Steam totalizer initial counter (kg)
        steam_totalizer = 2450000.0

        dg_schedule = self.generate_dg_schedule()
        peak_schedule = self.generate_peak_demand_schedule()

        raw_readings_batch = []
        rollup_batch = []
        BATCH_SIZE = 50000

        cursor = self.conn.cursor()

        total_raw_rows = 0
        total_rollup_rows = 0

        # Loop through each of the 50 days
        for day_idx in range(self.days):
            current_date = self.start_date + datetime.timedelta(days=day_idx)
            date_str = current_date.strftime("%Y-%m-%d")
            day_type = get_day_type(current_date)

            # Record baseline at 00:00:00 for start of day
            day_first_reading = {}
            for tag in energy_tags:
                r_val = round(counters[tag], 2)
                day_first_reading[tag] = r_val
                raw_readings_batch.append((tag, f"{date_str} 00:00:00", r_val))

            steam_first_reading = round(steam_totalizer, 1)
            raw_readings_batch.append((STEAM_TOTALIZER_TAG, f"{date_str} 00:00:00", steam_first_reading))

            # Track 1-minute values for peak demand and DG
            peak_info = peak_schedule.get(day_idx)
            dg_runs_today = dg_schedule.get(day_idx, [])

            # We will generate readings:
            # 1. 10-minute intervals for all cumulative energy counters (00:10, 00:20, ..., 23:50, 23:59)
            # 2. 1-minute intervals for:
            #    - Apparent Power Total (Transformer)
            #    - Real Power Total (Transformer)
            #    - DG Real Power Total
            #    - THD Voltage (4 tags) & THD Current (3 tags)
            # 3. 10-minute intervals for Steam Flow Rate, Pressure, Totalizer
            # 4. 10-minute intervals for Representative Live Device parameters

            for minute_of_day in range(1440):
                hour = minute_of_day // 60
                minute = minute_of_day % 60
                ts_str = f"{date_str} {hour:02d}:{minute:02d}:00"
                load_factor = get_hourly_load_factor(hour, day_type)

                # --- 1-MINUTE HIGH RESOLUTION TAGS ---

                # A. Peak Demand Apparent Power (Section 4)
                noise_kva = random.uniform(-15.0, 15.0)
                base_kva = (680.0 + 320.0 * load_factor) + noise_kva

                if peak_info:
                    p_start, p_dur, p_peak = peak_info
                    if p_start <= minute_of_day < p_start + p_dur:
                        progress = (minute_of_day - p_start) / p_dur
                        shape = math.sin(progress * math.pi)
                        base_kva = 1185.0 + (p_peak - 1185.0) * shape + random.uniform(-5.0, 5.0)

                raw_readings_batch.append((APPARENT_POWER_TAG, ts_str, round(base_kva, 2)))

                # Transformer Real Power
                real_power_trans = base_kva * random.uniform(0.92, 0.95)
                raw_readings_batch.append((REAL_POWER_TOTAL_TAG, ts_str, round(real_power_trans, 2)))

                # B. DG Real Power (Section 5)
                dg_kw = 0.0
                for r_start, r_dur, r_kw in dg_runs_today:
                    if r_start <= minute_of_day < r_start + r_dur:
                        dg_kw = r_kw + random.uniform(-2.5, 2.5)
                        break
                raw_readings_batch.append((DG_REAL_POWER_TAG, ts_str, round(dg_kw, 2)))

                # C. Harmonics / THD (Section 6)
                v_thd_base = 2.4 + 0.6 * load_factor + random.uniform(-0.15, 0.15)
                if hour in (11, 15) and day_type == "weekday":
                    v_thd_base += 1.2
                raw_readings_batch.append((VOLTAGE_THD_TAGS[0], ts_str, round(v_thd_base + 0.05, 2)))
                raw_readings_batch.append((VOLTAGE_THD_TAGS[1], ts_str, round(v_thd_base - 0.04, 2)))
                raw_readings_batch.append((VOLTAGE_THD_TAGS[2], ts_str, round(v_thd_base + 0.02, 2)))
                raw_readings_batch.append((VOLTAGE_THD_TAGS[3], ts_str, round(v_thd_base, 2)))

                c_thd_base = 4.8 + 1.8 * load_factor + random.uniform(-0.3, 0.3)
                if hour in (14, 19) and day_type == "weekday":
                    c_thd_base += 2.0
                raw_readings_batch.append((CURRENT_THD_TAGS[0], ts_str, round(c_thd_base + 0.15, 2)))
                raw_readings_batch.append((CURRENT_THD_TAGS[1], ts_str, round(c_thd_base - 0.10, 2)))
                raw_readings_batch.append((CURRENT_THD_TAGS[2], ts_str, round(c_thd_base + 0.05, 2)))

                # --- 10-MINUTE INTERVAL RESOLUTION ---
                # Sample at :10, :20, :30, :40, :50, and at end of hour :59 (:00 was recorded at day start or prev hour)
                is_sample_point = (minute in (10, 20, 30, 40, 50)) or (minute == 59 and hour == 23)
                if is_sample_point:
                    step_hours = 10.0 / 60.0 if minute != 59 else 9.0 / 60.0

                    # 1. Update cumulative energy counters
                    for tag, nominal_kw in energy_tags.items():
                        if "Incomer_Solar" in tag:
                            if 7 <= hour <= 16:
                                sun_factor = math.sin((hour + minute / 60.0 - 6.5) / 11.0 * math.pi)
                                solar_kw = max(0.0, nominal_kw * sun_factor + random.uniform(-2.0, 2.0))
                            else:
                                solar_kw = 0.0
                            delta_kwh = solar_kw * step_hours
                        elif "DG_Incomer" in tag:
                            delta_kwh = dg_kw * step_hours
                        elif "11kV_Main_Incomer" in tag:
                            effective_kw = (1200.0 + 900.0 * load_factor) + random.uniform(-20.0, 20.0)
                            if "kVAh" in tag:
                                effective_kw /= 0.94
                            delta_kwh = effective_kw * step_hours
                        elif "South_Utilities" in tag or "North_Utilities" in tag:
                            effective_kw = (nominal_kw * 0.7 + nominal_kw * 0.6 * load_factor) + random.uniform(-5.0, 5.0)
                            if "Apparent" in tag or "kVAh" in tag:
                                effective_kw /= 0.93
                            elif "Reactive" in tag:
                                effective_kw *= 0.35
                            delta_kwh = effective_kw * step_hours
                        elif "Reactive" in tag:
                            delta_kwh = (nominal_kw * 0.3 * load_factor) * step_hours
                        else:
                            delta_kwh = (nominal_kw * load_factor + random.uniform(-0.1 * nominal_kw, 0.1 * nominal_kw)) * step_hours

                        delta_kwh = max(0.001, delta_kwh)
                        counters[tag] += delta_kwh
                        raw_readings_batch.append((tag, ts_str, round(counters[tag], 2)))

                    # 2. Steam readings (Section 8)
                    if day_type == "sunday":
                        steam_flow = 120.0 + random.uniform(-10.0, 10.0)
                        steam_press = 5.2 + random.uniform(-0.2, 0.2)
                    else:
                        steam_flow = (320.0 + 380.0 * load_factor) + random.uniform(-15.0, 15.0)
                        steam_press = (6.0 + 0.8 * load_factor) + random.uniform(-0.15, 0.15)

                    steam_delta = steam_flow * step_hours
                    steam_totalizer += steam_delta

                    raw_readings_batch.append((STEAM_FLOW_RATE_TAG, ts_str, round(steam_flow, 1)))
                    raw_readings_batch.append((STEAM_PRESSURE_TAG, ts_str, round(steam_press, 2)))
                    raw_readings_batch.append((STEAM_TOTALIZER_TAG, ts_str, round(steam_totalizer, 1)))

                    # 3. Transformer Voltage, Current, Frequency, Power Factor (Section 14)
                    raw_readings_batch.append((VOLTAGE_LN_AVG_TAG, ts_str, round(238.5 + random.uniform(-2.5, 2.5), 1)))
                    raw_readings_batch.append((VOLTAGE_AN_TAG, ts_str, round(239.0 + random.uniform(-2.5, 2.5), 1)))
                    raw_readings_batch.append((VOLTAGE_BN_TAG, ts_str, round(238.0 + random.uniform(-2.5, 2.5), 1)))
                    raw_readings_batch.append((VOLTAGE_CN_TAG, ts_str, round(238.5 + random.uniform(-2.5, 2.5), 1)))

                    curr_avg = (base_kva * 1000.0) / (3.0 * 238.5)
                    raw_readings_batch.append((CURRENT_AVG_TAG, ts_str, round(curr_avg, 1)))
                    raw_readings_batch.append((CURRENT_A_TAG, ts_str, round(curr_avg * 1.01, 1)))
                    raw_readings_batch.append((CURRENT_B_TAG, ts_str, round(curr_avg * 0.99, 1)))
                    raw_readings_batch.append((CURRENT_C_TAG, ts_str, round(curr_avg * 1.00, 1)))

                    pf_val = 94.0 + random.uniform(-1.5, 1.5)
                    raw_readings_batch.append((POWER_FACTOR_TAG, ts_str, round(pf_val, 1)))
                    raw_readings_batch.append((FREQUENCY_TAG, ts_str, round(50.0 + random.uniform(-0.12, 0.12), 2)))

                    # 4. Representative Live Monitoring Devices (Section 14)
                    for dev_prefix, dev_meta in REPRESENTATIVE_LIVE_DEVICES.items():
                        nom_kw = dev_meta["kw"]
                        actual_kw = max(0.5, nom_kw * load_factor + random.uniform(-0.1 * nom_kw, 0.1 * nom_kw))
                        raw_readings_batch.append((f"{dev_prefix}Powers/Real Power/Real Power Total", ts_str, round(actual_kw, 2)))
                        raw_readings_batch.append((f"{dev_prefix}{dev_meta['pf_path']}", ts_str, round(93.0 + random.uniform(-2.0, 2.0), 1)))
                        raw_readings_batch.append((f"{dev_prefix}{dev_meta['freq_path']}", ts_str, round(50.0 + random.uniform(-0.1, 0.1), 2)))
                        raw_readings_batch.append((f"{dev_prefix}Voltages/Voltage/Voltage L-N Avg", ts_str, round(239.0 + random.uniform(-2.0, 2.0), 1)))

                # Flush raw readings batch if threshold reached
                if len(raw_readings_batch) >= BATCH_SIZE:
                    cursor.executemany("INSERT INTO opcda_readings VALUES (?, ?, ?);", raw_readings_batch)
                    total_raw_rows += len(raw_readings_batch)
                    raw_readings_batch.clear()

            # --- END OF DAY: RECORD DAILY ROLLUP (Section 1 & 2) ---
            for tag, start_val in day_first_reading.items():
                end_val = round(counters[tag], 2)
                energy_consumed = round(end_val - start_val, 2)
                rollup_batch.append((date_str, tag, start_val, end_val, energy_consumed))

            # Daily rollup for Steam Totalizer
            steam_end = round(steam_totalizer, 1)
            steam_consumed = round(steam_end - steam_first_reading, 1)
            rollup_batch.append((date_str, STEAM_TOTALIZER_TAG, steam_first_reading, steam_end, steam_consumed))

            if len(rollup_batch) >= 5000:
                cursor.executemany("INSERT INTO tag_daily_energy_rollup VALUES (?, ?, ?, ?, ?);", rollup_batch)
                total_rollup_rows += len(rollup_batch)
                rollup_batch.clear()

            print(f"  Processed Day {day_idx + 1:2d}/{self.days} ({date_str}) [{day_type}] - Cumulative kWh: {counters['HT_Room.11kV_Main_Incomer/Energy/kWh del']:,.1f}")

        # Flush any remaining rows
        if raw_readings_batch:
            cursor.executemany("INSERT INTO opcda_readings VALUES (?, ?, ?);", raw_readings_batch)
            total_raw_rows += len(raw_readings_batch)
            raw_readings_batch.clear()

        if rollup_batch:
            cursor.executemany("INSERT INTO tag_daily_energy_rollup VALUES (?, ?, ?, ?, ?);", rollup_batch)
            total_rollup_rows += len(rollup_batch)
            rollup_batch.clear()

        self.conn.commit()

        # Build Indexes
        print("\nCreating SQLite indexes for high-speed queries...")
        idx_start = time.time()
        cursor.execute("CREATE INDEX idx_opcda_tag_ts ON opcda_readings(tag_id, reading_timestamp);")
        cursor.execute("CREATE INDEX idx_opcda_ts ON opcda_readings(reading_timestamp);")
        cursor.execute("CREATE INDEX idx_rollup_tag_date ON tag_daily_energy_rollup(tag_id, date);")
        cursor.execute("CREATE INDEX idx_rollup_date ON tag_daily_energy_rollup(date);")
        self.conn.commit()
        print(f"Indexes built in {time.time() - idx_start:.2f} seconds.")

        total_elapsed = time.time() - start_time
        db_file_size_mb = os.path.getsize(self.db_path) / (1024 * 1024)

        print("\n" + "="*60)
        print("SEEDING COMPLETE!")
        print("="*60)
        print(f"Database Path:         {self.db_path}")
        print(f"Database Size:         {db_file_size_mb:.2f} MB")
        print(f"Total Raw Rows:        {total_raw_rows:,}")
        print(f"Total Rollup Rows:     {total_rollup_rows:,}")
        print(f"Execution Time:        {total_elapsed:.2f} seconds")
        print("="*60)

    def close(self):
        if self.conn:
            self.conn.close()


def main():
    parser = argparse.ArgumentParser(description="Seed 50 days of Yamaha EMS mock data into SQLite.")
    parser.add_argument("--days", type=int, default=50, help="Number of days to generate (default: 50)")
    parser.add_argument("--db-path", type=str, default="yamaha_mock.db", help="Path to SQLite database file")
    parser.add_argument("--end-date", type=str, default="2026-10-20", help="End date in YYYY-MM-DD (default: 2026-10-20)")

    args = parser.parse_args()

    seeder = MockDatabaseSeeder(db_path=args.db_path, days=args.days, end_date=args.end_date)
    try:
        seeder.connect()
        seeder.create_schema()
        seeder.seed_data()
    finally:
        seeder.close()


if __name__ == "__main__":
    main()
