# Component 1: Facility Incomer & Grid Supply

## 1. Scope & Purpose
Measures authoritative total grid electricity consumption for the entire Yamaha facility.

## 2. Authoritative Tags
- **Primary Grid Incomer (kWh):**
  `HT_Room.11kV_Main_Incomer/Energy/kWh del`
- **Primary Grid Incomer (kVAh):**
  `HT_Room.11kV_Main_Incomer/Energy/kVAh del`
- **Transformers:**
  - South Utilities: `HT_Room.South_Utilities_1000kVA_Transformer/Energy/kWh del`
  - North Utilities: `Incomer.North_Utilities_2000KVA_Transformer/Energies/Real Energy/Real Energy Into the Load`

## 3. Storage Tables & Query Strategy
- **Full Days:** Read directly from `tag_daily_energy_rollup`:
  ```sql
  SELECT energy FROM tag_daily_energy_rollup 
  WHERE tag_id = 'HT_Room.11kV_Main_Incomer/Energy/kWh del' AND date = :date;
  ```
- **Custom Windows:** Query `opcda_readings`:
  ```sql
  SELECT max(value) - min(value) AS energy_kwh
  FROM opcda_readings
  WHERE tag_id = 'HT_Room.11kV_Main_Incomer/Energy/kWh del'
    AND reading_timestamp >= :start_ts AND reading_timestamp < :end_ts
    AND toFloat64OrNull(value) > 0;
  ```

## 4. Calculation Rules & Invariants
- Timezone is strictly **IST (`Asia/Kolkata`)**. Calendar day: `[00:00:00, next 00:00:00)`.
- Never treat timestamps as naive UTC.
- Cumulative counter deltas only: `max(reading) - min(reading)`.
- **Negative Invariant:** NEVER sum instantaneous power to get energy.
- Missing data returns `null`. Never invent `0`.
