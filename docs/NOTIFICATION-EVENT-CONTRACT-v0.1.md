# Notification Event Contract v0.1

## Event schema

```
notification_event:
  event_id, event_type, actor_id, recipient_id,
  related_entity_type, related_entity_id,
  payload_reference, created_at
```

## Delivery record

`channel`, `delivery_status`, `sent_at`, `delivered_at`, `read_at`, `failed_at`, `failure_reason`

## Event types

LISTING_VERIFICATION_DUE, LISTING_STALE, VIEWING_REQUEST_CREATED, VIEWING_REQUEST_ACCEPTED, VIEWING_REQUEST_DECLINED, VIEWING_ALTERNATIVE_TIME_PROPOSED, LEASE_END_APPROACHING, UPCOMING_VACANCY_CONFIRMED

## Channels (future)

WEB_NOTIFICATION, APP_PUSH, EMAIL, LINE (if approved later)

## OTP role

OTP remains authentication / high-confidence action verification — **not** the normal notification channel.

Product-specific data remains outside Shared Canonical Master.
