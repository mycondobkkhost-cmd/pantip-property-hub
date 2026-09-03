# Canonical Project Master Schema v0.1 (Design Only)

**Status:** Design proposal — not implemented. No database migration in Phase V.

Derived from Pantip `projects.json` field profile, RealXtate `project_master_v01` / `trusted_projects` schemas, and the architectural principle that listings inherit canonical facts from project master.

## Design goals

1. **One canonical project identity** per real-world condominium/project
2. **Raw employee text is evidence**, not truth
3. **Marketplace area ≠ administrative district ≠ transit station**
4. **Confidence and provenance** on every non-trivial field
5. **Listings reference `canonical_project_id`**; they do not own location truth
6. **No silent auto-merge** of ambiguous projects

## Canonical Project Master

| Field | Type | Canonical / Derived | Required | Source priority | Confidence required | Conflict behavior | Listings inherit? |
|-------|------|-------------------|----------|-----------------|---------------------|-------------------|-------------------|
| `canonical_project_id` | UUID | Canonical | Yes | T1: existing Pantip `project.id` if verified | HIGH | Never auto-change | Yes (FK) |
| `legacy_bucket_key` | string | Canonical (legacy) | Yes | T1: Pantip `bucket_key` | HIGH | Preserve; map not replace | No (internal) |
| `canonical_name_th` | string | Canonical | Yes* | T1: verified name split; T2: LI/PH directory; T4: sheet | MEDIUM+ for auto | Human review if names disagree | Yes (display) |
| `canonical_name_en` | string | Canonical | No | T1/T2 structured sources; T4 sheet | MEDIUM+ | Review if TH/EN mismatch | Yes (display) |
| `display_name` | string | Derived | No | Computed from TH/EN preference | — | — | Yes |
| `aliases` | AliasEvidence[] | Canonical (as claims) | No | T3: multiple agreeing records; T4: sheet variants | Per-alias | Never merge on alias alone | No (search only) |
| `identity_state` | enum | Derived | Yes | Rules engine | — | QUARANTINED blocks downstream | No |
| `identity_resolution_status` | enum | Derived | Yes | `RESOLVED` / `REVIEW_REQUIRED` / `QUARANTINED` | — | — | No |
| `latitude` | float | Canonical | No | T1: verified pin; T2: PH strict acceptance; T5: geocode | HIGH for canonical use | Reject outside metro bbox | Yes (map) |
| `longitude` | float | Canonical | No | Same as latitude | HIGH | Same | Yes (map) |
| `coordinate_state` | enum | Derived | Yes | `VERIFIED` / `SOURCE_PROVIDED` / `QUESTIONABLE` / `NONE` | — | NONE blocks area assignment | No |
| `province` | string | Canonical | No | T2: admin directory; T1: verified address parse | MEDIUM+ | Admin consistency veto | Yes |
| `district` | string | Canonical | No | T2: khet from parsed address | MEDIUM+ | Veto if conflicts with coords | Yes |
| `subdistrict` | string | Canonical | No | T2: khwaeng from parsed address | MEDIUM+ | Veto if conflicts | Yes |
| `postal_code` | string | Canonical | No | T2: structured address | LOW+ | Optional | Yes |
| `address_normalized` | string | Canonical | No | T2: parsed Thai address | MEDIUM | — | Yes |
| `developers` | DeveloperRef[] | Relationship | No | T2: developer directory; T4: sheet | MEDIUM+ | Multiple allowed | Yes |
| `project_type` | enum | Canonical | No | T2: directory classification | LOW+ | — | Optional |
| `completion_year` | int | Canonical | No | T2: external ref | MEDIUM | — | Optional |
| `building_count` | int | Canonical | No | T2 | LOW+ | — | No |
| `floor_count` | int | Canonical | No | T2 | LOW+ | — | No |
| `transit_relations` | TransitRelation[] | Relationship | No | T1: transit master match; T4: sheet (untrusted alone) | MEDIUM+ per link | Sheet-only → CANDIDATE not VERIFIED | Yes (nearest stations) |
| `administrative_relations` | AdminRelation[] | Relationship | No | T2: official geography | MEDIUM+ | Consistency check only | Yes |
| `marketplace_area_relations` | AreaAssignment[] | Classification | No | T2: area assignment engine | HIGH/MEDIUM for product; LOW reference only | Multi-area allowed (max 3) | Yes (browse/filter) |
| `source_records` | SourceRecord[] | Evidence | No | All tiers | — | — | No |
| `evidence` | Evidence[] | Evidence | No | All tiers | Per-claim | — | No |
| `overall_confidence` | enum | Derived | Yes | Weakest dimension (RealXtate pattern) | — | — | No |
| `review_status` | enum | Workflow | Yes | `AUTO_SAFE` / `REVIEW_RECOMMENDED` / `MANUAL_REQUIRED` / `DO_NOT_TOUCH` | — | — | No |
| `listing_count` | int | Derived | No | Count of linked listings | — | — | No |
| `created_at` | timestamp | Provenance | Yes | System | — | — | No |
| `updated_at` | timestamp | Provenance | Yes | System | — | — | No |

*`canonical_name_th` required when Thai market is primary; may be satisfied by `canonical_name` during Pantip migration.

### Nested types (conceptual)

**AliasEvidence**
```
{ raw_value, normalized_value, source, source_record_id, confidence, review_status }
```

**TransitRelation**
```
{ station_id, system, line, straight_line_distance_m, distance_band, relationship_confidence, evidence_families[] }
```

**AreaAssignment**
```
{ area_id, role: PRIMARY|SECONDARY|EDGE, confidence: HIGH|MEDIUM|LOW, evidence_families[], meters_to_anchor, assignment_version }
```

**Evidence**
```
{ field, claim, source_tier, source_type, source_ref, independence_group, confidence, observed_at }
```

## Area Master v0.1

Marketplace areas are **property-discovery classifications**, not official administrative boundaries.

| Field | Type | Notes |
|-------|------|-------|
| `area_id` | string | Stable slug (e.g. `thonglor`, `ekkamai`) |
| `canonical_name_th` | string | Display |
| `canonical_name_en` | string | Display |
| `aliases` | string[] | Including road/soi variants |
| `area_type` | enum | `MARKETPLACE`, `CORRIDOR`, `TRANSIT_HUB` |
| `parent_area_id` | string? | Hierarchy (e.g. Sukhumvit parent) |
| `anchor_strategy` | enum | `STATION`, `COORDINATE`, `ROAD_CORRIDOR` |
| `anchor_refs` | string[] | Station IDs or coordinate refs |
| `core_radius_m` | int | Default 1000 (RealXtate) |
| `extended_radius_m` | int | Default 2200 |
| `geometry_strategy` | string | Start with station-radius; defer polygon |
| `marketplace_purpose` | string | Search/browse grouping |
| `evidence_rules` | json | Assignable evidence families |
| `review_status` | enum | `APPROVED`, `DRAFT`, `RETIRED` |

Import RealXtate's 31 approved Bangkok areas as **seed vocabulary**, not as automatic Pantip truth.

## Transit Master v0.1

| Field | Type | Notes |
|-------|------|-------|
| `station_id` | string | Stable (e.g. `bts_thonglor`) |
| `system` | enum | BTS, MRT, ARL, SRT |
| `line` | string | Line name |
| `canonical_name_th` | string | |
| `canonical_name_en` | string | |
| `aliases` | string[] | Including common misspellings |
| `latitude` | float | From OSM/Nominatim after identity confirm |
| `longitude` | float | |
| `operational_status` | enum | `OPERATIONAL`, `CONSTRUCTION`, `PLANNED` |

Pantip `transit_master.json` and RealXtate `transit-seed.ts` (169 stations) should be reconciled into one master — do not trust listing/sheet station strings directly.

## Developer Master v0.1

| Field | Type | Notes |
|-------|------|-------|
| `developer_id` | string | Stable slug |
| `canonical_name_th` | string | |
| `canonical_name_en` | string | |
| `aliases` | string[] | Brand variants |
| `brand_relationships` | ref[] | Parent developer, JV partners |

Not present in Pantip today; optional for v0.1 implementation.

## Administrative Geography v0.1

| Field | Type | Notes |
|-------|------|-------|
| `admin_id` | string | Official code if available |
| `level` | enum | `PROVINCE`, `DISTRICT`, `SUBDISTRICT` |
| `name_th` | string | |
| `name_en` | string | |
| `parent_admin_id` | string? | |
| `postal_codes` | string[] | |

Used for **consistency veto**, not primary marketplace classification.

## Project Alias / Identity Evidence v0.1

| Field | Type | Notes |
|-------|------|-------|
| `evidence_id` | UUID | |
| `raw_value` | string | As entered (sheet, import, user) |
| `normalized_value` | string | After `soft_norm` |
| `semantic_kind` | enum | `project`, `area`, `station`, `road`, `admin`, `unknown` |
| `source` | enum | `SHEET`, `HUB`, `LIVINGINSIDER`, `PROPERTYHUB`, `IMPORT`, `OPERATOR` |
| `source_record_id` | string? | Listing code, sheet row, etc. |
| `candidate_project_id` | UUID? | If resolved |
| `confidence` | enum | HIGH / MEDIUM / LOW |
| `review_status` | enum | `PENDING`, `ACCEPTED`, `REJECTED` |

Pantip `project_aliases.json` `variant_to_canonical` maps become **accepted evidence rows**, not silent truth without review metadata.

## Source priority hierarchy (proposed)

| Tier | Name | Examples | May set canonical truth? |
|------|------|----------|--------------------------|
| T1 | Verified canonical evidence | Owner-approved merge, verified coordinate pin, confirmed alias decision | **YES** (with audit) |
| T2 | High-confidence structured external | PropertyHub strict identity match, LivingInsider project page, OSM station coords, admin directory | **YES** with confidence gate |
| T3 | Multiple agreeing internal records | ≥2 listings same bucket + same admin parse + compatible coords | **CANDIDATE only** |
| T4 | Employee-entered sheet values | `โครงการ`, `ทำเล`, `สถานีรถไฟฟ้า` columns | **Evidence only** — never alone |
| T5 | AI / fuzzy inference | LLM geocode, fuzzy name match, embedding similarity | **NEVER silent overwrite** |

**Critical rule:** T5 alone must never promote to canonical. T4 → canonical requires T2 corroboration or T1 human approval.

## Listing inheritance rules

### Should inherit from Project Master (when linked)

- Canonical project name (TH/EN)
- Coordinates (if confidence ≥ MEDIUM)
- Province / district / subdistrict
- Marketplace area(s) with confidence
- Nearby transit (from transit_relations, not raw sheet strings)
- Developer (when available)

### Must remain listing-specific

- Price, bedrooms, bathrooms, size, floor
- Rent/sale status, availability, pet policy
- Owner/agent contact details
- Listing description, photos, captions
- `property_code` (may duplicate across projects)
- Historical raw `project_name` as **evidence** (preserve, do not delete)

### Sync behavior (future)

```
listing.project_id → canonical_project_master
                 → projected fields refreshed on master change
                 → raw sheet fields preserved in evidence table
```

Fix one project → N listings update classification without rewriting historical import text.

## Mapping from current Pantip fields

| Pantip field | v0.1 destination |
|--------------|------------------|
| `id` | `canonical_project_id` |
| `bucket_key` | `legacy_bucket_key` |
| `canonical_name` | `canonical_name_th` or `display_name` (split TH/EN) |
| `aliases` | `aliases[]` as AliasEvidence |
| `zone_verified` | Input to area assignment; not canonical area alone |
| `transit_verified` | Candidate transit_relations after station master match |
| `zone_unverified` / `transit_unverified` | Identity evidence (T4) |
| `location_status` | Maps to `review_status` partially |
| `location_source` | `source_records[]` |
| `living_project_url` | External source ref (T2) |
| `listing_count` | Derived |

## What is explicitly out of scope for v0.1 schema

- Full polygon geometry for areas
- Walking-distance routing (use straight-line + bands initially)
- Automatic project merge execution
- Supabase/Postgres physical migration (design only)
