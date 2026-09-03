# Phase Z4 Identity Accounting

## Formula

```
TOTAL LIVE (2,175)
  = SHARED_CANONICAL_IDENTITY_READY (2,128)
  + PRODUCT_ONLY_IDENTITY_READY (3)
  + IDENTITY_REVIEW_REQUIRED (37)
  + NON_PROJECT_ENTITY_REVIEW (7)
```

## Z3 discrepancy: 2,128 vs 2,159

| Metric | Count | Definition |
|--------|-------|------------|
| CANONICAL_IDENTITY_READY (Z3 contract) | 2,128 | EXACT_ID_MATCH + identity_state=CATALOG_IDENTITY |
| Identity field READY (Z3 readiness bug) | 2,159 | All EXACT_ID_MATCH (2,156) + 3 product-only valid |

**Gap = 31** = 28 identity_state review + 3 product-only counted as field READY

## Z4 fix

`readiness.identity_status` now uses `identity_accounting` buckets:
- `READY` = SHARED_CANONICAL_IDENTITY_READY only (2,128)
- `PRODUCT_ONLY_VALID` = 3
- `REVIEW_REQUIRED` = 37
- `NON_PROJECT_ENTITY_REVIEW` = 7
