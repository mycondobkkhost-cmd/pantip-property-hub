# Pantip Lease Opportunity v0.1

## Business purpose

Proactive **ทรัพย์ใกล้ครบสัญญา / โอกาสทำตลาด** — contact owner before other agents.

## Vacancy safety rule

**TIME ALONE MUST NEVER MEAN VACANT.**

| Condition | Status |
|-----------|--------|
| Expected lease end approaching | FOLLOW_UP_RECOMMENDED |
| Owner confirms vacancy | OWNER_CONFIRMED_VACANT_SOON |
| Elapsed 12 months without confirmation | Never → AVAILABLE |

## Evidence classes

| Class | Strong? | Notes |
|-------|---------|-------|
| CONFIRMED_LEASE_END | Yes | Explicit `contract_end` |
| DERIVED_FROM_EXPLICIT_TERM | Yes | Start + term months |
| ESTIMATED_12M_CANDIDATE | No | Shows disclaimer คาดการณ์จากรอบเช่าเดิม ยังไม่ได้ยืนยันจากเจ้าของ |
| DEAL_DATE_ONLY_CANDIDATE | No | Acquisition/deal date only |
| INSUFFICIENT_EVIDENCE | No | No usable dates |

## Opportunity statuses

UPCOMING, FOLLOW_UP_DUE, CONTACTED_WAITING, OWNER_CONFIRMED_VACANT_SOON, TENANT_RENEWED, OWNER_NOT_MARKETING, CONTACT_FAILED, DEFERRED, CLOSED

## Follow-up windows (configurable)

Default: 60, 45, 30, 14 days before expected end.

## Deduplication

One active opportunity per `property_id` + `listing_cycle_id`. `property_code` is NOT mutation identity.

## Contact events (append-only)

Results: OWNER_CONFIRMED_VACANCY, TENANT_RENEWED, OWNER_NOT_MARKETING, WAITING_FOR_OWNER, CONTACT_FAILED, CALLBACK_REQUESTED

## Storage

`.local/lease_opportunity_phase_z5/` — gitignored, TEST_ONLY.

## Data readiness (Z5 audit)

- RENTAL_PROPERTIES_TOTAL: 6,957
- HIGH_CONFIDENCE_FOLLOWUP: 0
- **DATA_NOT_READY_FOR_MVP** on production data; fixtures for local UI.
