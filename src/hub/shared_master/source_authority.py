"""Source authority and promotion policy — Phase Z3."""

from __future__ import annotations

from typing import Any

from src.hub.coordinate_evidence import (
    STATE_CANDIDATE,
    STATE_CONFLICT,
    STATE_INVALID,
    STATE_MISSING,
    STATE_VERIFIED,
    TIER_T1,
    TIER_T2,
    TIER_T3,
    TIER_T4,
    TIER_T5,
)

SOURCE_TIERS = {
    "T1": {
        "label": "owner-approved canonical decision / verified project pin",
        "may_promote_to_canonical": True,
        "auto_promote": False,
    },
    "T2": {
        "label": "trusted structured reference",
        "may_promote_to_canonical": True,
        "auto_promote": False,
    },
    "T3": {
        "label": "multiple independent corroborating sources",
        "may_promote_to_canonical": True,
        "auto_promote": False,
    },
    "T4": {
        "label": "historical employee/source evidence",
        "may_promote_to_canonical": False,
        "auto_promote": False,
    },
    "T5": {
        "label": "fuzzy / AI / weak inferred evidence",
        "may_promote_to_canonical": False,
        "auto_promote": False,
    },
}

TIER_TO_COORDINATE_STATE = {
    TIER_T1: STATE_VERIFIED,
    TIER_T2: "TRUSTED_REFERENCE",
    TIER_T3: "CORROBORATED",
    TIER_T4: STATE_CANDIDATE,
    TIER_T5: STATE_MISSING,
}

LEGACY_EVIDENCE_POLICY = {
    "classification": "RAW_EVIDENCE",
    "never_auto_canonical": True,
    "preserve_fields": ["raw_value", "source", "lineage", "timestamp"],
    "examples": ["old zone bag", "old transit token", "old project name", "employee sheet value"],
}

REFERENCE_ASSIGNMENT_POLICY = {
    "realxtate_marketplace_area_assignment_8z3": "REFERENCE_ASSIGNMENT",
    "reason": "Z0 proved weak EDGE fill can preserve contaminated area tokens",
    "promotion_requires": "current evidence rules and owner/master approval",
    "not_canonical_truth": True,
}


def coordinate_promotion_policy() -> dict[str, Any]:
    return {
        "tier_mapping": {
            "T1": {"canonical_state": STATE_VERIFIED, "auto_promote_future": False},
            "T2": {"canonical_state": "TRUSTED_REFERENCE", "auto_promote_future": True},
            "T3": {"canonical_state": "CORROBORATED", "auto_promote_future": True},
            "T4": {"canonical_state": STATE_CANDIDATE, "auto_promote_future": False},
            "T5": {"canonical_state": STATE_MISSING, "auto_promote_future": False},
        },
        "fail_closed": True,
        "never_silent_overwrite": True,
        "preserve_history": True,
        "z3_apply": False,
    }


def reference_assignment_policy() -> dict[str, Any]:
    return dict(REFERENCE_ASSIGNMENT_POLICY)


def lineage_dedupe_policy() -> dict[str, Any]:
    return {
        "rule": "copied source appearing in multiple databases counts as ONE lineage",
        "implementation": "lineage_id based on source family + normalized value, not storage location",
    }


def field_promotion_policy() -> dict[str, Any]:
    return {
        "per_field": True,
        "project_level_verified_flag": False,
        "t4_cannot_silently_become_canonical": True,
        "fail_closed": True,
    }
