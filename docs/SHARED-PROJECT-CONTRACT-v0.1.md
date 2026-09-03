# Shared Project Contract v0.1

## Canonical project record

| Field | Classification |
|-------|----------------|
| `canonical_project_id` | CANONICAL_CANDIDATE |
| `existing_product_ids.pantip_project_id` | CANONICAL_CANDIDATE |
| `existing_product_ids.realxtate_project_id` | CANONICAL_CANDIDATE |
| `canonical_name_th/en` | CANONICAL_CANDIDATE |
| `aliases[]` | RAW_EVIDENCE until promoted |
| `coordinate_state`, `canonical_coordinate` | CANONICAL_CANDIDATE |
| `marketplace_area_relations[]` | CANONICAL_CANDIDATE (per-field promotion) |

## Excluded from canonical master

Listing price, availability, owner/tenant name, phone, LINE, property description, property_code.

## Pantip-only projects (19)

Supported via `PRODUCT_ONLY_VALID`, `IDENTITY_REVIEW_REQUIRED`, `NON_PROJECT_ENTITY_REVIEW`, `POSSIBLE_REALXTATE_MISSING_PROJECT`.

## Field-level promotion

Identity READY does not imply coordinate or area READY. No project-level `verified=true`.

## Correction propagation

```
listing → project_id → canonical project → marketplace area relations
```

One canonical correction updates all listings via project inheritance.
