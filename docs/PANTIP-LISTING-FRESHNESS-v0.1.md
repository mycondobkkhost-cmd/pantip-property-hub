# Pantip Listing Freshness v0.1

Aligned to RealXtate `verification-service.ts`:

| RealXtate public_availability | Pantip state |
|------------------------------|--------------|
| available | VERIFIED_AVAILABLE |
| pending_verification | VERIFICATION_DUE |
| expired | STALE_UNCONFIRMED |
| unknown | STALE_UNCONFIRMED |
| unavailable | OWNER_REPORTED_UNAVAILABLE |

## TTL policy

- Rent: 7 days (matches RealXtate)
- Sale: 30 days

## Separation

- Freshness ≠ lease state (STALE ≠ RENTED)
- LISTING_VERIFIED_AVAILABLE ≠ LISTING_BUMP_REQUESTED

## Display (Thai)

- VERIFIED_AVAILABLE: "ยืนยันแล้วว่ายังว่างวันนี้"
- STALE_UNCONFIRMED: never "ยังว่างแน่นอน"

## Storage

`.local/listing_freshness_phase_z6/` — TEST_ONLY
