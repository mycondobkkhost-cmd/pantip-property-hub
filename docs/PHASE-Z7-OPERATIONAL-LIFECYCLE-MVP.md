# Phase Z7 — Operational Lifecycle MVP

## Authoritative data-entry date

- **Canonical concept:** `legacy_record_entered_at`
- **Persisted field:** `properties.last_listed_at`
- **Source:** Sheet column `วันที่รับเข้า` → `build_master.py` `acquired_raw`

Legacy `วันที่ว่าง` is **LEGACY_RAW_EVIDENCE** only — it must not drive follow-up queues, lease opportunity, or `owner_confirmed_available_from`.

## Property status recheck

Age-based `PROPERTY_STATUS_RECHECK` uses data-entry age only. Configurable threshold candidates: 90/180/270/365 days (policy defaults for dry-run).

## Owner-confirmed availability

`owner_confirmed_available_from` is set only via operator contact with explicit date + provenance (`confirmed_at`, `confirmed_by`, `confirmation_source`, `source_contact_event_id`).

## Unified dashboard

Operator page: **งานติดตามทรัพย์** at `/operator-follow-up/`

## Local QA

```bash
bash scripts/start_z7_operational_pilot.sh
python3 scripts/phase_z7_authenticated_qa.py
```

## Production dry-run flags

All dry-runs are TEST_ONLY under `.local/` — no production writes.
