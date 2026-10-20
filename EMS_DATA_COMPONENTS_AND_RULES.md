# Yamaha EMS — Independent Data Components, Storage & Calculation Rules

**Document Version:** 1.0  
**Target Audience:** Energy AI Assistant Developers, LLM Prompt Engineers, Data Engineers  
**Source Reference:** [`energy-ai-assistant-reference.md`](file:///home/raghu/Desktop/yamaha_chatbot_backend/energy-ai-assistant-reference.md)

---

## 1. System Storage Architecture: How Data is Stored for the Model

The Energy Management System (EMS) stores high-frequency industrial telemetry in two core tables, abstracted across **ClickHouse** (production) and **SQLite** (local development/mock).

```
                                      Telemetry Ingestion (OPC-DA)
                                                   │
                                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ RAW TIME-SERIES TABLE: `opcda_readings`                                                             │
│ Columns:                                                                                            │
│ • `tag_id` (String): Fully-qualified hierarchical meter path (e.g. `HT_Room.11kV_Main_Incomer/...`) │
│ • `reading_timestamp` (DateTime / ISO Text): Timestamp strictly in IST (`Asia/Kolkata`)             │
│ • `value` (Float64 / Real): Metric reading (cumulative counter, instantaneous power, or percentage) │
│ Indexes: `(tag_id, reading_timestamp)`, `(reading_timestamp)`                                      │
└──────────────────────────────────────────────────┬──────────────────────────────────────────────────┘
                                                   │
                                                   ▼ (Continuous Daily Rollup Materialized View)
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ DAILY AGGREGATE TABLE: `tag_daily_energy_rollup`                                                    │
│ Columns:                                                                                            │
│ • `date` (Date / Text 'YYYY-MM-DD'): Calendar day strictly in IST                                   │
│ • `tag_id` (String): Fully-qualified tag path                                                       │
│ • `min_value` (Float64): First/minimum reading of the calendar day                                 │
│ • `max_value` (Float64): Last/maximum reading of the calendar day                                   │
│ • `energy` (Float64): True day delta (`max_value - min_value`)                                      │
│ Indexes: `(tag_id, date)`, `(date)`                                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Global Storage & Semantics Invariants (Non-Negotiable)

1. **Strict IST Timezone (`Asia/Kolkata`):**
   - A calendar day is strictly defined as `[00:00:00 IST, next 00:00:00 IST)`.
   - Never treat timestamps as naive UTC. Never use UTC date boundaries.
2. **Cumulative Monotonic Counter Rule:**
   - Cumulative energy tags (kWh, kVAh, kVARh, Steam Totalizer) increase monotonically.
   - Energy over any window $W$ is:
     $$\text{Consumption}(W) = \sum_{\text{tags}} \left(\max_{t \in W}(\text{reading}) - \min_{t \in W}(\text{reading})\right)$$
   - **Negative Invariant:** **NEVER** sum instantaneous power (kW/kVA) to calculate energy.
3. **Invalid Readings & Missing Data:**
   - Values $\le 0$, non-numeric, or null must be excluded before computing $\max$ or $\min$:
     `toFloat64OrNull(value) > 0`
   - Missing data must strictly return `null`. **NEVER** fabricate `0` for missing or offline meters.
4. **Post-Calculation Rounding:**
   - Round energy (kWh/kVAh/kVARh), cost (INR), and power (kW/kVA) to **1 decimal place** after all calculations.
   - Tariff rates are never rounded.

---

## 2. Decomposition into 10 Independent Data Components

To guarantee zero cross-contamination and eliminate interdependencies, the EMS dataset is decoupled into **10 independent components**. Each component has its own dedicated tags, independent calculation formulas, and clear boundaries.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        YAMAHA EMS DECOUPLED DATA ARCHITECTURE                          │
├──────────────────────────┬──────────────────────────┬──────────────────────────────────┤
│ 1. Facility Incomer      │ 2. TOD Tariff & Cost     │ 3. Shift Accounting              │
│ (Grid Total Consumption) │ (HT_1 Hourly Rescaling)  │ (Shifts A, B, C with 00:40 split)│
├──────────────────────────┼──────────────────────────┼──────────────────────────────────┤
│ 4. Peak Demand           │ 5. Diesel Generator (DG) │ 6. Power Quality (THD)           │
│ (1180 kVA Threshold)     │ (> 1.0 kW Run Detection) │ (Voltage 5% / Current 8% Limits) │
├──────────────────────────┼──────────────────────────┼──────────────────────────────────┤
│ 7. Reactive Energy       │ 8. Steam Utilities       │ 9. Equipment-Wise Categories     │
│ (kVARh on Transformers)  │ (Flow, Pressure, Total)  │ (8 Categories with Exclusions)   │
├──────────────────────────┴──────────────────────────┴──────────────────────────────────┤
│ 10. Zone-Wise Cost Centers (17 Organizational Cost Centers via Explicit Tag Lists)     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### Component 1: Facility-Level Incomer Energy (Grid Supply)

* **Purpose:** Authoritative facility-wide electrical consumption.
* **Authoritative Tag:**
  `HT_Room.11kV_Main_Incomer/Energy/kWh del`
* **Storage Tables Used:** `tag_daily_energy_rollup` (for calendar days); `opcda_readings` (for custom windows).
* **Calculation Rule:**
  $$\text{Energy}_{\text{facility}} = \max(\text{counter}) - \min(\text{counter})$$
* **Zero-Dependency Guarantee:** Does not depend on sub-meter rollups, categories, or cost centers. It represents the master grid intake.

---

### Component 2: Time-of-Day (TOD) Tariff & Cost Accounting

* **Purpose:** Financial electricity bill calculations.
* **Tariff Schedule (`HT_1`):**
  | IST Hours | Band | Rate (₹/kWh) |
  |---|---|---:|
  | 00:00–04:59 | Off-Peak | 7.125 |
  | 05:00–05:59 | Normal | 7.500 |
  | 06:00–09:59 | Peak | 9.375 |
  | 10:00–17:59 | Normal | 7.500 |
  | 18:00–21:59 | Peak | 9.375 |
  | 22:00–23:59 | Off-Peak | 7.125 |

* **Mandatory Rescaling Regulation (Section 3):**
  Due to sampling boundaries, summing raw hourly deltas causes boundary leakage. The model must strictly enforce:
  1. Compute true daily energy: $E_{\text{daily}} = \max_{\text{day}}(\text{counter}) - \min_{\text{day}}(\text{counter})$
  2. Compute hourly deltas: $h_i = \max_{\text{hour } i}(\text{counter}) - \min_{\text{hour } i}(\text{counter})$
  3. Rescaling factor: $\text{scale} = \frac{E_{\text{daily}}}{\sum_{i=0}^{23} h_i}$
  4. Rescaled hourly consumption: $h_i^* = h_i \times \text{scale}$
  5. Total Cost:
     $$\text{Cost} = \sum_{i=0}^{23} (h_i^* \times \text{Rate}_i)$$
* **Negative Invariant:** Cost is **ALWAYS** computed on **kWh**; never on kVAh.

---

### Component 3: Shift-Wise Operational Energy Accounting

* **Purpose:** Shift-level production accountability.
* **Authoritative Tag:** `HT_Room.11kV_Main_Incomer/Energy/kWh del`
* **Shift Window Definitions:**
  | Shift | Calendar Day $D$ Window | Notes |
  |---|---|---|
  | **Shift C** | $D\text{ 00:40:00} \longrightarrow D\text{ 08:00:00}$ | Morning night shift |
  | **Shift A** | $D\text{ 08:00:00} \longrightarrow D\text{ 17:00:00}$ | General production day shift |
  | **Shift B** | $D\text{ 17:00:00} \longrightarrow D+1\text{ 00:40:00}$ | Evening shift (spans midnight) |

* **Boundary Regulation:**
  - The interval `00:00:00` to `00:40:00` on day $D$ belongs to the **previous day’s ($D-1$) Shift B**.
  - Boundary values must use the nearest recorded counter **at or before** the exact boundary timestamp.
  - Calculation: $\text{kWh}_{\text{shift}} = \text{counter}_{\text{end}} - \text{counter}_{\text{start}}$.
  - If any boundary reading is absent, return `null`.

---

### Component 4: Contracted Capacity, Peak Demand & Excursions

* **Purpose:** Grid peak load compliance and maximum demand charges.
* **Authoritative Meter & Tag:**
  - Meter: `HT_Room.South_Utilities_1000kVA_Transformer/`
  - Tag: `Powers/Apparent Power/Apparent Power Total`
* **Constants & Limits:**
  - Contracted Demand: **$1,475.0\text{ kVA}$**
  - Excursion Threshold (80%): **$1,180.0\text{ kVA}$** ($1475 \times 0.8$)
* **Calculation Rules:**
  - $\text{Peak kVA} = \max(\text{apparent\_power\_total})$ over raw instantaneous readings.
  - $\text{Utilization \%} = \frac{\text{Peak kVA}}{1475.0} \times 100$.
  - **Excursion Event:** Any contiguous period where readings exceed $1,180.0\text{ kVA}$. Records start time, duration, and peak kVA reached.
* **Negative Invariant:** **Do NOT** use the meter's internal pre-computed demand registers; use raw apparent power maximums.

---

### Component 5: Backup Power & Diesel Generator (DG) Operations

* **Purpose:** Generator run tracking, fuel burn estimation, and outage metrics.
* **Authoritative Tags:**
  - Real Power: `Incomer.DG_Incomer_300kVA/Powers/Real Power/Real Power Total`
  - Cumulative Energy: `Incomer.DG_Incomer_300kVA/Energies/Real Energy/Real Energy Into the Load`
* **Calculation Rules:**
  - **Run Detection:** A DG run starts when real power exceeds **$1.0\text{ kW}$**.
  - A contiguous period above $1.0\text{ kW}$ is counted as one run.
  - $\text{Monthly Runtime (minutes)} = \sum \text{duration of runs starting in month}$.
  - $\text{Energy Generated (kWh)} = \max(\text{energy\_tag}) - \min(\text{energy\_tag})$.
* **Zero-Dependency Guarantee:** DG is a standalone generation source. It must **never** be added into equipment category rollups.

---

### Component 6: Power Quality, Harmonics (THD) & Reactive Energy

* **Purpose:** Grid health, harmonic distortion compliance, and power factor support.
* **Authoritative Meter:** `HT_Room.South_Utilities_1000kVA_Transformer/`
* **Harmonics (THD) Suffixes & Limits:**
  - Voltage THD Limit: **$5.0\%$** (Suffixes: `Power Quality/THD Voltage/THD Voltage A-N`, `B-N`, `C-N`, `L-N`).
  - Current THD Limit: **$8.0\%$** (Suffixes: `Power Quality/THD Current/THD Current A`, `B`, `C`).
  - **Combined Current THD:** Since no total current tag exists:
    $$\text{Current THD}_{\text{total}} = \frac{\text{THD}_A + \text{THD}_B + \text{THD}_C}{3}$$
* **Reactive Energy (kVARh):**
  - **Trustworthy Rule:** Trustworthy **ONLY** on two devices:
    1. `HT_Room.South_Utilities_1000kVA_Transformer/Energies/Reactive Energy/Reactive Energy Into the Load`
    2. `Incomer.North_Utilities_2000KVA_Transformer/Energies/Reactive Energy/Reactive Energy Into the Load`
  - For all other meters, reactive energy counters are untrusted or unavailable (`null`).
* **Power Factor Raw Scaling Regulation (Section 14):**
  - Raw `powerFactorTotal` values are stored on a **$0\text{--}100$ scale**.
  - **Rule:** Divide raw values by $100$ before displaying or applying logic (e.g. raw $94.0 \rightarrow 0.94$).

---

### Component 7: Non-Electrical Utilities (Thermal / Steam)

* **Purpose:** Steam flow and boiler generation tracking.
* **Authoritative Device:** `Flowmeter-Gate1.Blower_Room_Steam/`
* **Tags:**
  - Flow Rate: `.../Flow Rate` (Instantaneous kg/h)
  - Pressure: `.../Pressure` (Instantaneous bar)
  - Totalizer: `.../Totalizer` (Cumulative kg)
* **Calculation Rules:**
  - Current snapshot: latest reading within a 7-day lookback.
  - Consumed today: $\max(\text{totalizer}) - \min(\text{totalizer})$ over the IST day.
* **Negative Invariant (Section 8 & 15):** **NO** confirmed Water or Compressed Air flow tags exist. If asked for Water or Compressed Air consumption, the model must explicitly state that tags are unavailable rather than guessing or fabricating values.

---

### Component 8: Equipment Categories (Equipment-Wise View)

* **Purpose:** Functional equipment grouping across **8 standard categories**.
* **Categories:**
  1. `Lighting`
  2. `Molding`
  3. `Dust_Collector`
  4. `Compressor`
  5. `Paintshop`
  6. `Others`
  7. `Airconditioning`
  8. `Production_Power`
* **Tag Selection Rule:**
  `tag_id` starts with `<Category>.` AND ends with `Energies/Real Energy/Real Energy Into the Load`.
* **Mandatory Category Exclusions (Section 11 & 15):**
  You **MUST subtract/exclude** these two specific tags from their respective category totals:
  1. `Dust_Collector.G0_144_Dust_Collector/...` (Excluded from Dust Collector category due to bad telemetry).
  2. `Airconditioning.PA_FA_Inspection_Box-AC/...` (Excluded from Airconditioning category due to counter reset).
* **Negative Invariant:** `HT_Room`, `North_Utilities`, `Solar`, and `DG` are facility incomers/sources and must **never** be included in the 8 equipment categories.

---

### Component 9: Organizational Cost Centers (Zone-Wise View)

* **Purpose:** Departmental accounting across **17 confirmed cost centers**.
* **Cost Centers:**
  1. `General Admin` (24 tags)
  2. `Information System` (2 tags)
  3. `AG KILN Dry` (2 tags)
  4. `AG WP Process` (7 tags)
  5. `AG WW Assy` (5 tags)
  6. `AG Painting` (14 tags)
  7. `AG Assy` (2 tags)
  8. `Painting Printing` (4 tags)
  9. `PK Assy` (8 tags)
  10. `PA WW Process` (5 tags)
  11. `PA Painting` (8 tags)
  12. `PA Assy` (2 tags)
  13. `Material W/H` (3 tags)
  14. `Production Prepare` (5 tags)
  15. `Production Improve` (24 tags)
  16. `Process Inspection` (5 tags)
  17. `Logistics & Shipping` (2 tags)

* **Strict Mapping Regulations:**
  - Cost centers use **explicit tag lists only** (Section 13). **NEVER** use prefix matching for cost centers.
  - The Category Exclusions (`G0_144_Dust_Collector` and `PA_FA_Inspection_Box-AC`) **ARE VALID** and included in their mapped cost centers (`PA WW Process` and `PA Assy`).
  - **Unmapped Conflict:** `Air_Conditioning-1` and `Air_Conditioning-2` are deliberately omitted due to an organizational conflict between Information System and Material W/H.

---

### Component 10: Real-Time Telemetry & Live Device Registry

* **Purpose:** Single-meter real-time diagnostic snapshots.
* **Representative Devices (Section 14):**
  - Transformers: `HT_Room.South_Utilities...`, `Incomer.North_Utilities...`
  - Representative Feeders: `Lighting.SDB-9_L_Office/`, `Molding.PP-PK2-20_1600T/`, `Compressor.Compressor_1/`, `Airconditioning.Chiller/`, etc.
* **Telemetry Parameters:**
  - Voltage L-N Avg, Current Avg, Power Factor Total, Real Power Total, Frequency.
* **Negative Invariant (Section 16):** A representative live device reading (e.g. `Molding.PP-PK2-20_1600T`) is **NOT** the total consumption of the Molding category. Do not confuse single-device telemetry with category rollups.

---

## 3. Disambiguation Protocol for User Queries (Section 16)

When interpreting user requests, the model must follow this exact decision sequence:

```
                                      User Query
                                           │
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │ STEP 1: Disambiguate Entity                  │
                    │ • Facility Level?  --> Component 1 or 2      │
                    │ • "Equipment-Wise" --> Component 8 (8 cats)  │
                    │ • "Zone-Wise"      --> Component 9 (17 CCs)  │
                    │ • Specific Machine --> Component 10 (Single) │
                    │ • DG / Solar       --> Component 5 / Sources │
                    │ • Steam            --> Component 7 (Thermal) │
                    └──────────────────────┬───────────────────────┘
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │ STEP 2: Disambiguate Metric                  │
                    │ • Total Energy --> Max - Min cumulative delta│
                    │ • Shift Energy --> Shift A, B, C boundaries  │
                    │ • Cost         --> Rescaled hour × Tariff HT_1│
                    │ • Peak Load    --> Max Apparent Power (kVA)  │
                    │ • Distortion   --> Voltage / Current THD     │
                    └──────────────────────┬───────────────────────┘
                                           ▼
                    ┌──────────────────────────────────────────────┐
                    │ STEP 3: Apply Data Quality Rules             │
                    │ • Exclude G0_144 / PA_FA if category rollup  │
                    │ • Return null if data missing (never 0)      │
                    │ • Round result to 1 decimal place            │
                    └──────────────────────────────────────────────┘
```

---

## 4. Mapping Matrix: Independent Components to Tools

| Component # | Component Name | LangChain Backend Tool | Core Service Function |
|---|---|---|---|
| **1** | Facility Incomer Energy | `get_energy_consumption(date)` | `EnergyService.get_facility_daily_energy` |
| **2** | TOD Tariff & Cost | `get_cost_and_tariff(date)` | `TariffService.calculate_daily_cost` |
| **3** | Shift Accounting | `get_shift_wise_consumption(date)` | `ShiftService.get_shift_consumption` |
| **4** | Peak Demand & Excursions | `get_peak_demand_analysis(date)` | `DemandService.get_peak_demand_analysis` |
| **5** | Diesel Generator (DG) | `get_dg_generator_status(month)` | `DGService.get_dg_monthly_metrics` |
| **6** | Power Quality & THD | `get_power_quality_and_utilities("thd", date)` | `PowerQualityService.get_thd_analysis` |
| **7** | Utilities & Steam | `get_power_quality_and_utilities("steam", date)` | `PowerQualityService.get_steam_summary` |
| **8** | Equipment-Wise Categories | `get_breakdown_summary("equipment_wise", date)` | `BreakdownService.get_equipment_wise_breakdown` |
| **9** | Zone-Wise Cost Centers | `get_breakdown_summary("zone_wise", date)` | `BreakdownService.get_zone_wise_cost_centers` |
| **10** | Live Telemetry & SQL | `execute_custom_sql(query)` | `db_client.execute_query` |
| **All** | Knowledge & Exceptions | `search_ems_knowledge_base(query)` | `EMSKnowledgeBase.search` |
| **RCA** | Root Cause Anomaly Diagnosis| `diagnose_high_consumption(date)` | `RCAService.diagnose_day` |

---

## Summary for LLM Ingestion & Inference

- **Zero Coupling:** No component imports, mutates, or relies on another component's intermediate variables.
- **Auditable Calculation:** Every computation uses deterministic Python code rather than LLM mental math.
- **Deterministic Schema:** Responses always map back to strict typed schemas (`AssistantResponse`, `ChartConfig`) ensuring clean frontend rendering with zero ambiguity.
