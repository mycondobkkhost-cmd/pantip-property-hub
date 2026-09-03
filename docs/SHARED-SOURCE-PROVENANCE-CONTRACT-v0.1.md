# Shared Source Provenance Contract v0.1

Aligned to RealXtate Phase 9B `SOURCE-PROVENANCE-MODEL.md` (read-only inspection).

## Entity: SOURCE_RECORD

| Field | Description |
|-------|-------------|
| source_system | FACEBOOK_MANUAL, PANTIP_LEGACY, LIVING, OWNER_DIRECT, … |
| source_listing_id | External stable id within source system |
| source_url | Observation URL |
| observed_at | When source was seen |
| raw_fingerprint | Hash or payload fingerprint |
| mapping_status | UNLINKED, LINKED, REJECTED, CONFLICT, QUARANTINED, REVIEW_REQUIRED |
| canonical_property_id | Nullable until linked |
| canonical_listing_id | Nullable until linked |
| evidence | Supporting linkage evidence |

## Idempotency

Unique key: `(source_system, source_listing_id)`

Re-import refreshes raw fields; does not wipe canonical link by default.

## Rules

1. **Source record ≠ canonical property** — mapping is explicit.
2. **REJECTED ≠ delete** — retain for audit.
3. **UNLINKED** — valid terminal state until reviewed.
4. **CONFLICT** — multiple canonical candidates; human resolution.

## RealXtate status

FOUNDATION_ONLY — parallel `realxtate-provenance.sqlite`; not live-wired to all ingestion paths.

## Pantip status

Contract defined Z5; import pipeline not implemented.
