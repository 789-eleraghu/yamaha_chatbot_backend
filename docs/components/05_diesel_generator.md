# Component 5: Backup Power & Diesel Generator (DG) Operations

## 1. Scope & Purpose
Tracks generator runtimes, starts/stops, emergency backup events, and generated energy.

## 2. Authoritative Device & Tags
- **Device:** `Incomer.DG_Incomer_300kVA/`
- **Real Power Tag:** `Powers/Real Power/Real Power Total`
- **Energy Tag:** `Energies/Real Energy/Real Energy Into the Load`

## 3. Run Detection & Monthly Metrics
- **Run Threshold:** A run begins when real power exceeds **1.0 kW**.
- A contiguous period above 1.0 kW is counted as one run.
- **Monthly Runtime:** $\sum \text{duration of runs (minutes)}$.
- **Monthly Energy Generated:** $\max(\text{energy\_tag}) - \min(\text{energy\_tag})$ over the month.
- **Starts / Stops:** Number of runs whose start/stop falls within the reporting month.
- **Last Completed Run:** Most recent completed run within the lookback window.

## 4. Zero-Dependency Invariant
- DG is an emergency source and must **NEVER** be merged into equipment categories or grid incomer totals.
