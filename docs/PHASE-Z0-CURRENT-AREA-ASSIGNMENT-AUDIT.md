# Phase Z0 — Current Area Assignment Audit

## Pipeline discovered (RealXtate Phase 8Z.3)

```
market_area_seed_8z2b (31 approved areas)
        ↓
transit_stations (anchor coordinates)
        ↓
project_master_v01 (project pin + identity)
        ↓
property_projects.locations_json / listing bags
        ↓
marketplace-area-assignment-v01.ts  scoreArea()
        ↓
marketplace_area_assignment_8z3 (SQLite)
        ↓
Phase W crosswalk (read-only export)
        ↓
Owner Review UI (reference evidence display)
```

## Mechanism classification

| Mechanism | Used? | Notes |
|---|---|---|
| Coordinate-based (haversine to area station anchors) | YES | CORE ≤1000m, EXTENDED ≤2200m |
| Name/branding token match | YES | Project catalog name |
| Catalog listing bag token match | YES | **Major contamination vector** |
| Admin district token match | YES | From listing location segments |
| Road/soi relationships | YES | Strong soi can boost confidence |
| Manual per-project override | NO | Not found in 8z3 path |
| Inherited Pantip zone | INDIRECT | Via catalog `locations_json` copy |
| AI inference | NO | Deterministic TypeScript rules |

System type: **mixed deterministic** — coordinate + lexical token matching.

## Assignment population (trusted master, read-only)

| Confidence | Assignment rows | Distinct projects |
|---|---|---|
| HIGH | 630 | (subset of 2,039) |
| MEDIUM | 846 | |
| LOW | 1,989 | |
| **Total rows** | **3,465** | **2,039 projects** |

HIGH+MEDIUM project-level (Phase W crosswalk): **759 projects** with REALXTATE_HIGH or REALXTATE_MEDIUM.

## Evidence family breakdown (row-level)

| Evidence pattern | Rows |
|---|---|
| catalog_listing_bag + admin + coordinate_geo | 767 |
| **catalog_listing_bag only** | **692** |
| catalog_listing_bag + admin | 412 |
| name_branding + catalog_listing_bag + admin | 349 |
| catalog_listing_bag + coordinate_geo | 258 |

## Key failure mode

- **889** assignment rows have `meters_to_anchor > 2200` (beyond EXTENDED band).
- Many still exist because LOW/EDGE slots accept `catalog_listing_bag` without geographic veto.
- Only **2** HIGH/MEDIUM rows lack `coordinate_geo` — high/med assignments are mostly coordinate-backed.

## Dependency graph (condensed)

```
SOURCE: locations_json zone bag
  → RULE: listingPrimaryHit(alias)
  → ASSIGNMENT: catalog_listing_bag evidence
  → CONFIDENCE: LOW (supporting_signals_only)
  → ROLE: EDGE (fill third slot)

SOURCE: project coordinate pin
  → RULE: nearestAreaAnchor ≤ CORE_METERS
  → ASSIGNMENT: coordinate_geo evidence
  → CONFIDENCE: HIGH if + independent local evidence
  → ROLE: PRIMARY
```

## Conclusion

Existing RealXtate assignments are **reference evidence**, not ground truth. They are deterministic but allow legacy sheet contamination to create geographically implausible EDGE assignments.
