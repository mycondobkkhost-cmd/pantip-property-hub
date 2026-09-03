# Pantip Notification Center v0.1

## Principle

**Internal notification event ≠ delivery channel.**

OTP remains authentication/action verification, not normal notification delivery.

## MVP event types

- FOLLOW_UP_OVERDUE
- FOLLOW_UP_DUE_TODAY
- LEASE_END_WITHIN_14_DAYS
- LEASE_END_WITHIN_30_DAYS
- LEASE_END_WITHIN_60_DAYS
- OWNER_CONFIRMED_VACANT_SOON

## Event model

| Field | Purpose |
|-------|---------|
| notification_event_id | Stable id |
| event_type | Taxonomy above |
| recipient_user_id | Operator |
| related_entity_type | e.g. lease_opportunity |
| related_entity_id | Opportunity id |
| created_at | When generated |
| read_at | Independent from dismiss |
| dismissed_at | Independent from read |
| dedupe_key | Prevents duplicate daily alerts |
| priority | normal / high |
| delivery_channel | HUB_NOTIFICATION (MVP) |

## RealXtate compatibility

RealXtate notifications DEFERRED. Contract aligns with future `NOTIFICATION_EVENT_CONTRACT` so Pantip can share event taxonomy when RealXtate implements delivery (WEB, APP_PUSH, EMAIL).

## UI integration

Hub `/lease-opportunities/` — bell icon + badge count + panel.

## Storage

`.local/lease_opportunity_phase_z5/notification_events.json` — TEST_ONLY.
