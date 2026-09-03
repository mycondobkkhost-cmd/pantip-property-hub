# Lease Opportunity Contract v0.1

## Concept

When rental deal is known, preserve: `lease_start`, `expected_lease_end`, `lease_term`.

## Follow-up windows (configurable)

60, 45, 30, 14 days before lease end.

## Vacancy states

- POSSIBLE_UPCOMING_VACANCY — time-based follow-up only
- FOLLOW_UP_RECOMMENDED — operator prompt
- UPCOMING_VACANCY_CONFIRMED — **only** after owner/authorized confirmation

**Never** infer vacancy from elapsed time alone (12 months ≠ vacant).

## Closed loop

LISTING → VERIFIED → VIEWING → DEAL → LEASE → NEAR END → OWNER CONFIRMATION → REACTIVATED LISTING

User should not recreate entire property record.
