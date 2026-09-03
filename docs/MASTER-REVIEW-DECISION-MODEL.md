# Master Review Decision Model v0.1

## Review item

| Field | Description |
|-------|-------------|
| `review_item_id` | Stable ID: `{review_type}:{project_id}` |
| `review_version` | Schema version (`0.1`) |
| `project_id` | Canonical Pantip project UUID |
| `project_name` | Display name |
| `live_snapshot_listing_count` | Listings at Phase W snapshot |
| `current_value` | Pantip value + semantic kind + verification state |
| `proposed_value` | RealXtate reference + confidence |
| `evidence[]` | Plain-language + technical evidence records |
| `disagreement_class` | e.g. `DIRECT_CONFLICT`, `PANTIP_ONLY` |
| `legacy_promotion_suspected` | `verified == unverified` flag |
| `priority` | P0–P3 |
| `source_snapshot` | `source_hash`, `crosswalk_version` |
| `source_project_fingerprint` | Hash for stale detection |
| `decision` | Current derived status |

## Review types

| Type | Trigger |
|------|---------|
| `AREA_REVIEW` | `DIRECT_CONFLICT` + RealXtate HIGH/MEDIUM |
| `PANTIP_ONLY_REVIEW` | `match_class == PANTIP_ONLY` |
| `TRANSIT_REVIEW` | Designed, not active in v0.1 |
| `IDENTITY_REVIEW` | Designed, not active in v0.1 |

## Decision event (append-only)

Stored in `master_review_decisions.jsonl`:

```
decision_event_id, review_item_id, project_id,
previous_status, new_status, actor, timestamp,
reason, note, source_snapshot_hash, source_project_fingerprint
```

Current status = latest event per `review_item_id`.

## Allowed statuses

`PENDING`, `APPROVED`, `REJECTED`, `DEFERRED`

**Not allowed in Phase X:** `APPLIED`

## Transitions

| From | To |
|------|-----|
| PENDING | APPROVED, REJECTED, DEFERRED |
| DEFERRED | APPROVED, REJECTED, PENDING |
| APPROVED | DEFERRED, REJECTED |
| REJECTED | DEFERRED, APPROVED |

## Approve reasons

- `REFERENCE_EVIDENCE_ACCEPTED`
- `OWNER_KNOWLEDGE`
- `MULTIPLE_SOURCES_AGREE`
- `MARKETPLACE_CLASSIFICATION_ACCEPTED`

## Reject reasons

- `REFERENCE_INCORRECT`
- `PROJECT_DIFFERENT`
- `SEMANTIC_MISMATCH`
- `OWNER_KNOWLEDGE`
- `INSUFFICIENT_EVIDENCE`
