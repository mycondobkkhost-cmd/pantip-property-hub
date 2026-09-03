# Shared Operational Capability Contracts v0.1

## Layer separation

**SHARED CANONICAL MASTER** = WHAT / WHERE only (projects, areas, transit, coordinates).

**SHARED PRODUCT CAPABILITY CONTRACTS** = operational concepts implemented independently per product.

Shared contract ≠ shared runtime database.

## Contracts

| Contract | Purpose |
|----------|---------|
| PROPERTY_IDENTITY_CONTRACT | `property_id` stable; `property_code` display-only |
| LISTING_IDENTITY_CONTRACT | `listing_id` ≠ `property_id` |
| LISTING_CYCLE_CONTRACT | Many cycles per property; no eternal listing |
| SOURCE_PROVENANCE_CONTRACT | Source rows map to canonical; retain UNLINKED/REJECTED |
| LISTING_FRESHNESS_CONTRACT | Verification states; bump separate from verify |
| NOTIFICATION_EVENT_CONTRACT | Event ≠ delivery channel; OTP not notification |
| VIEWING_REQUEST_CONTRACT | Customer snapshot, slots, response vocabulary |
| DEAL_LIFECYCLE_CONTRACT | Inquiry → close pipeline |
| LEASE_LIFECYCLE_CONTRACT | Active → ended → vacant confirmed |
| LEASE_OPPORTUNITY_CONTRACT | Near-vacancy follow-up; time ≠ vacant |

## Identity model

```
canonical_project_id
      ↓
property_id
      ↓
listing_cycle_id
      ↓
listing_id

source_record_id → mapping → property_id / listing_id
```

## Excluded from Shared Master

Owner contact, customer profile, listing freshness, viewing, lease dates, notifications, marketing follow-up.

## Implementation

- Pantip Z5: lease opportunity + notification foundation (local TEST_ONLY)
- RealXtate: freshness implemented; notifications/lease deferred
