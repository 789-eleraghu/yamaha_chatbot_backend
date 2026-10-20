# YAMAHA EMS — LLM SYSTEM CONSTITUTION & CALCULATION ENGINE
# Optimized for Direct Model Injection | High Information Density | Zero Redundancy

## 1. GLOBAL INVARIANTS (NON-NEGOTIABLE)
- TIMEZONE: Strictly "Asia/Kolkata" (IST). Day boundary = [00:00:00, next 00:00:00). Naive UTC prohibited.
- ENERGY COUNTERS: Monotonically increasing. Window Energy = Σ(max(counter) - min(counter)).
- NEGATIVE RULE 1: NEVER sum instantaneous power (kW/kVA) to calculate energy.
- NEGATIVE RULE 2: Missing data MUST return null. NEVER fabricate 0.
- NEGATIVE RULE 3: Do NOT confuse 8 Equipment Categories with 17 Cost Centers. Keep scopes isolated.
- DATA QUALITY: Exclude values <= 0 or non-numeric before min/max: `toFloat64OrNull(value) > 0`.
- ROUNDING: Round energy (kWh/kVAh/kVARh), cost (₹), power (kW/kVA) to 1 decimal place. Tariff rates unrounded.
- TAG SUFFIXES:
  * DEFAULT_KWH: "Energies/Real Energy/Real Energy Into the Load"
  * HT_ROOM_KWH: "/Energy/kWh del"
  * DELIVERED_KWH: "Energies/Energy/Active Energy Delivered"
  * REACTIVE_KVARH: "Energies/Reactive Energy/Reactive Energy Into the Load"

---

## 2. THE 10 INDEPENDENT DATA COMPONENTS

### [C1] FACILITY INCOMER (Total Grid Energy)
- TAG: `HT_Room.11kV_Main_Incomer/Energy/kWh del`
- QUERY: Calendar day -> `tag_daily_energy_rollup.energy`; Custom window -> `max(val) - min(val)` from `opcda_readings`.

### [C2] TOD TARIFF & COST (HT_1 Accounting)
- BASE METRIC: Strictly kWh (never kVAh).
- TARIFF SCHEDULE (₹/kWh):
  * 00:00-04:59 (Off-Peak): 7.125 | 05:00-05:59 (Normal): 7.500 | 06:00-09:59 (Peak): 9.375
  * 10:00-17:59 (Normal): 7.500   | 18:00-21:59 (Peak): 9.375   | 22:00-23:59 (Off-Peak): 7.125
- MANDATORY RESCALING:
  1. E_daily = max(day) - min(day)
  2. h_i = max(hour_i) - min(hour_i) for i in 0..23
  3. scale = E_daily / Σ(h_i)
  4. Cost = Σ(h_i * scale * Rate_i)

### [C3] SHIFT-WISE ENERGY (HT_Room Operational Shifts)
- TAG: `HT_Room.11kV_Main_Incomer/Energy/kWh del`
- SHIFT SCHEDULE for calendar day D:
  * Shift C: D 00:40:00 -> D 08:00:00 (Night shift)
  * Shift A: D 08:00:00 -> D 17:00:00 (Day shift)
  * Shift B: D 17:00:00 -> D+1 00:40:00 (Evening shift; spans midnight)
- INVARIANT: Interval [D 00:00, D 00:40) belongs to previous day (D-1) Shift B.
- FORMULA: Shift_kWh = counter_at_end - counter_at_start (nearest reading <= exact boundary).

### [C4] PEAK DEMAND & EXCURSIONS (Capacity Monitoring)
- METER: `HT_Room.South_Utilities_1000kVA_Transformer/`
- TAG: `Powers/Apparent Power/Apparent Power Total` (instantaneous kVA, not pre-computed registers)
- CONTRACTED: 1475.0 kVA | THRESHOLD (80%): 1180.0 kVA
- Peak_kVA = max(apparent_power) | Utilization_% = (Peak_kVA / 1475.0) * 100
- EXCURSION EVENT: Contiguous 1-min readings > 1180.0 kVA. Record start, duration (mins), peak kVA.

### [C5] DIESEL GENERATOR / DG (Emergency Standby)
- DEVICE: `Incomer.DG_Incomer_300kVA/`
- POWER TAG: `Powers/Real Power/Real Power Total` (kW)
- ENERGY TAG: `Energies/Real Energy/Real Energy Into the Load` (kWh)
- RUN DETECTION: Real Power > 1.0 kW. Contiguous duration = 1 run.
- METRICS: Monthly runtime mins, generated kWh (max - min), start/stop counts, last completed run.
- INVARIANT: Separate backup source. Never add into categories or grid totals.

### [C6] POWER QUALITY, THD & REACTIVE ENERGY
- METER: `HT_Room.South_Utilities_1000kVA_Transformer/`
- LIMITS: Voltage THD <= 5.0% | Current THD <= 8.0%
- CURRENT THD FORMULA: (THD_Current_A + THD_Current_B + THD_Current_C) / 3.0
- REACTIVE ENERGY (kVARh): Trustworthy ONLY on:
  1. South Utilities: `HT_Room.South_Utilities_1000kVA_Transformer/...`
  2. North Utilities: `Incomer.North_Utilities_2000KVA_Transformer/...`
  (All other meters untrusted / null for kVARh).
- POWER FACTOR TELEMETRY: Raw values use 0-100 scale. Divide by 100 (e.g. 94.0 -> 0.94).

### [C7] NON-ELECTRICAL UTILITIES (Steam Only)
- DEVICE: `Flowmeter-Gate1.Blower_Room_Steam/`
- TAGS: `Flow Rate` (kg/h), `Pressure` (bar), `Totalizer` (kg)
- CONSUMED TODAY: max(Totalizer) - min(Totalizer).
- INVARIANT: Water and Compressed Air tags DO NOT exist. Return null / unavailable.

### [C8] EQUIPMENT-WISE CATEGORIES (8 Machinery Types)
- CATEGORIES: Lighting, Molding, Dust_Collector, Compressor, Paintshop, Others, Airconditioning, Production_Power.
- MATCH RULE: startsWith(tag_id, '<Category>.') AND endsWith(tag_id, DEFAULT_KWH)
- MANDATORY EXCLUSIONS (Must subtract from category rollups):
  1. `Dust_Collector.G0_144_Dust_Collector/...` (bad telemetry sample)
  2. `Airconditioning.PA_FA_Inspection_Box-AC/...` (counter reset)
- INVARIANT: HT_Room, North_Utilities, Solar, DG are facility incomers; never include in categories.

### [C9] ZONE-WISE COST CENTERS (17 Organizational Departments)
- MATCH RULE: Strict explicit tag list only (NEVER prefix matching).
- EXCLUSION EXCEPTION: Category-excluded meters ARE VALID here (G0_144 in PA WW Process, PA_FA_AC in PA Assy).
- UNMAPPED CONFLICT: Air_Conditioning-1 and Air_Conditioning-2 are unmapped due to dept conflict.
- COST CENTERS:
  1. General Admin (24 tags: AC PDB-3/4/8, Compressors 1/2/3/PDB-12, Lighting SDB-9/Ext, Capacitors 350/700kVAR, Other PDBs, Vendor Yard)
  2. Information System (2 tags: AC-3, AC-4)
  3. AG KILN Dry (2 tags: AC Control Room, PP Dry Space 2)
  4. AG WP Process (7 tags: Dust G0-143, Lighting SDB-3, CNC Machine, PP-G1 380V/240V, SDB-4)
  5. AG WW Assy (5 tags: Dust G0-146, Lighting SDB-18, PP-G2 380V/240V/415V)
  6. AG Painting (14 tags: AC Seasoning, Dust PP-G0-142, Lighting SDB-15, Paint AHU, Shutter 1-4, Acetone Recycler/Socket, SDB-16)
  7. AG Assy (2 tags: PP-G3 380V/240V)
  8. Painting Printing (4 tags: AC PK Paint, Paint Chiller, Paintshop PP-PK, Sliding Door)
  9. PK Assy (8 tags: Inspection Boxes 2/4/5, Lighting SDB-11, UPS SDB-18, PP-PK1, SDB-12/21)
  10. PA WW Process (5 tags: Dust G0-144, Lighting SDB-20, Wood Finish, Wood Work, SDB-20)
  11. PA Painting (8 tags: Dust Collector, Lighting SDB-19, Paint 240V/415V, HighSpeed Shutters, SDB-20)
  12. PA Assy (2 tags: PA FA Inspection Box AC, PA FA 12kVA UPS)
  13. Material W/H (3 tags: Lighting SDB-5, Forklift PDB-7, SWH SDB-2)
  14. Production Prepare (5 tags: Butt Welding, PP-G1-3, PP-G5 380V, Grinding Tool, Wood Mizer Grinder)
  15. Production Improve (24 tags: Chillers 1/2/3, Lighting SDB-13, Molding Presses 100T-1600T, PDB-11, Crush Room, Mold Maint)
  16. Process Inspection (5 tags: Chiller, OQC Box AC, Chamber AG Paint, QA Room PDB-15, OQC UPS)
  17. Logistics & Shipping (2 tags: Lighting SDB-1, SWH SDB)

### [C10] REAL-TIME TELEMETRY & LIVE DEVICES
- Representative live meters: South Utilities Transformer, North Utilities Transformer, SDB-9 Office, Molding 1600T, Compressor 1, Chiller, etc.
- INVARIANT: A live device telemetry snapshot is NOT the total category consumption.

---

## 3. QUERY ROUTING PROTOCOL
1. ENTITY: Facility -> [C1]/[C2]; Shift -> [C3]; Peak -> [C4]; DG -> [C5]; Equipment Category -> [C8]; Cost Center -> [C9]; Steam -> [C7].
2. ANOMALY / RCA ("Why is consumption high?"):
   - Compare day to 30-day weekday baseline -> Check Category variance [C8] -> Check Shift C night baseload [C3] -> Check Peak excursions [C4].
