# Component 10: Real-Time Telemetry & Live Device Registry

## 1. Scope & Purpose
Real-time monitoring of representative industrial machines (Section 14).

## 2. Representative Devices
- `HT_Room.South_Utilities_1000kVA_Transformer/`
- `Incomer.North_Utilities_2000KVA_Transformer/`
- `Lighting.SDB-9_L_Office/`
- `Molding.PP-PK2-20_1600T/`
- `Dust_Collector.Dust_Collector/`
- `Compressor.Compressor_1/`
- `Paintshop.PP-G4-118_AG_AHU_AG_Paint/`
- `Airconditioning.Chiller/`
- `Production_Power.PP-G1-1_380V_AG_WW/`
- `Incomer.Incomer_Solar_100kW/`
- `Incomer.DG_Incomer_300kVA/`

## 3. Common Telemetry Suffixes
| Parameter | Standard Suffix |
|---|---|
| Voltage L-N Avg | `Voltages/Voltage/Voltage L-N Avg` |
| Current Avg | `Currents/Current/Current Avg` |
| Real Power Total | `Powers/Real Power/Real Power Total` |
| Apparent Power Total | `Powers/Apparent Power/Apparent Power Total` |
| Reactive Power Total | `Powers/Reactive Power/Reactive Power Total` |
| Power Factor Total | `Power Factors/Power Factor/Power Factor Total` (or alternate path) |
| Frequency | `Power Meters/Power Meter/Frequency` (or alternate path) |

## 4. Invariants
- A representative live device reading is **NOT** the total consumption of its equipment category.
- Some representative devices (Compressor, Lighting, Molding, Others, Production Power) do not reliably provide apparent or reactive power.
