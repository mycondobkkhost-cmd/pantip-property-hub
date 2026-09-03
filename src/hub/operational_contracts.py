"""Shared operational capability contracts — Phase Z5."""

from __future__ import annotations

# Identity fields (conceptual; not shared runtime DB)
IDENTITY_FIELDS = frozenset(
    {
        "canonical_project_id",
        "property_id",
        "listing_id",
        "listing_cycle_id",
        "source_record_id",
        "deal_id",
        "lease_id",
        "viewing_request_id",
    }
)

PROPERTY_IDENTITY_CONTRACT = {
    "version": "0.1",
    "rule": "property_id is stable product identity; property_code is display-only",
    "mutation_identity": "property_id",
    "excluded_from_mutation": ["property_code"],
}

LISTING_IDENTITY_CONTRACT = {
    "version": "0.1",
    "rule": "listing_id != property_id; listing belongs to a listing_cycle",
    "mutation_identity": "listing_id",
}

LISTING_CYCLE_CONTRACT = {
    "version": "0.1",
    "rule": "One property may have many listing cycles over time; do not model one eternal listing",
    "fields": ["listing_cycle_id", "property_id", "cycle_started_at", "cycle_ended_at"],
}

SOURCE_PROVENANCE_CONTRACT = {
    "version": "0.1",
    "entity": "SOURCE_RECORD",
    "fields": [
        "source_system",
        "source_listing_id",
        "source_url",
        "observed_at",
        "raw_fingerprint",
        "mapping_status",
        "canonical_property_id",
        "canonical_listing_id",
        "evidence",
    ],
    "mapping_statuses": ["UNLINKED", "LINKED", "REJECTED", "CONFLICT", "QUARANTINED", "REVIEW_REQUIRED"],
    "rule": "source_record != canonical property; REJECTED rows retained",
    "idempotency_key": "(source_system, source_listing_id)",
}

LISTING_FRESHNESS_CONTRACT = {
    "version": "0.1",
    "states": [
        "VERIFIED_AVAILABLE",
        "VERIFICATION_DUE",
        "VERIFICATION_OVERDUE",
        "STALE_UNCONFIRMED",
        "OWNER_REPORTED_UNAVAILABLE",
        "RENTED",
        "SOLD",
        "PAUSED",
    ],
    "bump_separate": True,
    "events": ["LISTING_VERIFIED_AVAILABLE", "LISTING_BUMPED"],
}

NOTIFICATION_EVENT_CONTRACT = {
    "version": "0.1",
    "rule": "Internal notification event != delivery channel; OTP is auth not notification",
    "channels": ["WEB_NOTIFICATION", "HUB_NOTIFICATION", "WEB", "APP_PUSH", "EMAIL"],
    "fields": [
        "notification_event_id",
        "event_type",
        "recipient_user_id",
        "related_entity_type",
        "related_entity_id",
        "created_at",
        "read_at",
        "dismissed_at",
        "dedupe_key",
        "priority",
    ],
}

VIEWING_REQUEST_CONTRACT = {
    "version": "0.1",
    "responses": [
        "ACCEPT",
        "DECLINE",
        "PROPOSE_ALTERNATIVE_TIME",
        "PROPERTY_NOT_AVAILABLE",
        "NEED_MORE_INFORMATION",
    ],
    "fields": ["customer_profile_snapshot", "consent_scope", "requested_slots", "recipient"],
}

DEAL_LIFECYCLE_CONTRACT = {"version": "0.1", "states": ["INQUIRY", "VIEWING", "NEGOTIATION", "DEPOSIT", "CONTRACT", "CLOSED"]}

LEASE_LIFECYCLE_CONTRACT = {
    "version": "0.1",
    "states": ["ACTIVE", "RENEWING", "ENDING_SOON", "ENDED", "VACANT_CONFIRMED"],
}

LEASE_OPPORTUNITY_CONTRACT = {
    "version": "0.1",
    "rule": "TIME ALONE MUST NEVER MEAN VACANT; owner confirmation required",
    "evidence_classes": [
        "CONFIRMED_LEASE_END",
        "DERIVED_FROM_EXPLICIT_TERM",
        "ESTIMATED_12M_CANDIDATE",
        "DEAL_DATE_ONLY_CANDIDATE",
        "INSUFFICIENT_EVIDENCE",
    ],
    "strong_evidence": ["CONFIRMED_LEASE_END", "DERIVED_FROM_EXPLICIT_TERM"],
    "statuses": [
        "UPCOMING",
        "FOLLOW_UP_DUE",
        "CONTACTED_WAITING",
        "OWNER_CONFIRMED_VACANT_SOON",
        "TENANT_RENEWED",
        "OWNER_NOT_MARKETING",
        "CONTACT_FAILED",
        "DEFERRED",
        "CLOSED",
    ],
    "follow_up_windows_days": [60, 45, 30, 14],
}

SHARED_MASTER_EXCLUDES_OPERATIONAL = frozenset(
    {
        "owner_contact",
        "customer_profile",
        "listing_freshness",
        "viewing",
        "lease_dates",
        "notifications",
        "marketing_follow_up",
    }
)

OPERATIONAL_CONTRACTS = {
    "PROPERTY_IDENTITY_CONTRACT": PROPERTY_IDENTITY_CONTRACT,
    "LISTING_IDENTITY_CONTRACT": LISTING_IDENTITY_CONTRACT,
    "LISTING_CYCLE_CONTRACT": LISTING_CYCLE_CONTRACT,
    "SOURCE_PROVENANCE_CONTRACT": SOURCE_PROVENANCE_CONTRACT,
    "LISTING_FRESHNESS_CONTRACT": LISTING_FRESHNESS_CONTRACT,
    "NOTIFICATION_EVENT_CONTRACT": NOTIFICATION_EVENT_CONTRACT,
    "VIEWING_REQUEST_CONTRACT": VIEWING_REQUEST_CONTRACT,
    "DEAL_LIFECYCLE_CONTRACT": DEAL_LIFECYCLE_CONTRACT,
    "LEASE_LIFECYCLE_CONTRACT": LEASE_LIFECYCLE_CONTRACT,
    "LEASE_OPPORTUNITY_CONTRACT": LEASE_OPPORTUNITY_CONTRACT,
}
