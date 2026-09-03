# Project Crosswalk Review Policy v0.1

Design policy for reviewing LIVE Pantip ↔ RealXtate crosswalk findings. **No corrections applied until explicit owner approval.**

## Inputs

| Input | Authority |
|-------|-----------|
| Fly `/app/data` LIVE snapshot | **Authoritative for Pantip operations** |
| RealXtate trusted master | **Reference only** |
| Git `data/` | **Not authoritative** — stale vs live (78 git-only projects) |
| Crosswalk artifacts in `/tmp/` or Backups | Analysis output — not production |

## Review queue priority bands

| Band | Criteria | Action |
|------|----------|--------|
| **P0** | RealXtate HIGH + Pantip DIRECT_CONFLICT + ≥20 listings | Owner review first |
| **P1** | RealXtate HIGH/MEDIUM + missing Pantip zone + ≥10 listings | Review recommended |
| **P2** | MEDIUM confidence or partial agreement | Queue for later |
| **P3** | Identity conflict, PANTIP_ONLY, insufficient evidence | Manual / defer |

## Correction class mapping

| Class | Meaning | Phase W status |
|-------|---------|----------------|
| AUTO_SAFE | Deterministic, no conflict | None identified for area overlay |
| REVIEW_RECOMMENDED | Strong reference, meaningful change | **134 projects** (true area conflict) |
| MANUAL_REQUIRED | Identity ambiguity | 0 live conflicts; 19 PANTIP_ONLY |
| DO_NOT_TOUCH | Insufficient evidence | Default for unmatched |

## Crosswalk promotion format (future)

Versioned artifact for shared-master architecture:

```json
{
  "crosswalk_version": "0.1",
  "generated_at": "ISO-8601",
  "pantip_project_id": "uuid",
  "canonical_project_id": "uuid",
  "reference_project_id": "uuid",
  "match_class": "EXACT_ID_MATCH",
  "evidence": ["stable_project_id"],
  "review_status": "PENDING",
  "approved_by": null,
  "approved_at": null,
  "area_assignments": [],
  "transit_relations": [],
  "coordinate_candidate": null
}
```

`approved_by` / `approved_at` remain null until future owner review phase. **Discovery ≠ approval.**

## Coordinate trust ladder (design only)

| Class | Meaning |
|-------|---------|
| COORD_VERIFIED_REFERENCE_AVAILABLE | Verified pin in RealXtate |
| COORD_CANDIDATE_REFERENCE_AVAILABLE | SOURCE_PROVIDED pin |
| COORD_MISSING | No coordinates |
| COORD_CONFLICT | State/identity disagreement |

**No coordinate import in Phase W.**

## Phase X recommended scope

Build owner review system v0.1: load review queue, present Pantip vs RealXtate side-by-side, record APPROVE/REJECT/DEFER without applying changes.
