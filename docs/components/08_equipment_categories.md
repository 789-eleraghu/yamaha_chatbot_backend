# Component 8: Equipment Categories (Equipment-Wise View)

## 1. Scope & Purpose
Groups meters by functional machinery category across the **8 standard categories** (Section 12).

## 2. The 8 Equipment Categories
1. `Lighting`
2. `Molding`
3. `Dust_Collector`
4. `Compressor`
5. `Paintshop`
6. `Others`
7. `Airconditioning`
8. `Production_Power`

## 3. Tag Selection Rules
- **Category Match:**
  `tag_id` starts with `<Category>.` AND ends with `Energies/Real Energy/Real Energy Into the Load`
- Calculation: $\sum \left(\max(\text{counter}) - \min(\text{counter})\right)$ over matched tags.

## 4. Mandatory Category Exclusions (Section 11 & 15)
The model **MUST SUBTRACT/EXCLUDE** these two meters from their category totals:
1. `Dust_Collector.G0_144_Dust_Collector/` (Excluded from Dust Collector category due to bad telemetry).
2. `Airconditioning.PA_FA_Inspection_Box-AC/` (Excluded from Airconditioning category due to counter reset).

## 5. Negative Invariants
- `HT_Room`, `North_Utilities`, `Solar`, and `DG` are separate facility sources and must **never** be included in the 8 category rollups.
