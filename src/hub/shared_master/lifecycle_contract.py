"""Operational lifecycle contracts — Phase Z4 Track B (documentation/schema only)."""

from __future__ import annotations

# Fields that must NEVER appear in canonical project master.
CANONICAL_PROJECT_EXCLUDED_OPERATIONAL = frozenset(
    {
        "listing_verification_status",
        "last_owner_verified_at",
        "verification_due_at",
        "listing_freshness_state",
        "viewing_request_id",
        "customer_profile",
        "notification_history",
        "lease_start",
        "lease_end",
        "lease_term",
        "rent_price",
        "sale_price",
        "property_code",
        "owner_phone",
        "owner_line",
        "tenant_name",
    }
)

LISTING_FRESHNESS_STATES = frozenset(
    {
        "VERIFIED_AVAILABLE",
        "VERIFICATION_DUE",
        "VERIFICATION_OVERDUE",
        "OWNER_REPORTED_UNAVAILABLE",
        "RENTED",
        "SOLD",
        "PAUSED",
        "STALE_UNCONFIRMED",
    }
)

NOTIFICATION_EVENT_TYPES = frozenset(
    {
        "LISTING_VERIFICATION_DUE",
        "LISTING_STALE",
        "VIEWING_REQUEST_CREATED",
        "VIEWING_REQUEST_ACCEPTED",
        "VIEWING_REQUEST_DECLINED",
        "VIEWING_ALTERNATIVE_TIME_PROPOSED",
        "LEASE_END_APPROACHING",
        "UPCOMING_VACANCY_CONFIRMED",
    }
)

VIEWING_RESPONSES = frozenset(
    {
        "ACCEPT",
        "DECLINE",
        "PROPOSE_ALTERNATIVE_TIME",
        "PROPERTY_NOT_AVAILABLE",
        "NEED_MORE_INFORMATION",
    }
)

VACANCY_STATES = frozenset(
    {
        "POSSIBLE_UPCOMING_VACANCY",
        "FOLLOW_UP_RECOMMENDED",
        "UPCOMING_VACANCY_CONFIRMED",
    }
)

IMPLEMENTATION_SEQUENCE = [
    "1. Notification foundation",
    "2. Listing freshness + renewal",
    "3. Pantip lease opportunity / near-vacancy workflow",
    "4. RealXtate owner listing lifecycle",
    "5. Viewing request + owner response",
    "6. Deal / lease lifecycle integration",
    "7. Listing reactivation loop",
]
