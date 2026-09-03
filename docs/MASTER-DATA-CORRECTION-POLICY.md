# Master Data Correction Policy v0.1 (Design Only)

**Status:** Policy design — no corrections applied in Phase V.

This policy governs how Pantip (and eventually RealXtate) may change canonical project master data in future phases.

## Core principles

1. **Production `/app/data` is authoritative** for current operations until an explicit approved migration phase runs.
2. **Discovery ≠ correction.** Analysis may propose; only approved workflows apply.
3. **Never wholesale restore** stash, recovery branch, or Git snapshots into production.
4. **Raw employee text is preserved** as evidence even when canonical fields change.
5. **AI/fuzzy inference never silently overwrites** canonical truth.

## Correction classes

| Class | Criteria | Auto-apply? | Example |
|-------|----------|-------------|---------|
| **AUTO_SAFE** | Deterministic identity; single strong signal; no conflict; no canonical field removal | Yes (with audit log) | Sync `listing_count` from actual FK count |
| **REVIEW_RECOMMENDED** | High confidence but meaningful canonical change | No — operator queue | Adopt RealXtate HIGH marketplace area for project with matching ID |
| **MANUAL_REQUIRED** | Ambiguity, conflict, or merge candidate | No — owner decision | `thesaintresidence` vs `thesaintresidences` bucket split |
| **DO_NOT_TOUCH** | Insufficient evidence | Never | Fuzzy name-only match; single sheet zone tag |

## Evidence requirements by change type

| Change type | Minimum evidence | Class |
|-------------|------------------|-------|
| Set canonical coordinates | T1 verified OR T2 strict PH acceptance + identity match | REVIEW_RECOMMENDED minimum |
| Add marketplace area | T2 area assignment HIGH with ≥2 evidence families | REVIEW_RECOMMENDED |
| Add marketplace area (MEDIUM) | T2 assignment + no admin veto | REVIEW_RECOMMENDED |
| Merge two projects | T1 owner approval only | MANUAL_REQUIRED |
| Rename canonical project | T1 or T2 directory + no conflict | REVIEW_RECOMMENDED |
| Fix transit relation | T2 station master match + distance band | AUTO_SAFE if deterministic match |
| Copy sheet zone → zone_verified | T4 only | **DO_NOT_TOUCH** (insufficient) |
| Import RealXtate area to Pantip | Same `project_id` + confidence HIGH/MEDIUM | REVIEW_RECOMMENDED |
| Change `project_id` on listing | T1 only + orphan prevention | MANUAL_REQUIRED |

## Workflow (future phases)

```
DISCOVER  →  offline analysis, crosswalk, quality report
    ↓
CANDIDATE →  proposed change with affected listing count
    ↓
EVIDENCE  →  tier, source refs, independence groups
    ↓
CONFIDENCE → HIGH / MEDIUM / LOW / UNASSIGNED
    ↓
REVIEW    →  operator or owner queue (by class)
    ↓
APPROVE   →  explicit authorization recorded
    ↓
APPLY     →  transactional write + backup before batch
    ↓
AUDIT LOG →  immutable record: who, when, what, why, before/after
```

**Phase V stops before CANDIDATE apply.**

## Batch correction strategy

Goal: **fix one project correctly → many listings inherit**.

| Step | Action |
|------|--------|
| 1 | Identify project with bad inherited `location_ref` / area |
| 2 | Build evidence packet from masters (not from one listing) |
| 3 | Update canonical project master only |
| 4 | Run `sync_project_listings_location_ref()` equivalent |
| 5 | Verify listing sample; log counts changed |
| 6 | Do **not** edit thousands of listings individually |

## Conflict handling

| Conflict type | Policy |
|---------------|--------|
| Same name, different bucket | MANUAL_REQUIRED — never auto-merge |
| Same bucket, different RealXtate ID | BLOCK — identity corruption signal |
| Coordinates vs admin mismatch | Admin is veto only; coords win for map, admin flagged |
| Multiple HIGH marketplace areas | Allowed up to 3 with roles (PRIMARY/SECONDARY/EDGE) |
| Sheet transit contradicts station master | Sheet → evidence; station master → canonical relation |

## Production safety gates (before any APPLY phase)

- [ ] Explicit owner authorization in phase prompt
- [ ] Fresh live health check (1 machine, volume mounted)
- [ ] T-0 backup of `/app/data`
- [ ] Dry-run count of affected projects/listings
- [ ] Rollback plan documented
- [ ] No deploy required for data-only correction (preferred) OR deploy separated from data migration

## Pantip-specific known debt (do not auto-fix)

| Item | Count (Git snapshot) | Policy |
|------|---------------------|--------|
| Properties missing `project_id` | 9 | MANUAL_REQUIRED per listing |
| Projects `pending_verification` | 119 | Review individually |
| 78 Pantip/RealXtate bucket conflicts | 78 | Phase W crosswalk |
| Staff zone label concentration (`เจริญนคร` 587) | — | DO_NOT_TOUCH without area engine |
| 0 project coordinates | 2,234 | Import from RealXtate T2 only via REVIEW |

## RealXtate knowledge import rules

| Import | Policy |
|--------|--------|
| Marketplace area assignments | REVIEW_RECOMMENDED overlay by `project_id` |
| Transit master seed | AUTO_SAFE for master table only (not project relations) |
| Normalization functions | AUTO_SAFE for code port (not data) |
| Identity decision packets | Reference only — Pantip-specific review |
| Coordinate ledger | DO_NOT_TOUCH without Pantip pin source equivalent |

## Audit log minimum fields

```
change_id, timestamp, actor, phase_id,
entity_type, entity_id, field,
before_value, after_value,
evidence_tier, evidence_refs[],
correction_class, approval_ref,
affected_listing_count
```

## Shared architecture recommendation

See Phase V report. Recommended: **Option C** — canonical master as versioned export artifact; each product holds local copy synchronized on explicit promotion. Simplest for current scale; avoids premature shared service operational burden.

## Explicit non-actions (Phase V and until authorized)

- NO production data mutation
- NO project merges
- NO `project_id` changes
- NO area/transit/zone overwrites from RealXtate import
- NO stash/recovery restore
- NO Runtime Git Migration
