# Phase Z6 — RealXtate Resync and Lease Data Foundation

## Executive result

RealXtate HEAD **unchanged** from Z5 (`cb7f472`). No new commits. Pantip built lease evidence recovery dry-run, future lease record contract, and listing freshness MVP aligned to RealXtate verification TTL model.

## Historical data recovery: **PARTIAL**

| Category | Count |
|----------|-------|
| STRONG_EXPLICIT_LEASE_END | 7 (Hubลูกค้าปัจจุบัน) |
| AVAILABLE_FROM_ONLY | 580 (วันที่ว่าง date — not lease_end) |
| NO_EVIDENCE | 6,370 |
| IDENTITY_AMBIGUOUS (dup codes) | 30 rows |

## Decision flags

- READY_FOR_PRODUCTION_LEASE_OPPORTUNITIES = **NO** (7 strong of 6,957)
- READY_FOR_FUTURE_LEASE_DATA_CAPTURE = **YES**
- READY_FOR_PANTIP_FRESHNESS_MVP = **YES**
- READY_FOR_PANTIP_FRESHNESS_PRODUCTION_DRY_RUN = **PARTIAL** (local pilot only)
- READY_FOR_FIRST_SHARED_MASTER_PROMOTION_DRY_RUN = **NO**

## วันที่ว่าง conclusion

**MUST NOT map to lease_end.** Semantics: vacancy status (`available`) or **available-from date** (L4), not contract end.

## Next phase

CASE B — stop brute-force historical recovery; implement future lease capture + Pantip freshness first; availability-date follow-up for 580 properties.
