# Energy AI Assistant — Calculation & Tag Reference

**Purpose:** Implementation reference for an Energy AI Assistant querying Yamaha EMS data.

This document defines:
- what each energy metric means,
- how metrics are calculated,
- which tags/meters are authoritative,
- how zones and cost centers map to tags,
- important data-quality rules and exceptions.

---

## 1. Data source and global rules

### Data source

- **Database:** ClickHouse
- **Database:** `yamaha`
- **Raw table:** `opcda_readings`
- **Daily rollup:** `tag_daily_energy_rollup` / `_mv`
- **Primary source of truth:** `opcda_readings`; daily rollup may be used for day-level calculations.

### Timezone

All timestamps and date boundaries are **IST (`Asia/Kolkata`)**.

A calendar day is:

```text
[00:00 IST, next 00:00 IST)
```

Do not treat timestamps as naive UTC timestamps.

### Energy-counter rule

For cumulative energy counters:

```text
energy = max(counter) - min(counter)
```

Apply this **per tag**, then sum the tag deltas.

Do **not** sum instantaneous power readings to calculate energy.

### Invalid readings

Before calculating `max`/`min`:

```text
toFloat64OrNull(value) > 0
```

Exclude zero, negative, and non-numeric values.

### Missing data

Missing data must return:

```text
null
```

Never fabricate `0` for missing data.

### Rounding

Return computed energy, cost, and power values rounded to **1 decimal place** after calculation.

Tariff rates are not rounded.

---

# 2. Core energy calculation

Most kWh/kVAh/kVARh metrics use:

```text
consumption(window)
    = Σ over matching tags (
        max(reading within window)
        - min(reading within window)
      )
```

A tag may be selected by:

```text
prefix + suffix
```

or by an explicit tag list.

### Day-level calculations

Use the daily rollup where applicable:

```text
maxMerge(max_value) - minMerge(min_value)
```

### Hour-level calculations

Read from `opcda_readings` and bucket by:

```text
toStartOfHour(reading_timestamp)
```

Then calculate:

```text
max(value) - min(value)
```

### Important boundary rule

For multi-period totals, calculate the largest exact period that fits the requested window rather than blindly summing finer-grained deltas. This avoids losing energy at period boundaries.

---

# 3. Cost / tariff

Current tariff: `HT_1`

| IST time | Band | ₹/kWh |
|---|---|---:|
| 00:00–04:59 | Off-Peak | 7.125 |
| 05:00–05:59 | Normal | 7.500 |
| 06:00–09:59 | Peak | 9.375 |
| 10:00–17:59 | Normal | 7.500 |
| 18:00–21:59 | Peak | 9.375 |
| 22:00–23:59 | Off-Peak | 7.125 |

### Cost formula

1. Calculate the true daily kWh using the core energy calculation.
2. Calculate hourly kWh.
3. Rescale hourly values so that:

```text
Σ hourly_kWh = true_daily_kWh
```

with:

```text
scale = true_daily_kWh / Σ(hourly_kWh)
rescaled_hour = hourly_kWh × scale
```

4. Calculate:

```text
cost = Σ(rescaled_hour × tariff_rate_for_hour)
```

Cost is always based on **kWh**, not kVAh.

---

# 4. Peak demand

## Authoritative meter

```text
HT_Room.South_Utilities_1000kVA_Transformer/
```

Peak Demand KPI tag:

```text
HT_Room.South_Utilities_1000kVA_Transformer/Powers/Apparent Power/Apparent Power Total
```

### Peak kVA

```text
peak_kVA = max(apparent_power_total)
```

Use raw instantaneous readings.

Do not use the meter's own pre-computed Demand tags.

### Contracted demand

```text
HT_Room = 1475 kVA
```

### Demand utilization

```text
utilization_% = peak_kVA / 1475 × 100
```

### Peak-event threshold

```text
threshold = 1475 × 0.8 = 1180 kVA
```

A peak event is a contiguous excursion above `1180 kVA`.

Detection uses per-minute maximum values.

Each event contains:

```text
date
time
peakKVA
```

### Hourly peak chart

For each hour:

```text
hourly_peak = max(readings in hour)
```

For windows longer than 24 hours, each hour-of-day uses the **maximum** across the selected days.

---

# 5. DG / Diesel Generator

## Device

```text
Incomer.DG_Incomer_300kVA/
```

### Energy tag

```text
Incomer.DG_Incomer_300kVA/Energies/Real Energy/Real Energy Into the Load
```

### Real-power tag

```text
Incomer.DG_Incomer_300kVA/Powers/Real Power/Real Power Total
```

### Run detection

A DG run starts when real power exceeds:

```text
1.0 kW
```

Detection uses per-minute maximum values.

A contiguous period above the threshold is one run.

An open run has:

```text
stop = null
```

### Monthly metrics

```text
runtimeMinutesThisMonth
    = sum(runtimeMinutes of runs in month)

energyKwhThisMonth
    = cumulative-counter delta of DG energy tag

startsThisMonth
    = runs whose start falls in month

stopsThisMonth
    = runs whose stop falls in month
```

`startsThisMonth` and `stopsThisMonth` can differ because the current run may still be open.

### Last run

The last completed DG run is determined independently of the selected reporting month, using the most recent completed run within the configured lookback.

---

# 6. Harmonics / THD

## Authoritative device

```text
HT_Room.South_Utilities_1000kVA_Transformer/
```

### Voltage THD

| Measurement | Tag suffix |
|---|---|
| Voltage A-N | `Power Quality/THD Voltage/THD Voltage A-N` |
| Voltage B-N | `Power Quality/THD Voltage/THD Voltage B-N` |
| Voltage C-N | `Power Quality/THD Voltage/THD Voltage C-N` |
| Voltage L-N | `Power Quality/THD Voltage/THD Voltage L-N` |

### Current THD

| Measurement | Tag suffix |
|---|---|
| Current A | `Power Quality/THD Current/THD Current A` |
| Current B | `Power Quality/THD Current/THD Current B` |
| Current C | `Power Quality/THD Current/THD Current C` |

### Combined current THD

There is no dedicated total-current THD tag.

Calculate:

```text
current_THD_total
    = average(THD_A, THD_B, THD_C)
```

### Limits

```text
Voltage THD limit = 5%
Current THD limit = 8%
```

**Known inconsistency:** another live UI card currently displays a 15% current-THD limit. Treat `8%` as the backend-configured limit unless the implementation explicitly chooses otherwise.

### Trend calculation

Use one-minute buckets:

```text
avg(value) per tag per minute
```

---

# 7. Reactive energy

Only these two devices currently have trustworthy reactive-energy counters:

| Device | Prefix |
|---|---|
| HT_Room | `HT_Room.South_Utilities_1000kVA_Transformer/` |
| North_Utilities | `Incomer.North_Utilities_2000KVA_Transformer/` |

Tag suffix:

```text
Energies/Reactive Energy/Reactive Energy Into the Load
```

Formula:

```text
kVARh = max(value) - min(value)
```

for the requested IST day/window.

---

# 8. Steam

Steam is the only confirmed non-electrical utility dataset currently available.

## Device

```text
Flowmeter-Gate1.Blower_Room_Steam/
```

| Metric | Tag |
|---|---|
| Flow Rate | `Flow Rate` |
| Pressure | `Pressure` |
| Totalizer | `Totalizer` |

Full tags are:

```text
Flowmeter-Gate1.Blower_Room_Steam/Flow Rate
Flowmeter-Gate1.Blower_Room_Steam/Pressure
Flowmeter-Gate1.Blower_Room_Steam/Totalizer
```

### Current snapshot

Use the latest reading within a **7-day** lookback.

### Steam consumed today

```text
totalizerToday = max(totalizer) - min(totalizer)
```

### Trend

Trailing **3 days**, hourly-average Flow Rate.

### Important limitation

No confirmed real Water or Compressed Air flow/consumption tags currently exist in the namespace.

---

# 9. Shift-wise consumption

## Scope

Shift calculations currently apply only to:

```text
HT_Room
```

## Tag

```text
HT_Room.11kV_Main_Incomer/Energy/kWh del
```

## Shift definitions

| Shift | IST window |
|---|---|
| A | 08:00–17:00 |
| B | 17:00–00:40 next day |
| C | 00:40–08:00 |

For calendar day `D`:

```text
C(D): D 00:40 → D 08:00
A(D): D 08:00 → D 17:00
B(D): D 17:00 → D+1 00:40
```

The period `00:00–00:40` belongs to the previous day's B shift.

### Calculation

Because `00:40` is not an hour boundary, use per-minute last-known values.

For each shift:

```text
shift_kWh
    = counter_at_end_boundary
    - counter_at_start_boundary
```

Boundary values use the nearest reading at or before the exact boundary.

A shift with no qualifying data returns `null`.

---

# 10. Equipment-wise vs Zone-wise

This distinction is critical for interpreting user questions.

| User-facing term | Backend concept | Count | Meaning |
|---|---|---:|---|
| Equipment-wise | `TOP_ZONES_FEEDERS` | 8 | Equipment/category grouping |
| Zone-wise | `COST_CENTER_DEVICES` | 17 | Real organizational cost centers |

### Equipment-wise

Groups meters by equipment category, e.g.:

```text
Lighting
Molding
Compressor
Airconditioning
Production_Power
```

### Zone-wise

Groups explicit devices into organizational cost centers, e.g.:

```text
AG Painting
AG WP Process
Production Improve
```

Do not treat these as interchangeable.

---

# 11. Equipment-category mapping

`ZONE_TAG_CONFIG` contains 11 equipment-category zones.

For a category:

```text
matching tags =
    startsWith(tag_id, prefix)
    AND endsWith(tag_id, suffix)
```

Then calculate energy using the core cumulative-counter formula.

| Zone | Prefix | kWh suffix | kVAh |
|---|---|---|---|
| HT_Room | `HT_Room.` | `/Energy/kWh del` | Yes |
| North_Utilities | `Incomer.North_Utilities_2000KVA_Transformer/` | `Energies/Real Energy/Real Energy Into the Load` | Yes |
| Lighting | `Lighting.` | `Energies/Real Energy/Real Energy Into the Load` | No |
| Molding | `Molding.` | `Energies/Real Energy/Real Energy Into the Load` | No |
| Dust_Collector | `Dust_Collector.` | `Energies/Real Energy/Real Energy Into the Load` | No |
| Compressor | `Compressor.` | `Energies/Real Energy/Real Energy Into the Load` | No |
| Paintshop | `Paintshop.` | `Energies/Real Energy/Real Energy Into the Load` | No |
| Other | `Other.` | `Energies/Real Energy/Real Energy Into the Load` | No |
| Others | `Others.` | `Energies/Real Energy/Real Energy Into the Load` | No |
| Airconditioning | `Airconditioning.` | `Energies/Real Energy/Real Energy Into the Load` | No |
| Production_Power | `Production_Power.` | `Energies/Real Energy/Real Energy Into the Load` | No |

### Category exclusions

Exclude these devices from the category total:

```text
Dust_Collector.G0_144_Dust_Collector/
Airconditioning.PA_FA_Inspection_Box-AC/
```

These exclusions apply only to the category rollups, not to their explicit cost-center mappings.

### Facility source meters

Solar and DG are separate from the 11 category zones and must not be included in category totals:

```text
Solar:
Incomer.Incomer_Solar_100kW/

DG:
Incomer.DG_Incomer_300kVA/
```

Both use:

```text
Energies/Real Energy/Real Energy Into the Load
```

---

# 12. Equipment-wise 8-category subset

The Equipment-wise view uses exactly these 8 categories:

```text
Lighting
Molding
Dust_Collector
Compressor
Paintshop
Others
Airconditioning
Production_Power
```

Excluded from this subset:

```text
HT_Room
North_Utilities
Other
```

---

# 13. Zone-wise cost-center mapping

Cost centers use **explicit complete tag IDs**, not prefix matching.

A cost-center total is:

```text
Σ cumulative-counter-delta(each mapped tag)
```

Only confirmed live mappings should be used.

## General Admin

```text
Airconditioning.PDB-3_Office/Energies/Real Energy/Real Energy Into the Load
Airconditioning.PDB-4_Canteen/Energies/Real Energy/Real Energy Into the Load
Airconditioning.PDB-8_Nursery/Energies/Real Energy/Real Energy Into the Load
Compressor.Compressor_1/Energies/Real Energy/Real Energy Into the Load
Compressor.Compressor_2/Energies/Real Energy/Real Energy Into the Load
Compressor.Compressor_3/Energies/Real Energy/Real Energy Into the Load
Compressor.PDB-12_Compressor/Energies/Real Energy/Real Energy Into the Load
Lighting.SDB-9_L_Office/Energies/Real Energy/Real Energy Into the Load
Lighting.SDB_Ext_Lighting_GH_1/Energies/Real Energy/Real Energy Into the Load
Other.350kVAR_Capacitor/Energies/Real Energy/Real Energy Into the Load
Other.700_kVAR_Capacitor/Energies/Real Energy/Real Energy Into the Load
Other.PDB-10_North_LT_Room/Energies/Real Energy/Real Energy Into the Load
Other.PDB-2_South_LT_Room/Energies/Real Energy/Real Energy Into the Load
Other.PDB-5_Pump_Room/Energies/Real Energy/Real Energy Into the Load
Other.PDB-6_Water_Supply_PUMP_Room/Energies/Real Energy/Real Energy Into the Load
Other.PDB_1_Part_RS_SWH/Energies/Real Energy/Real Energy Into the Load
Other.PDB_YMIN_Site_Office/Energies/Real Energy/Real Energy Into the Load
Other.PP-ETP/Energies/Real Energy/Real Energy Into the Load
Other.SDB-10_Nuresy/Energies/Real Energy/Real Energy Into the Load
Other.SDB-7_L-P_GH2/Energies/Real Energy/Real Energy Into the Load
Other.SDB-8A_P_Canteen/Energies/Real Energy/Real Energy Into the Load
Other.SDB-9A_Office_Power/Energies/Real Energy/Real Energy Into the Load
Other.Vendor_Yard/Energies/Real Energy/Real Energy Into the Load
Production_Power.PDB-9_RS/Energies/Real Energy/Real Energy Into the Load
```

## Information System

```text
Airconditioning.Air_Conditioning-3/Energies/Energy/Active Energy Delivered
Airconditioning.Air_Conditioning-4/Energies/Energy/Active Energy Delivered
```

`Air_Conditioning-1` and `Air_Conditioning-2` are intentionally unmapped because of a conflict with Material W/H.

## AG KILN Dry

```text
Airconditioning.AC_Control_Room_Indoor/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G0-1_Dry_Space_2/Energies/Real Energy/Real Energy Into the Load
```

## AG WP Process

```text
Dust_Collector.G0_143_Dust_Collector/Energies/Real Energy/Real Energy Into the Load
Lighting.SDB-3_L_AG_WW/Energies/Real Energy/Real Energy Into the Load
Production_Power.CNC_Machine_AG_WW/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G1-1_380V_AG_WW/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G1-2_380V_AG_WW/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G1-3_240V_AG_WW/Energies/Real Energy/Real Energy Into the Load
Production_Power.SDB-4_P_AG_WW/Energies/Real Energy/Real Energy Into the Load
```

## AG WW Assy

```text
Dust_Collector.G0_146_Dust_Collector/Energies/Real Energy/Real Energy Into the Load
Lighting.SDB-18_L/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G2-1_380V_AG_FA/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G2-2_240V_AG_FA/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G2-2_415V_AG_FA/Energies/Real Energy/Real Energy Into the Load
```

## AG Painting

```text
Airconditioning.AC_Seasoning_Room_Outdoor/Energies/Energy/Active Energy Delivered
Dust_Collector.PP-G0-142_Dust_Collector/Energies/Real Energy/Real Energy Into the Load
Lighting.SDB-15_L_AG_Paint/Energies/Real Energy/Real Energy Into the Load
Paintshop.PP-G4-118_AG_AHU_AG_Paint/Energies/Real Energy/Real Energy Into the Load
Production_Power.AG_5kVA_Fire_Paint_UPS/Energies/Real Energy/Real Energy Into the Load
Production_Power.AG_Paint_High_Speed_Shutter1/Energies/Energy/Active Energy Delivered
Production_Power.AG_Paint_High_Speed_Shutter2/Energies/Energy/Active Energy Delivered
Production_Power.AG_Paint_High_Speed_Shutter3/Energies/Energy/Active Energy Delivered
Production_Power.AG_Paint_High_Speed_Shutter4/Energies/Energy/Active Energy Delivered
Production_Power.AG_Paintshop_lighting/Energies/Energy/Active Energy Delivered
Production_Power.Acetone_Industrial_Socket/Energies/Real Energy/Real Energy Into the Load
Production_Power.Acetone_Recycler_Machine/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G3-2_415V_AG_Paint/Energies/Real Energy/Real Energy Into the Load
Production_Power.SDB-16_P_AG_Paint/Energies/Real Energy/Real Energy Into the Load
```

## AG Assy

```text
Production_Power.PP-G3-1_380V_AG_Paint/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G3-2_240V_AG_Paint/Energies/Real Energy/Real Energy Into the Load
```

## Painting Printing

```text
Airconditioning.AC_PK_Paint_Shop/Energies/Real Energy/Real Energy Into the Load
Airconditioning.PP_PK_Paint_Chiller/Energies/Real Energy/Real Energy Into the Load
Paintshop.PP-PK_Paint/Energies/Real Energy/Real Energy Into the Load
Production_Power.PK_Paint_Sliding_Door_1_And_2/Energies/Real Energy/Real Energy Into the Load
```

## PK Assy

```text
Airconditioning.PK_Inspection_Box2-AC/Energies/Real Energy/Real Energy Into the Load
Airconditioning.PK_Inspection_Box4-AC/Energies/Real Energy/Real Energy Into the Load
Airconditioning.PK_Inspection_Box5-Ac/Energies/Real Energy/Real Energy Into the Load
Lighting.SDB-11_L_Paint/Energies/Real Energy/Real Energy Into the Load
Other.SDB_18_P_UPS/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-PK1_PK_Assembly/Energies/Real Energy/Real Energy Into the Load
Production_Power.SDB-12_P_Paint/Energies/Real Energy/Real Energy Into the Load
Production_Power.SDB-21_P_PK_Assembly_Extn/Energies/Real Energy/Real Energy Into the Load
```

## PA WW Process

```text
Dust_Collector.G0_144_Dust_Collector/Energies/Real Energy/Real Energy Into the Load
Lighting.SDB-20_L_PA_WW/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-PA-1_Wood_Finish/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-PA1-Wood_Work/Energies/Real Energy/Real Energy Into the Load
Production_Power.SDB-20_P_PA_WW/Energies/Real Energy/Real Energy Into the Load
```

`Dust_Collector.G0_144_Dust_Collector` is excluded from the Dust Collector category total but remains valid for this cost center.

## PA Painting

```text
Dust_Collector.Dust_Collector/Energies/Real Energy/Real Energy Into the Load
Lighting.SDB-19_L_PA_Paint/Energies/Real Energy/Real Energy Into the Load
Paintshop.PP-PA_Paint_240V/Energies/Real Energy/Real Energy Into the Load
Paintshop.PP-PA_Paint_415V/Energies/Real Energy/Real Energy Into the Load
Production_Power.PA_HighSpeed_Paint_Shutter/Energies/Real Energy/Real Energy Into the Load
Production_Power.PA_High_Speed_Paint_Shutter/Energies/Real Energy/Real Energy Into the Load
Production_Power.PA_Paint_High_Speed_Shutter-5kVA_UPS/Energies/Energy/Active Energy Delivered
Production_Power.SDB-20_P_PA_Paint/Energies/Real Energy/Real Energy Into the Load
```

## PA Assy

```text
Airconditioning.PA_FA_Inspection_Box-AC/Energies/Real Energy/Real Energy Into the Load
Production_Power.PA_FA_12kVA_UPS/Energies/Energy/Active Energy Delivered
```

`Airconditioning.PA_FA_Inspection_Box-AC` is excluded from the Airconditioning category total but remains valid for this cost center.

## Material W/H

```text
Lighting.SDB-5_L_Hazardous_W_H/Energies/Real Energy/Real Energy Into the Load
Other.PDB-7_Forklift/Energies/Real Energy/Real Energy Into the Load
Other.SDB-2_P_SWH/Energies/Real Energy/Real Energy Into the Load
```

`Air_Conditioning-1` and `Air_Conditioning-2` remain unmapped because of the Information System conflict.

## Production Prepare

```text
Production_Power.Butt_Welding_Machine/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G1-3_AG_WW/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-G5_380V_Maintenance/Energies/Real Energy/Real Energy Into the Load
Production_Power.Universal_Grinding_Tool/Energies/Real Energy/Real Energy Into the Load
Production_Power.Wood_Mizer_Blade_Grinder/Energies/Real Energy/Real Energy Into the Load
```

## Production Improve

```text
Airconditioning.Chiller_1/Energies/Real Energy/Real Energy Into the Load
Airconditioning.Chiller_2/Energies/Real Energy/Real Energy Into the Load
Airconditioning.Chiller_3/Energies/Real Energy/Real Energy Into the Load
Lighting.SDB-13_L_Moulding/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-10_450T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-11_650T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-12_850T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-13AB_1300T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-13_1300T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-16_230T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-17_280T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-18_350T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-19_350T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-20AB_1600T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-20_1600T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-3_100T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-5_180T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-8_350T/Energies/Real Energy/Real Energy Into the Load
Molding.PP-PK2-9_450T/Energies/Real Energy/Real Energy Into the Load
Production_Power.PDB-11_PK_Moulding/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-PK2-15_Crush_Room/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-PK2-1_Moulding_Chiller/Energies/Real Energy/Real Energy Into the Load
Production_Power.PP-PK3-1_Mould_Maintenance/Energies/Real Energy/Real Energy Into the Load
Production_Power.SDB-14_P_Moulding/Energies/Real Energy/Real Energy Into the Load
```

## Process Inspection

```text
Airconditioning.Chiller/Energies/Real Energy/Real Energy Into the Load
Airconditioning.PA_OQC_Inspection_Box_AC/Energies/Real Energy/Real Energy Into the Load
Airconditioning.PP-G3-3_415V_Chamber_AG_Paint/Energies/Real Energy/Real Energy Into the Load
Other.PDB-15_QA_Room/Energies/Real Energy/Real Energy Into the Load
Production_Power.PA_OQC_5kVA_UPS/Energies/Real Energy/Real Energy Into the Load
```

## Logistics & Shipping

```text
Lighting.SDB-1_L_SWH/Energies/Real Energy/Real Energy Into the Load
Other.SDB_SWH/Energies/Real Energy/Real Energy Into the Load
```

---

# 14. Live monitoring device registry

These are representative devices for live monitoring. They are **not** the complete set of meters used for consumption totals.

| Device | Prefix |
|---|---|
| HT_Room | `HT_Room.South_Utilities_1000kVA_Transformer/` |
| North_Utilities | `Incomer.North_Utilities_2000KVA_Transformer/` |
| Lighting | `Lighting.SDB-9_L_Office/` |
| Molding | `Molding.PP-PK2-20_1600T/` |
| Dust_Collector | `Dust_Collector.Dust_Collector/` |
| Compressor | `Compressor.Compressor_1/` |
| Paintshop | `Paintshop.PP-G4-118_AG_AHU_AG_Paint/` |
| Other | `Other.SDB_SWH/` |
| Others | `Others.Server_Room/` |
| Airconditioning | `Airconditioning.Chiller/` |
| Production_Power | `Production_Power.PP-G1-1_380V_AG_WW/` |
| Solar | `Incomer.Incomer_Solar_100kW/` |
| DG | `Incomer.DG_Incomer_300kVA/` |
| Capacitor_350kVAR | `Other.350kVAR_Capacitor/` |
| Capacitor_700kVAR | `Other.700_kVAR_Capacitor/` |

## Common live parameter suffixes

| Parameter | Suffix |
|---|---|
| voltageAvg | `Voltages/Voltage/Voltage L-N Avg` |
| voltageA/B/C | `Voltages/Voltage/Voltage A-N` / `B-N` / `C-N` |
| currentAvg | `Currents/Current/Current Avg` |
| currentA/B/C | `Currents/Current/Current A` / `B` / `C` |
| powerFactorTotal | `Power Factors/Power Factor/Power Factor Total` |
| realPowerTotal | `Powers/Real Power/Real Power Total` |
| apparentPowerTotal | `Powers/Apparent Power/Apparent Power Total` |
| reactivePowerTotal | `Powers/Reactive Power/Reactive Power Total` |
| frequency | `Power Meters/Power Meter/Frequency` |

### Alternate live-tag paths

These devices use alternate paths for power factor and frequency:

```text
HT_Room
North_Utilities
Dust_Collector
Airconditioning
DG
Solar
Other
```

Power factor:

```text
Power Factors/Power Factor Total/Power Factor Total
```

Frequency:

```text
Miscellaneous/Frequency/Frequency
```

### Power-factor scaling

Raw `powerFactorTotal` values use a **0–100 scale**.

Example:

```text
raw = 92
display/logic value = 0.92
```

Divide by 100 before applying normal power-factor thresholds.

### Known unavailable live parameters

The following representative devices do not reliably provide apparent/reactive power:

```text
Compressor
Lighting
Molding
Others
Production_Power
```

DG apparent/reactive power is also generally unavailable because it is only observed during rare DG operation.

---

# 15. Data-quality exceptions

The AI assistant must not silently invent values when data is incomplete.

Known exceptions:

1. `Dust_Collector.G0_144_Dust_Collector/`
   - Excluded from the Dust Collector category rollup because of a verified bad sample.
   - Still valid in its explicit cost-center mapping.

2. `Airconditioning.PA_FA_Inspection_Box-AC/`
   - Excluded from the Airconditioning category rollup because of a verified counter reset.
   - Still valid in its explicit cost-center mapping.

3. `Air_Conditioning-1` / `Air_Conditioning-2`
   - Deliberately unmapped because of a conflict between Information System and Material W/H.

4. kVAh
   - Currently trustworthy only for `HT_Room` and `North_Utilities`.

5. Water / compressed air
   - No confirmed real utility-flow tags currently exist.

---

# 16. AI assistant interpretation rules

When answering a user query:

### 1. Resolve the user's entity first

Determine whether the user means:

```text
Facility
Equipment-wise category
Zone-wise cost center
Specific device
DG
Solar
HT_Room
North_Utilities
Steam
```

Do not assume "zone" means the same thing in every context.

### 2. Resolve the metric

Examples:

```text
Energy / consumption → cumulative-counter delta
Cost → kWh × tariff, using tariff rescaling rule
Peak demand → maximum apparent power
Demand utilization → peak kVA / contracted demand
Reactive energy → cumulative reactive-energy delta
DG runtime → contiguous periods above 1 kW
THD → minute-level average
Steam consumption → totalizer delta
Shift consumption → exact shift-boundary counter delta
```

### 3. Resolve the time window

All windows are IST.

Explicitly determine:

```text
start
end
calendar day/month
shift
```

For relative terms such as "today", use the current IST date.

### 4. Preserve data semantics

- `null` means unavailable/missing.
- Do not convert missing data to zero.
- Do not claim complete coverage when mappings are incomplete.
- State when a metric is only available for specific devices.

### 5. Do not double-count

Keep these scopes separate:

```text
Equipment categories
Cost centers
Grid / Solar / DG source meters
Representative live-monitoring meters
```

A representative live meter is not automatically the total consumption of its category.

---

# 17. Authoritative reference hierarchy

When multiple definitions appear possible, use this order:

1. Explicit mapping in this document.
2. Metric-specific formula in this document.
3. Known data-quality exception in this document.
4. Live backend/API result.
5. If none of the above resolves the question, return that the information is unavailable rather than guessing.

