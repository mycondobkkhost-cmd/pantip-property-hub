# Lease Evidence Authority v0.1

## Levels

| Level | Source | Strong for near-vacancy? |
|-------|--------|--------------------------|
| L1 | Explicit contract record start/end | Yes |
| L2 | Hubลูกค้าปัจจุบัน / tenant_store | Yes |
| L3 | contract_start + explicit term months | Yes |
| L4 | Owner availability date (วันที่ว่าง date) | No — AVAILABILITY_DATE_FOLLOWUP only |
| L5 | Deal/rented date only | No — candidate only |
| L6 | Legacy ambiguous | No |

## วันที่ว่าง

- `available` → vacancy status, not a date
- Date patterns → AVAILABLE_FROM_DATE — **never lease_end**
- Month-only (Feb 2025) → OWNER_EXPECTED — confirm with owner

## Identity linkage

Prefer `property_id`. `property_code` duplicate → FAIL CLOSED (300 duplicate codes in catalog).
