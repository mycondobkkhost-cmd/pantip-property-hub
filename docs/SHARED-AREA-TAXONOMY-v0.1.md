# Shared Area Taxonomy v0.1

## Semantic kinds (not interchangeable)

| Kind | Example |
|------|---------|
| MARKETPLACE_GROUP | Phrom Phong–Thonglor–Ekkamai, Asoke–Rama 9 |
| MARKETPLACE_AREA | Thonglor, Ekkamai, On Nut |
| CORRIDOR | Phatthanakan (พัฒนาการ) |
| TRANSIT_HUB | MRT สวนหลวง ร.9 |
| ADMIN_AREA | เขตสวนหลวง |

## Group ↔ sub-area model

Groups contain member areas via `member_relations[]` with `MEMBER`/`BRIDGE`/`OVERLAP` — not PRIMARY/SECONDARY.

Project ↔ area uses PRIMARY/SECONDARY/EDGE separately.

## Semantic reviews (Z3)

| Area | Status | Recommendation |
|------|--------|----------------|
| Rama 9 | CANDIDATE_OWNER_REVIEW | MARKETPLACE_GROUP with child areas |
| Phatthanakan | READY_FOR_OWNER_REVIEW | CORRIDOR (+ optional search relation) |
| Suan Luang | INSUFFICIENT_EVIDENCE | Separate admin vs marketplace vs transit |
| Sukhumvit | PARTIAL_EVIDENCE | CORRIDOR + group hierarchy, not single area |

## RealXtate 8z3 assignments

Classified as `REFERENCE_ASSIGNMENT`, not canonical truth.
