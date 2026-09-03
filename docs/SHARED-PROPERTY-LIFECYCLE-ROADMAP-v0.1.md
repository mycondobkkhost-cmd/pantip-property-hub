# Shared Property Lifecycle Roadmap v0.1

## Vision

```
LISTING CREATED → VERIFIED FRESH → PERIODIC RENEWAL → CUSTOMER INTEREST
→ VIEWING REQUEST → OWNER RESPONSE → RENTED/SOLD → LEASE LIFECYCLE
→ NEAR LEASE END → OWNER FOLLOW-UP → UPCOMING VACANCY CONFIRMED
→ LISTING REACTIVATION
```

## Identity separation

| Layer | ID | Purpose |
|-------|-----|---------|
| Shared Canonical Master | canonical_project_id | WHAT/WHERE the project is |
| Product operational | property_id, listing_id, listing_cycle_id | WHAT IS HAPPENING |

A property may have multiple listing cycles over time.

## Shared vs product-specific

**Shared architecture concepts:** notification event taxonomy, listing lifecycle state model, viewing request contract, lease opportunity contract.

**Product-specific:** Pantip operator workflow, RealXtate owner self-service UI, ranking/bump rules, notification channels, customer profile fields, monetization.

## Implementation sequence

1. Notification foundation
2. Listing freshness + renewal
3. Pantip lease opportunity / near-vacancy workflow
4. RealXtate owner listing lifecycle
5. Viewing request + owner response
6. Deal / lease lifecycle integration
7. Listing reactivation loop

## Boundary

Never add to Canonical Project Master: listing verification, viewing requests, customer profiles, lease dates, notification history.
