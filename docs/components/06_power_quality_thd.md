# Component 6: Power Quality, Harmonics (THD) & Reactive Energy

## 1. Scope & Purpose
Monitors harmonic distortion compliance, power factor, and inductive reactive energy.

## 2. Harmonics (THD) Authoritative Meter & Limits
- **Meter:** `HT_Room.South_Utilities_1000kVA_Transformer/`
- **Voltage THD Limit:** **5.0%**
  - Tags: `Power Quality/THD Voltage/THD Voltage A-N`, `B-N`, `C-N`, `L-N`
- **Current THD Limit:** **8.0%**
  - Tags: `Power Quality/THD Current/THD Current A`, `B`, `C`
  - **Combined Total Current THD:**
    $$\text{Current THD}_{\text{total}} = \frac{\text{THD}_A + \text{THD}_B + \text{THD}_C}{3}$$

## 3. Reactive Energy (kVARh) Trustworthy Invariant
Reactive energy counters are trustworthy **ONLY** on these two devices:
1. `HT_Room.South_Utilities_1000kVA_Transformer/Energies/Reactive Energy/Reactive Energy Into the Load`
2. `Incomer.North_Utilities_2000KVA_Transformer/Energies/Reactive Energy/Reactive Energy Into the Load`
For all other meters, reactive energy counters are untrusted or unavailable (`null`).

## 4. Power Factor Scaling Rule
- Raw `powerFactorTotal` telemetry is stored on a **0–100 scale** (e.g. 94.0 = 0.94).
- Divide by 100 before applying power factor thresholds.
