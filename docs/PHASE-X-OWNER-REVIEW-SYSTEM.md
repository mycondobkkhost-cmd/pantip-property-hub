# Phase X — Owner Review System

## Purpose

Build an owner-facing review UI to inspect Pantip LIVE vs RealXtate Master reference and **record decisions only**.

**REVIEW ≠ APPLY.** Approving a proposal does not modify production.

## Routes

| Route | Auth | Purpose |
|-------|------|---------|
| `/master-review/` | Session + operator | Thai review UI |
| `GET /api/master-review/summary` | Operator | Dashboard counts |
| `GET /api/master-review/items` | Operator | Filtered queue |
| `GET /api/master-review/items/<id>` | Operator | Single item |
| `GET /api/master-review/export` | Operator | Promotion candidate JSON |
| `POST /api/master-review/decision` | Operator | Record decision |
| `POST /api/master-review/batch-decision` | Operator | Batch DEFER/REJECT only |

## Review source

Immutable Phase W artifact (preferred):

`/Users/angkarn1996/Backups/pantip-property-automation/phase-w-crosswalk-20260904T035800Z/live-project-crosswalk.json`

Override: `MASTER_REVIEW_SOURCE_PATH`

## Queue counts (from Phase W LIVE)

| Type | Count |
|------|------:|
| AREA_REVIEW (DIRECT_CONFLICT, HIGH/MEDIUM) | 134 |
| PANTIP_ONLY_REVIEW | 19 |
| Top 50 prioritized | Available via filter |

## Local development

```bash
export MASTER_REVIEW_SOURCE_PATH=data_fixtures/master_review/sample_crosswalk.json
export MASTER_REVIEW_DATA_DIR=.local/master_review
export HUB_LOCAL_DEV=1
python3 scripts/hub_server.py
# Open http://127.0.0.1:8787/master-review/
```

## Workflow

```
REVIEW → DECISION → PROMOTION CANDIDATE → (future) DRY RUN → OWNER AUTH → (future) APPLY
```

Phase X stops at **PROMOTION CANDIDATE**.
