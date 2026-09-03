# Phase Z5 — RealXtate ↔ Pantip Cross-Product Sync

## Executive result

Phase Z5 inspected **actual** RealXtate state (read-only) at `cb7f472`, compared against Pantip Z4 baseline, updated shared operational capability contracts, and built Pantip lease opportunity + notification center **foundation only** with TEST_ONLY local storage.

**READY_FOR_PANTIP_LEASE_OPPORTUNITY_MVP=NO** — production rental data has **0** high-confidence lease end dates; MVP UI uses fixtures only.

## RealXtate latest state

| Item | Value |
|------|-------|
| Branch | `main` |
| HEAD | `cb7f4725598b349fc0cbd003190e757c9551136b` |
| Latest phase | 9B provenance foundation + 8Z marketplace master |
| Canonical listing | `listings.id` (catalog SQLite) |
| Source records | Parallel provenance SQLite (9B) |
| Freshness | IMPLEMENTED (verification overlay + TTL) |
| Renewal | NOT_FOUND |
| Notifications | DEFERRED |
| Viewing | FOUNDATION_ONLY (lead form stub) |
| Lease lifecycle | NOT_FOUND |

## Pantip lease data discovery

- 6,957 rental properties in `properties.json`
- No `contract_start` / `contract_end` on properties
- `วันที่ว่าง` read from sheet but **not stored**
- `current_tenants.json` absent (0 tenant records)
- **HIGH_CONFIDENCE_FOLLOWUP = 0**

## Deliverables

- `src/hub/cross_product_sync.py` — RealXtate inventory + diff
- `src/hub/operational_contracts.py` — shared operational contracts
- `src/hub/lease_opportunity.py` — evidence classes, local storage
- `src/hub/notification_center.py` — event model, dedupe
- `hub/lease-opportunities/index.html` — local authenticated UI
- `/tmp/pantip-phase-z5-sync/*.json` — sync artifacts

## Gates

All Z5 gates documented in test output. Owner master decisions unchanged (Pattanakarn/Rama 9 REVIEW_REQUIRED).

## Next action

Import or sync explicit lease dates (`current_tenants.json` / sheet) before production lease opportunity rollout.
