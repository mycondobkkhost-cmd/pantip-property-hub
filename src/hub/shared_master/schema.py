"""Shared Canonical Master entity schema — Phase Z3."""

from __future__ import annotations

from typing import Any

SHARED_MASTER_VERSION = "v0.1"
SCHEMA_VERSION = "shared-master-schema-0.1"

ENTITY_TYPES = frozenset(
    {
        "CANONICAL_PROJECT",
        "MARKETPLACE_AREA",
        "MARKETPLACE_GROUP",
        "CORRIDOR",
        "TRANSIT_STATION",
        "TRANSIT_HUB",
        "ADMIN_PROVINCE",
        "ADMIN_DISTRICT",
        "ADMIN_SUBDISTRICT",
        "DEVELOPER",
        "COORDINATE_EVIDENCE",
        "IDENTITY_ALIAS",
        "SOURCE_EVIDENCE",
    }
)

FIELD_CLASSIFICATIONS = frozenset(
    {
        "CANONICAL_CANDIDATE",
        "PRODUCT_SPECIFIC",
        "RAW_EVIDENCE",
        "DERIVED",
        "LEGACY",
        "PII",
    }
)

READINESS_STATUSES = frozenset(
    {
        "READY",
        "CANDIDATE",
        "REVIEW_REQUIRED",
        "CONFLICT",
        "MISSING",
        "NOT_APPLICABLE",
    }
)

IDENTITY_ELIGIBILITY = frozenset(
    {
        "CANONICAL_IDENTITY_READY",
        "IDENTITY_REVIEW_REQUIRED",
        "PRODUCT_ONLY_VALID",
        "NON_PROJECT_ENTITY_REVIEW",
    }
)

COORDINATE_STATES = frozenset(
    {
        "VERIFIED",
        "CORROBORATED",
        "TRUSTED_REFERENCE",
        "CANDIDATE",
        "CONFLICT",
        "MISSING",
        "INVALID",
    }
)

AREA_RELATION_ROLES = frozenset({"PRIMARY", "SECONDARY", "EDGE"})
GROUP_MEMBER_RELATIONS = frozenset({"MEMBER", "BRIDGE", "OVERLAP"})

ASSIGNMENT_CLASSES = frozenset(
    {
        "CANONICAL_ASSIGNMENT",
        "REFERENCE_ASSIGNMENT",
    }
)


def versioned_artifact_header(
    *,
    artifact_kind: str,
    source_snapshot_ids: list[str],
    content_hash: str,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "shared_master_version": SHARED_MASTER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": artifact_kind,
        "generated_at": generated_at,
        "source_snapshot_ids": source_snapshot_ids,
        "content_hash": content_hash,
    }
