# Phase Z1 — Legacy Evidence Lineage

## Problem

Legacy employee sheet data copied into both `pantip_zone_verified` and `catalog_listing_bag` was counted as two independent sources.

## Lineage IDs

| Lineage | Source |
|---------|--------|
| `lineage:legacy_employee_sheet` | Shared Pantip zone + catalog bag |
| `lineage:pantip_zone_field` | Pantip zone only |
| `lineage:catalog_listing_bag` | Catalog bag only |
| `lineage:coordinate_pin` | Coordinate |
| `lineage:transit_field` | Transit labels |
| `lineage:realxtate_assignment` | RealXtate 8z3 assignment |
| `lineage:project_name` | Name branding |

## Token classification

`MARKETPLACE_AREA`, `ADMIN_DISTRICT`, `ADMIN_SUBDISTRICT`, `TRANSIT`, `ROAD_CORRIDOR`, `UNKNOWN`, `CONFLICTING`

## Rules

- Same lineage → counts once for corroboration
- Legacy sheet alone → never `AUTO_SAFE`
- RealXtate assignment alone → never `AUTO_SAFE`
- `legacy_bag_lineage_shared()` detects ≥80% token overlap

## Evidence families

`COORDINATE`, `TRANSIT`, `ADMIN_GEOGRAPHY`, `MARKETPLACE_REFERENCE`, `OWNER_VERIFIED`, `LEGACY_SHEET`, `NAME_BRANDING`, `CORRIDOR`
