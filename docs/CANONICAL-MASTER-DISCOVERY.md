# Canonical Master Data Discovery — Phase V

Read-only discovery completed 2026-09-04. This document maps what Pantip and RealXtate currently know about projects, where they overlap, and what can be reused for a future shared canonical model.

**No production data was modified in this phase.**

## Executive summary

Pantip and RealXtate share the same historical project identity foundation: stable `project_id` values derived from `bucket_key` via `uuid5(NAMESPACE_DNS, "ptp-project-{bucket}")`. Of **2,156** RealXtate catalog projects, **2,156** match Pantip by ID or bucket key. Pantip's Git snapshot has **2,234** projects (production live count may differ slightly; Fly `/app/data` is authoritative for operations).

RealXtate has invested heavily in **identity discipline**, **coordinate trust**, **transit master**, and **marketplace area assignment with confidence tiers**. Pantip has invested in **sheet-driven project buckets**, **verified/unverified zone-transit split**, **listing sync from project master**, and **operator Hub workflows**.

The long-term target is **not** copying one database over the other. It is a controlled pipeline:

```
RAW DATA → IDENTITY RESOLUTION → CANONICAL PROJECT MASTER
         → AREA / TRANSIT / ADMIN / DEVELOPER MASTERS
         → LISTINGS REFERENCE canonical project_id
```

## Pantip project model (current)

### Identity

| Field | Type | Populated | Meaning |
|-------|------|-----------|---------|
| `id` | UUID string | 2,234/2,234 | Stable canonical project ID (`uuid5` from bucket) |
| `bucket_key` | string | 2,234/2,234 | Normalized identity slug (e.g. `thru_thonglor`) |
| `canonical_name` | string | 2,234/2,234 | Display name for Hub and synced listings |
| `aliases` | string[] | 434/2,234 | Alternate spellings seen on sheet or merged |

### Location (two-layer verified/unverified)

| Field | Populated | Meaning |
|-------|-----------|---------|
| `zone_verified` | 2,041 | Trusted neighborhood/landmark tags (ทำเล) |
| `zone_unverified` | 2,056 | Raw sheet/SEO zone tags |
| `transit_verified` | 2,096 | Trusted BTS/MRT/ARL station labels |
| `transit_unverified` | 2,185 | Raw sheet transit labels |
| `location_status` | 2,234 | `verified` (2,115) or `pending_verification` (119) |
| `location_source` | 1,542 | Provenance (`livinginsider`, `corridor:*`, `override`, etc.) |

### External enrichment

| Field | Populated | Meaning |
|-------|-----------|---------|
| `living_project_url` | 765 | LivingInsider project page |
| `living_zone` | 935 | LivingInsider zone text |

### Not present on Pantip projects today

- `latitude` / `longitude` (0 projects in Git snapshot)
- `province` / `district` / `subdistrict` as structured admin fields
- `developer` as canonical field
- `marketplace_area` as classified entity
- Generic `confidence` or `evidence[]` on project records

### Listing → project relationship

- Primary FK: `property.project_id` → `project.id`
- Denormalized: `property.project_name`, `location_ref`, `transit_from_sheet`
- Sync path: `sync_project_listings_location_ref()` pushes verified project zone/transit to all linked listings
- 9 properties missing `project_id` in Git snapshot; 0 orphan `project_id` references

### Supporting masters

- `data/project_aliases.json` — 79 variant→canonical bucket mappings + 11 manual decisions
- `data/zone_master.json`, `data/transit_master.json` — curated label lists for Hub UI
- `src/hub/project_identity.py` — `soft_norm`, typo map, protected buckets, alias resolution
- `src/hub/project_location_enrich.py` — station/zone alias canonicalization, corridor packs

## RealXtate project master knowledge (reference)

RealXtate catalog (`realxtate-catalog.sqlite`): **2,156** projects, **7,288** listings. Trusted master DB holds Project Master v0.1 and Marketplace Area Assignment v0.1.

### Reusable canonical concepts (from RealXtate)

| Concept | Key sources | Reusable? |
|---------|-------------|-----------|
| Name normalization / aliases | `web/data-trust/normalize.ts`, `aliases.ts` | **YES** — aligns with Pantip `soft_norm` |
| Semantic location classification | `semantic-classifier.ts`, `false-positive-rules.ts` | **YES** — Area ≠ Station ≠ Road ≠ Admin |
| Project Master pattern (no auto-merge) | `project-master-v01.ts`, `schema-8z2k.sql` | **PARTIAL** — architecture portable |
| Coordinate trust ladder | `location-trust-ladder.ts`, `propertyhub-coordinate-ledger.ts` | **PARTIAL** — methodology yes, PH-specific ledger no |
| Transit master (169 stations) | `transit-seed.ts`, `TRANSIT-MASTER.md` | **PARTIAL** — Bangkok seed reusable |
| Marketplace area assignment | `marketplace-area-assignment-v01.ts` | **PARTIAL** — rules portable, 31-area vocabulary Bangkok-specific |
| Identity decision packets | `identity-decision-packet.ts` | **PARTIAL** — workflow pattern yes |
| Thai address parsing | `thai-address.ts` | **YES** |

### RealXtate marketplace area outcomes (measured)

Across 2,156 projects in trusted master:

| Confidence | Projects with assignment rows |
|------------|------------------------------|
| HIGH | 464 |
| MEDIUM | 573 |
| LOW | 1,816 |
| Projects with HIGH or MEDIUM (any row) | **759** (~35.2%) |

Assignment rows total: **3,465** (multi-area projects allowed, max 3).

### Product-specific (do NOT import as canonical truth)

- UI card ordering, SEO text, landing page behavior
- RealXtate-specific review groups (Park 24, THE CITY Bangna)
- PropertyHub flight-page coordinate ledger (without Pantip equivalent source)
- 25 READY marketplace areas for product pilot flag

## Canonical vs marketplace vs product-specific

| Class | Examples | Shared master candidate? |
|-------|----------|--------------------------|
| **A. Canonical fact** | project ID, canonical name, coordinates, admin district | **YES** |
| **B. Canonical relationship** | project↔transit, project↔developer, project↔admin geography | **YES** |
| **C. Marketplace classification** | Thonglor marketplace area, PRIMARY/SECONDARY/EDGE role | **YES with care** — not official boundaries |
| **D. Product presentation** | UI labels, SEO, card layout | **NO** |
| **E. Derived/temporary** | listing counts, search cache, exports | **NO** |

## Population comparison (offline, Git snapshot + RealXtate catalog)

Measured with `scripts/analyze_canonical_project_overlap.py`:

| Match class | Count | Definition |
|-------------|------:|------------|
| EXACT_ID_MATCH | 2,156 | Same `project_id` or same `bucket_key` → derived UUID |
| EXACT_STRONG_MATCH | 0 | Normalized name unique + compatible bucket (subset of above) |
| HIGH_CONFIDENCE_CANDIDATE | 0 | Alias overlap + same bucket (already captured by ID match) |
| MEDIUM_CONFIDENCE_CANDIDATE | 0 | Alias overlap with bucket mismatch |
| LOW_CONFIDENCE_CANDIDATE | 0 | Weak prefix similarity only |
| CONFLICT | 78 | Name ambiguity or bucket mismatch vs RealXtate |
| UNMATCHED_PANTIP | 0 | No RealXtate candidate |
| UNMATCHED_REALXTATE | 0 | All RealXtate projects matched by ID/bucket |

**Interpretation:** The shared UUID scheme makes cross-reference safe for **2,156** projects. The **78** Pantip-only extras (2,234 − 2,156) are bucket splits or post-divergence additions requiring forensic review, not automatic merge.

### Conflict examples (project-level, safe)

| Pantip bucket | Issue |
|---------------|-------|
| `thesaintresidence` vs RealXtate `thesaintresidences` | Name match, bucket mismatch |
| `ideoratchadahuaikhwang` vs `ideoratchadahuaykhwang` | Spelling variant bucket split |
| `thenichepridethonglorphetchaburi` | Multiple RealXtate name matches (9 aliases) |

## Pantip data quality findings (measured, not fixed)

| Issue | Count | Notes |
|-------|------:|-------|
| Projects missing `zone_verified` | 193 | No trusted zone tags |
| Projects missing `transit_verified` | 138 | No trusted transit tags |
| `pending_verification` status | 119 | Location not fully verified |
| Sparse identity (no aliases, ≤1 listing) | 1,401 | Weak evidence for disambiguation |
| Near-duplicate name prefix groups | 322 | e.g. Life Asoke family, Supalai Veranda variants |
| Duplicate normalized canonical names | 2 | e.g. duplicate iCondo buckets |
| Properties missing `project_id` | 9 | Known from prior audits |
| Projects with coordinates | 0 | Gap vs RealXtate coordinate work |
| Top zone `เจริญนคร` on 587 projects | — | RealXtate audit flags staff zone labels as untrusted noise |
| Top transit `BTS กรุงธนบุรี` on 583 projects | — | Suspicious concentration; likely sheet inheritance artifact |

### Architectural principle confirmed

Employee-entered strings like "ทองหล่อ", "Thonglor", "สุขุมวิท 55" are **raw evidence** in `zone_unverified` / sheet columns. They must not independently become canonical truth. Pantip partially implements this via `zone_verified` / `transit_verified` split, but verified fields often equal unverified copies (2,041 zone, 1,919 transit) — enrichment without independent verification.

## Recommended next phase

See `docs/CANONICAL-PROJECT-SCHEMA-v0.1.md` and `docs/MASTER-DATA-CORRECTION-POLICY.md`.

Phase W should build a **read-only crosswalk table** with evidence packets for the 78 conflicts and import RealXtate marketplace area assignments as **reference overlays** (not production writes).

## References

- Pantip: `src/hub/project_store.py`, `project_identity.py`, `project_location_enrich.py`
- Pantip docs: `docs/DATA-FILE-POLICY.md`, `docs/ARCHITECTURE.md`
- RealXtate: `docs/TRUSTED-PROJECT-MASTER-ARCHITECTURE.md`, `docs/PHASE-8Z3-MARKETPLACE-AREA-FAST-TRACK.md`
- Analysis tool: `scripts/analyze_canonical_project_overlap.py`
