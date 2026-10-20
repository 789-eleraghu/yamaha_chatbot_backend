# Component 9: Organizational Cost Centers (Zone-Wise View)

## 1. Scope & Purpose
Departmental energy accounting across **17 confirmed cost centers** (Section 13).

## 2. The 17 Cost Centers
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

## 3. Strict Mapping Regulations
- **Explicit Tags Only:** Cost centers use **explicit complete tag IDs only** (from `src/db/tag_catalog.py`). **NEVER** use prefix matching.
- **Category-Excluded Tags ARE Valid in Cost Centers:**
  - `Dust_Collector.G0_144_Dust_Collector/...` is included in `PA WW Process`.
  - `Airconditioning.PA_FA_Inspection_Box-AC/...` is included in `PA Assy`.
- **Deliberately Unmapped Conflict:**
  `Air_Conditioning-1` and `Air_Conditioning-2` are unmapped due to an organizational conflict between Information System and Material W/H.
