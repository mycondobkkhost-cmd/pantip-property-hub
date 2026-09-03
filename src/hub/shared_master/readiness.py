"""Field-level promotion readiness — Phase Z3."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
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
from src.hub.shared_master.identity_accounting import (
    build_identity_accounting,
    classify_identity_bucket,
    identity_status_from_bucket,
)

TRUSTED_DB = DEFAULT_TRUSTED
CATALOG_DB = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-catalog.sqlite"
)


@dataclass
class FieldReadiness:
    canonical_project_id: str
    identity_status: str
    name_status: str
    coordinate_status: str
    admin_status: str
    transit_status: str
    marketplace_area_status: str
    group_status: str
    developer_status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "canonical_project_id": self.canonical_project_id,
            "identity_status": self.identity_status,
            "name_status": self.name_status,
            "coordinate_status": self.coordinate_status,
            "admin_status": self.admin_status,
            "transit_status": self.transit_status,
            "marketplace_area_status": self.marketplace_area_status,
            "group_status": self.group_status,
            "developer_status": self.developer_status,
        }


def _coord_readiness(ev) -> str:
    if ev.coordinate_state == STATE_MISSING:
        return "MISSING"
    if ev.coordinate_state == STATE_CONFLICT:
        return "CONFLICT"
    if ev.evidence_tier == TIER_T1:
        return "READY"
    if ev.evidence_tier in (TIER_T2, TIER_T3) and coordinate_evaluable(ev):
        return "READY"
    if coordinate_evaluable(ev):
        return "CANDIDATE"
    return "MISSING"


def _area_readiness(areas: list[dict[str, Any]] | None, confidence: str | None) -> str:
    if not areas:
        return "MISSING"
    highs = [a for a in areas if (a.get("confidence") or "").upper() == "HIGH"]
    meds = [a for a in areas if (a.get("confidence") or "").upper() == "MEDIUM"]
    if highs:
        return "CANDIDATE"
    if meds:
        return "REVIEW_REQUIRED"
    if confidence in ("REALXTATE_HIGH", "REALXTATE_MEDIUM"):
        return "CANDIDATE" if confidence == "REALXTATE_HIGH" else "REVIEW_REQUIRED"
    return "REVIEW_REQUIRED"


def build_field_readiness_matrix(
    *,
    crosswalk_path: Path | None = None,
    trusted_db: Path | None = None,
) -> list[FieldReadiness]:
    crosswalk_path = crosswalk_path or DEFAULT_PHASE_W
    trusted_db = trusted_db or TRUSTED_DB
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))

    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    cur = conn.cursor()

    transit_projects = {
        row[0]
        for row in cur.execute(
            "SELECT DISTINCT project_id FROM marketplace_area_assignment_8z3 ma "
            "JOIN market_area_seed_8z2b s ON ma.area_id = s.area_id "
            "WHERE s.transit_anchors_json IS NOT NULL AND s.transit_anchors_json != '[]'"
        )
    }

    rows: list[FieldReadiness] = []
    identity_states = {
        row[0]: row[1]
        for row in cur.execute("SELECT project_id, identity_state FROM project_master_v01")
    }

    for r in crosswalk:
        pid = r["pantip_project_id"]
        bucket = classify_identity_bucket(r, identity_state=identity_states.get(pid))
        identity = identity_status_from_bucket(bucket)

        name = "READY" if r.get("pantip_canonical_name") else "MISSING"

        payload_row = cur.execute(
            "SELECT payload_json FROM project_master_v01 WHERE project_id=?", (pid,)
        ).fetchone()
        if payload_row:
            ev = parse_coordinate_from_payload(pid, json.loads(payload_row[0] or "{}"))
            coord = _coord_readiness(ev)
        else:
            coord = "MISSING"

        admin = "MISSING"
        transit = "CANDIDATE" if pid in transit_projects else "MISSING"
        if r.get("pantip_transit_verified") and r.get("pantip_transit_unverified"):
            if r["pantip_transit_verified"] == r["pantip_transit_unverified"]:
                transit = "CANDIDATE" if transit == "MISSING" else transit

        area_status = _area_readiness(
            r.get("realxtate_marketplace_areas"),
            r.get("realxtate_area_confidence"),
        )

        group_status = "MISSING"
        if area_status in ("READY", "CANDIDATE", "REVIEW_REQUIRED"):
            group_status = "CANDIDATE"

        developer_status = "MISSING"

        rows.append(
            FieldReadiness(
                canonical_project_id=pid,
                identity_status=identity,
                name_status=name,
                coordinate_status=coord,
                admin_status=admin,
                transit_status=transit,
                marketplace_area_status=area_status,
                group_status=group_status,
                developer_status=developer_status,
            )
        )

    conn.close()
    return rows


def summarize_readiness(matrix: list[FieldReadiness]) -> dict[str, Any]:
    total = len(matrix)
    fields = [
        "identity_status",
        "name_status",
        "coordinate_status",
        "admin_status",
        "transit_status",
        "marketplace_area_status",
        "group_status",
        "developer_status",
    ]

    summary: dict[str, Any] = {"total_projects": total, "fields": {}}
    for field in fields:
        counter = Counter(getattr(r, field) for r in matrix)
        ready = counter.get("READY", 0)
        summary["fields"][field] = {
            "counts": dict(counter),
            "ready_count": ready,
            "ready_rate": round(ready / total * 100, 2) if total else 0,
        }
    return summary
