"""Shared project master contract — Phase Z3."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from src.hub.coordinate_evidence import (
    STATE_CONFLICT,
    STATE_MISSING,
    TIER_T1,
    TIER_T2,
    TIER_T3,
    coordinate_evaluable,
    parse_coordinate_from_payload,
)
from src.hub.population_accounting import DEFAULT_PHASE_W, DEFAULT_TRUSTED

CANONICAL_EXCLUDED_FIELDS = frozenset(
    {
        "listing_price",
        "rent_price",
        "sale_price",
        "listing_availability",
        "owner_name",
        "tenant_name",
        "phone",
        "line",
        "property_description",
        "property_code",
        "owner_facebook",
        "post_url",
        "source_url",
    }
)

PANTIP_ONLY_CLASSES = frozenset(
    {
        "PANTIP_ONLY_VALID_PROJECT",
        "PANTIP_ONLY_IDENTITY_REVIEW",
        "PANTIP_ONLY_NON_PROJECT_ENTITY",
        "POSSIBLE_REALXTATE_MISSING_PROJECT",
    }
)

NON_PROJECT_PATTERNS = (
    re.compile(r"^home\s+office", re.I),
    re.compile(r"^town\s*house\s", re.I),
    re.compile(r"^บ้านเดี่ยว", re.I),
    re.compile(r"^ทาวน์เฮ้าส์", re.I),
    re.compile(r"^home\s+office", re.I),
)


def canonical_project_id_policy(
    *,
    crosswalk_path: Path | None = None,
    trusted_db: Path | None = None,
) -> dict[str, Any]:
    """Verify whether stable shared UUID can be canonical_project_id."""
    crosswalk_path = crosswalk_path or DEFAULT_PHASE_W
    trusted_db = trusted_db or DEFAULT_TRUSTED
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))

    exact = [r for r in crosswalk if r.get("match_class") == "EXACT_ID_MATCH"]
    pantip_only = [r for r in crosswalk if r.get("match_class") == "PANTIP_ONLY"]

    ids = [r["pantip_project_id"] for r in crosswalk if r.get("pantip_project_id")]
    unique_ids = set(ids)

    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    db_ids = {row[0] for row in conn.execute("SELECT project_id FROM project_master_v01")}
    conn.close()

    stable_pairs = 0
    for r in exact:
        if r.get("pantip_project_id") == r.get("realxtate_project_id"):
            stable_pairs += 1

    return {
        "recommended_canonical_project_id": "reuse_stable_shared_uuid",
        "new_third_namespace_required": False,
        "live_total": len(crosswalk),
        "exact_id_match_count": len(exact),
        "stable_id_pair_count": stable_pairs,
        "pantip_only_count": len(pantip_only),
        "unique_canonical_ids": len(unique_ids),
        "collision_count": len(ids) - len(unique_ids),
        "deterministic": True,
        "historically_stable": stable_pairs == len(exact),
        "live_only_supported": True,
        "trusted_db_project_count": len(db_ids),
        "policy": "Do NOT renumber IDs. canonical_project_id = pantip_project_id = realxtate_project_id when EXACT_ID_MATCH.",
    }


def classify_pantip_only_project(row: dict[str, Any]) -> str:
    name = (row.get("pantip_canonical_name") or "").strip()
    listings = int(row.get("live_listing_count") or 0)
    lower = name.lower()

    for pat in NON_PROJECT_PATTERNS:
        if pat.search(name) or pat.search(lower):
            return "PANTIP_ONLY_NON_PROJECT_ENTITY"

    if listings <= 1 and any(k in lower for k in ("home office", "town house", "townhouse", "บ้าน", "ทาวน์")):
        return "PANTIP_ONLY_NON_PROJECT_ENTITY"

    if listings >= 2:
        return "POSSIBLE_REALXTATE_MISSING_PROJECT"

    if any(k in lower for k in ("diplomat", "atmoz", "plant estique", "townhouse")):
        return "PANTIP_ONLY_VALID_PROJECT"

    return "PANTIP_ONLY_IDENTITY_REVIEW"


def build_cross_product_contract(
    *,
    crosswalk_path: Path | None = None,
    trusted_db: Path | None = None,
) -> list[dict[str, Any]]:
    crosswalk_path = crosswalk_path or DEFAULT_PHASE_W
    trusted_db = trusted_db or DEFAULT_TRUSTED
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))

    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    cur = conn.cursor()

    rows: list[dict[str, Any]] = []
    for r in crosswalk:
        pid = r.get("pantip_project_id")
        match_class = r.get("match_class", "UNKNOWN")
        rx_id = r.get("realxtate_project_id")

        if match_class == "EXACT_ID_MATCH" and pid == rx_id:
            canonical_id = pid
            identity_class = "CANONICAL_IDENTITY_READY"
            eligibility = "CANONICAL_IDENTITY_READY"
        elif match_class == "PANTIP_ONLY":
            canonical_id = pid
            pantip_only_class = classify_pantip_only_project(r)
            identity_class = pantip_only_class
            eligibility = (
                "PRODUCT_ONLY_VALID"
                if pantip_only_class in ("PANTIP_ONLY_VALID_PROJECT", "POSSIBLE_REALXTATE_MISSING_PROJECT")
                else "NON_PROJECT_ENTITY_REVIEW"
                if pantip_only_class == "PANTIP_ONLY_NON_PROJECT_ENTITY"
                else "IDENTITY_REVIEW_REQUIRED"
            )
        else:
            canonical_id = pid
            identity_class = "IDENTITY_REVIEW_REQUIRED"
            eligibility = "IDENTITY_REVIEW_REQUIRED"

        payload_row = cur.execute(
            "SELECT identity_state FROM project_master_v01 WHERE project_id=?", (pid,)
        ).fetchone()
        identity_state = payload_row[0] if payload_row else None
        if identity_state and identity_state not in ("CATALOG_IDENTITY",):
            if eligibility == "CANONICAL_IDENTITY_READY":
                eligibility = "IDENTITY_REVIEW_REQUIRED"

        rows.append(
            {
                "canonical_project_id": canonical_id,
                "pantip_project_id": pid,
                "realxtate_project_id": rx_id,
                "match_class": match_class,
                "identity_match_class": match_class,
                "pantip_only_class": classify_pantip_only_project(r) if match_class == "PANTIP_ONLY" else None,
                "canonical_eligibility": eligibility,
                "identity_state_realxtate": identity_state,
                "pantip_canonical_name": r.get("pantip_canonical_name"),
                "live_listing_count": r.get("live_listing_count"),
            }
        )

    conn.close()
    return rows


def build_canonical_project_record(
    project_id: str,
    *,
    crosswalk_row: dict[str, Any],
    payload: dict[str, Any],
    area_assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build one sanitized canonical project contract record (no listing fields)."""
    coord_ev = parse_coordinate_from_payload(project_id, payload)
    coord_state = coord_ev.coordinate_state
    if coordinate_evaluable(coord_ev) and coord_ev.evidence_tier in (TIER_T1, TIER_T2, TIER_T3):
        shared_coord_state = {
            TIER_T1: "VERIFIED",
            TIER_T2: "TRUSTED_REFERENCE",
            TIER_T3: "CORROBORATED",
        }.get(coord_ev.evidence_tier, "CANDIDATE")
    elif coord_state == STATE_CONFLICT:
        shared_coord_state = "CONFLICT"
    elif coord_state == STATE_MISSING:
        shared_coord_state = "MISSING"
    else:
        shared_coord_state = "CANDIDATE"

    canonical_coord = None
    if coord_ev.latitude is not None and coord_ev.longitude is not None:
        canonical_coord = {"latitude": coord_ev.latitude, "longitude": coord_ev.longitude}

    return {
        "canonical_project_id": project_id,
        "existing_product_ids": {
            "pantip_project_id": project_id,
            "realxtate_project_id": crosswalk_row.get("realxtate_project_id"),
        },
        "canonical_name_th": payload.get("catalog_name"),
        "canonical_name_en": payload.get("catalog_name"),
        "aliases": payload.get("aliases") or [],
        "project_type": payload.get("project_type"),
        "developer_relations": [],
        "coordinate_state": shared_coord_state,
        "canonical_coordinate": canonical_coord,
        "coordinate_evidence": [coord_ev.to_dict()],
        "admin_relations": [],
        "marketplace_area_relations": [
            {
                "area_id": a.get("area_id"),
                "role": a.get("role"),
                "confidence": a.get("confidence"),
                "assignment_class": "REFERENCE_ASSIGNMENT",
            }
            for a in area_assignments
        ],
        "marketplace_group_relations": [],
        "corridor_relations": [],
        "transit_relations": [],
        "source_records": payload.get("source_records") or [],
        "confidence": payload.get("identity_confidence"),
        "review_status": payload.get("identity_resolution_status"),
    }
