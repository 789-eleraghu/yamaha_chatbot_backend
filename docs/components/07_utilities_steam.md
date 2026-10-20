# Component 7: Non-Electrical Utilities (Thermal / Steam)

## 1. Scope & Purpose
Monitors non-electrical utility metrics (steam flow, boiler pressure, and cumulative steam consumption).

## 2. Authoritative Device & Tags
- **Device:** `Flowmeter-Gate1.Blower_Room_Steam/`
- **Flow Rate:** `Flowmeter-Gate1.Blower_Room_Steam/Flow Rate` (kg/h)
- **Pressure:** `Flowmeter-Gate1.Blower_Room_Steam/Pressure` (bar)
- **Totalizer:** `Flowmeter-Gate1.Blower_Room_Steam/Totalizer` (Cumulative kg)

## 3. Calculation Rules
- **Current Snapshot:** Latest available reading within a 7-day lookback.
- **Steam Consumed Today:**
  $$\text{Steam Consumed (kg)} = \max(\text{Totalizer}) - \min(\text{Totalizer})$$
- **Trend:** Trailing 3-day hourly-average flow rate.

## 4. Missing Utilities Invariant (Section 8 & 15)
- **NO** confirmed Water or Compressed Air flow meters exist in the Yamaha telemetry namespace.
- If asked for Water or Compressed Air, the assistant must return `null` / state that tags are unavailable rather than guessing.
