# Shared Master Promotion Policy

## Rules

1. Promotion is **per field**, not per project.
2. T4/T5 cannot silently become canonical.
3. RealXtate `marketplace_area_assignment_8z3` is reference only until re-promoted.
4. Owner master-definition review precedes area semantic approval (Pattanakarn, Rama 9).
5. Z3 defines policy only — **no apply**.

## Denormalized Pantip listing fields

| Field | Policy |
|-------|--------|
| `project_name` | DISPLAY CACHE — regenerate from project master |
| `location_ref` | DISPLAY CACHE |
| `transit_from_sheet` | LEGACY RAW_EVIDENCE |

Do not delete in Z3. Document regeneration path for future promotion.

## Versioning

Each artifact carries: `shared_master_version`, `schema_version`, `generated_at`, `source_snapshot_ids`, `content_hash`.
