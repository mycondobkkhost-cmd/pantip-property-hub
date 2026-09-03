# Listing Freshness and Renewal Contract v0.1

## Fields (product operational layer)

- `listing_verification_status`
- `last_owner_verified_at`
- `verification_due_at`
- `listing_freshness_state`

## States

VERIFIED_AVAILABLE, VERIFICATION_DUE, VERIFICATION_OVERDUE, OWNER_REPORTED_UNAVAILABLE, RENTED, SOLD, PAUSED, STALE_UNCONFIRMED

## Renewal / bump separation

Owner confirms still available → updates `last_owner_verified_at` → renews freshness → **optional separate** ranking/bump event.

Freshness confirmation and ranking boost are distinct internal concepts even if one UI action triggers both.

## UX examples

- "ยืนยันแล้วว่ายังว่างวันนี้"
- "เจ้าของยืนยันล่าสุด 3 วันที่แล้ว"
- "กำลังรอเจ้าของยืนยันสถานะ"

Do not claim AVAILABLE if verification is stale/unknown.
