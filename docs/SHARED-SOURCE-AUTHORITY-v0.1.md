# Shared Source Authority v0.1

## Source tiers

| Tier | Meaning | May promote? |
|------|---------|--------------|
| T1 | Owner-approved / verified pin | Yes (manual) |
| T2 | Trusted structured reference | Yes (future auto for coords) |
| T3 | Multiple corroborating sources | Yes (future auto for coords) |
| T4 | Historical employee/source evidence | No |
| T5 | Fuzzy / weak inferred | No |

## Coordinate promotion mapping

- T1 → VERIFIED
- T2 → TRUSTED_REFERENCE
- T3 → CORROBORATED
- T4 → CANDIDATE
- T5 → MISSING

Fail-closed. Never silent overwrite. Preserve history.

## Legacy Living/employee data

Always `RAW_EVIDENCE`. Preserve raw value, source, lineage, timestamp.

## Lineage deduplication

Copied source in multiple databases = ONE lineage.
