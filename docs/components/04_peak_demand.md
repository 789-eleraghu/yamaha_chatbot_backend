# Component 4: Contracted Capacity, Peak Demand & Excursions

## 1. Scope & Purpose
Monitors maximum apparent power, demand penalties, and threshold excursions.

## 2. Authoritative Device & Tag
- **Meter:** `HT_Room.South_Utilities_1000kVA_Transformer/`
- **Tag:** `Powers/Apparent Power/Apparent Power Total`

## 3. Thresholds & Limits
- **Contracted Demand:** **1,475.0 kVA**
- **Peak Event Threshold (80%):** **1,180.0 kVA** ($1475 \times 0.8$)

## 4. Calculation Rules
- $\text{Peak kVA} = \max(\text{apparent\_power\_total})$ over raw instantaneous readings.
- $\text{Utilization \%} = \frac{\text{Peak kVA}}{1475.0} \times 100$.
- **Hourly Peak:** $\max(\text{value})$ per hour of the day.
- **Excursion Event:** Contiguous period of 1-minute readings above 1,180.0 kVA. Records:
  - Date & Start Time
  - Duration (minutes)
  - Peak kVA reached

## 5. Negative Invariant
- **Do NOT** use the meter's internal pre-computed demand registers; use raw apparent power readings.
