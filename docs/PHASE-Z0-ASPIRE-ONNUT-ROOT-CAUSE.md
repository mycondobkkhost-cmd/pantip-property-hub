# Phase Z0 — Aspire Onnut Station Root Cause

## Project identity

| Field | Value |
|---|---|
| project_id | `d9a5d2b2-355a-55e6-b471-773b9badc8c6` |
| bucket_key | `aspireonnutstation` |
| Pantip / RealXtate name | Aspire Onnut Station (แอสปาย อ่อนนุช สเตชั่น) |
| match_class | EXACT_ID_MATCH |
| live_listing_count | 11 |

## Coordinate evidence

| Field | Value |
|---|---|
| coordinate_state | SOURCE_PROVIDED |
| acceptance_status | ACCEPTED |
| source_family | propertyhub_directory |
| latitude | 13.707728 |
| longitude | 100.599766 |
| trust_label | SOURCE_PROVIDED_PROJECT_PIN (T2, not owner-verified) |

Nearest transit (straight-line distance, not walking):

| Station | Distance |
|---|---|
| BTS อ่อนนุช | 269 m |
| BTS พระโขนง | 1,238 m |
| BTS บางจาก | 1,360 m |

## Pantip legacy zone contamination

`pantip_zone_verified`:

- อ่อนนุช
- อุดมสุข
- **เจริญนคร**
- คลองเตย
- วัฒนา

`legacy_promotion_suspected: true` — verified equals unverified zone bag.

Catalog `locations_json` (same contamination):

```json
["อ่อนนุช","อุดมสุข","เจริญนคร","คลองเตย","วัฒนา"]
```

Catalog `transit_json` incorrectly includes Thonburi-side stations:

- BTS กรุงธนบุรี
- BTS เจริญนคร
- BTS อ่อนนุช

## RealXtate marketplace assignments (8z3)

| Area | Role | Confidence | Evidence families | Reason | Straight-line m to anchor |
|---|---|---|---|---|---|
| อ่อนนุช (onnut) | PRIMARY | HIGH | name_branding, catalog_listing_bag, admin, coordinate_geo | core_coordinate_plus_independent_local_evidence | 269 |
| เจริญนคร (charoen_nakhon) | EDGE | LOW | catalog_listing_bag | supporting_signals_only | 10,016 |
| คลองเตย (khlong_toei) | EDGE | LOW | catalog_listing_bag, admin | supporting_signals_only | 5,159 |

## Causal chain — why Charoen Nakhon appears

This is an **algorithm + data contamination** failure, not a coordinate pin error.

1. **Legacy employee sheet zone bag** stores multiple unrelated marketplace/admin tokens per project (`อ่อนนุช`, `เจริญนคร`, `คลองเตย`, …) in Pantip and catalog `locations_json`.
2. RealXtate Phase **8z3** assignment (`marketplace-area-assignment-v01.ts`) treats `locations_json` as `catalog_listing_bag` evidence via `listingPrimaryHit()`.
3. Token `เจริญนคร` matches approved seed area `charoen_nakhon`.
4. Coordinate for project is **269 m** from On Nut anchor — correctly yields PRIMARY On Nut (HIGH).
5. Algorithm still allows additional **LOW / EDGE** slots up to 3 areas when weak `catalog_listing_bag` hits exist.
6. Charoen Nakhon receives LOW confidence with reason `supporting_signals_only` despite **10,016 m** straight-line distance — distance does not veto weak EDGE fills.
7. Pantip owner UI / review queue surfaces all three marketplace relations; owner sees Charoen Nakhon as a Master proposal even though it is weak EDGE contamination.

## Owner-suggested candidates (not auto-approved)

| Candidate | In approved 31-area seed? | Z0 prototype result |
|---|---|---|
| On Nut | YES | AUTO_SAFE / PRIMARY |
| Suan Luang | NO | Not evaluable as marketplace area (not in seed) |
| Pattanakarn | NO | Not evaluable as marketplace area (not in seed) |
| Charoen Nakhon | YES | REJECT_QUARANTINE |

## Classification

- **Data error component:** legacy multi-zone listing bag + incorrect transit labels in catalog.
- **Algorithm error component:** 8z3 permits far-away EDGE assignments from `catalog_listing_bag` alone.

## Z0 prototype disposition

| Area | Existing RX | New engine |
|---|---|---|
| On Nut | KEEP (SUPPORTED) | AUTO_SAFE PRIMARY |
| Charoen Nakhon | DOWNGRADE/REJECT | REJECT_QUARANTINE |
| Khlong Toei | DOWNGRADE/REJECT | REJECT_QUARANTINE |
