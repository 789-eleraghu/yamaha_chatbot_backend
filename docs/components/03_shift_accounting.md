# Component 3: Shift-Wise Operational Energy Accounting

## 1. Scope & Purpose
Determines shift-level energy consumption for plant shifts on `HT_Room`.

## 2. Authoritative Tag
`HT_Room.11kV_Main_Incomer/Energy/kWh del`

## 3. Shift Schedule & Exact Windows
For calendar day $D$:
- **Shift C:** $D\text{ 00:40:00} \longrightarrow D\text{ 08:00:00}$
- **Shift A:** $D\text{ 08:00:00} \longrightarrow D\text{ 17:00:00}$
- **Shift B:** $D\text{ 17:00:00} \longrightarrow D+1\text{ 00:40:00}$ (spans midnight into next day)

## 4. Boundary Crossover Regulation
- The period `00:00:00` to `00:40:00` on calendar day $D$ belongs to the **previous day’s ($D-1$) Shift B**.
- Boundary values use the nearest recorded counter reading **at or before** the exact boundary:
  $$\text{kWh}_{\text{shift}} = \text{counter}_{\text{end}} - \text{counter}_{\text{start}}$$
- If counter readings at boundary timestamps are missing, return `null`.
