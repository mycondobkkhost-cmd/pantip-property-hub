# Historical Lease Migration Policy

## Recovery result: PARTIAL (not POOR)

- 7 properties with L2 strong evidence (Hubลูกค้าปัจจุบัน)
- 580 with availability-date only (L4)
- 6,370 with no recoverable lease evidence

## Policy

1. **Do not** map วันที่ว่าง to lease_end
2. **Do not** invent 12-month terms from deal dates
3. **Do not** brute-force full historical backfill
4. **Do** sync Hubลูกค้าปัจจุบัน → `current_tenants.json` in a future controlled migration
5. **Do** capture all future deals via lease_record at CONTRACT_STARTED

## Recommendation

**STOP** full historical recovery after Z6. Proceed with future capture + freshness MVP.
