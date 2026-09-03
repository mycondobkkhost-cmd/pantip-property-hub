# Phase Z1 — Market Area Master v0.2

Fixture: `data_fixtures/area_engine/market_area_spatial_seed_v0.2.json`

- **31** `EXISTING_APPROVED` areas — stable `area_id` from RealXtate seed
- **12** candidate / review entries — no production authority

## Suan Luang research

| Field | Result |
|-------|--------|
| Admin | เขตสวนหลวง — `ADMIN_DISTRICT` (separate entity) |
| Marketplace candidate | `suan_luang` — `CANDIDATE` / `REVIEW_REQUIRED` |
| Evidence | Transit anchor `yl_suan_luang_rama_9` only |
| Recommendation | **REVIEW_REQUIRED** — owner suggestion alone insufficient |

## Pattanakarn research

| Field | Result |
|-------|--------|
| RealXtate seed | `phatthanakan` exists as `CORRIDOR`, outcome `NEEDS_RESEARCH` |
| Fixture status | `CANDIDATE` / `REVIEW_REQUIRED` |
| Recommendation | **REVIEW_REQUIRED** — not auto-approved as marketplace area |

## Anchor types

- `TRANSIT_STATION`
- `VERIFIED_PROJECT_CLUSTER`
- `ROAD_CORRIDOR`
- `MANUAL_REFERENCE_POINT`

## Adjacency v0.2

Relations: `DIRECT_NEIGHBOR`, `CORRIDOR_NEIGHBOR`, `TRANSIT_NEIGHBOR`, `EDGE_COMPATIBLE` — declared from seed, not name similarity alone.
