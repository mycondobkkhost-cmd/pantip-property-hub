"""Canonical coordinate evidence parser — Phase Z1 foundation.

READ-ONLY. Normalizes coordinate records without mutating source payloads.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Bangkok metro bounding box (conservative, for quality flags only).
BKK_LAT_MIN, BKK_LAT_MAX = 13.40, 14.10
BKK_LON_MIN, BKK_LON_MAX = 100.30, 101.00

THAILAND_LAT_MIN, THAILAND_LAT_MAX = 5.0, 21.0
THAILAND_LON_MIN, THAILAND_LON_MAX = 97.0, 106.0

TIER_T1 = "T1_COORD"
TIER_T2 = "T2_COORD"
TIER_T3 = "T3_COORD"
TIER_T4 = "T4_COORD"
TIER_T5 = "T5_COORD"

STATE_VERIFIED = "VERIFIED"
STATE_CANDIDATE = "CANDIDATE"
STATE_MISSING = "MISSING"
STATE_CONFLICT = "CONFLICT"
STATE_INVALID = "INVALID"

USABLE_TIERS = frozenset({TIER_T1, TIER_T2, TIER_T3})
EVALUABLE_TIERS = frozenset({TIER_T1, TIER_T2, TIER_T3, TIER_T4})


@dataclass
class CoordinateEvidence:
    project_id: str
    latitude: float | None
    longitude: float | None
    source: str
    source_record_id: str
    evidence_tier: str
    coordinate_state: str
    acceptance_state: str
    evidence: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source": self.source,
            "source_record_id": self.source_record_id,
            "evidence_tier": self.evidence_tier,
            "coordinate_state": self.coordinate_state,
            "acceptance_state": self.acceptance_state,
            "evidence": self.evidence,
            "conflicts": self.conflicts,
            "quality_flags": self.quality_flags,
        }


def _extract_lat_lng(coord: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = coord.get("latitude")
    lng = coord.get("longitude")
    if lat is None and coord.get("lat") is not None:
        lat = coord.get("lat")
    if lng is None and coord.get("lng") is not None:
        lng = coord.get("lng")
    if lng is None and coord.get("lon") is not None:
        lng = coord.get("lon")
    return lat, lng


def _valid_range(lat: float | None, lng: float | None) -> bool:
    if lat is None or lng is None:
        return False
    if lat == 0 and lng == 0:
        return False
    if not (THAILAND_LAT_MIN <= lat <= THAILAND_LAT_MAX):
        return False
    if not (THAILAND_LON_MIN <= lng <= THAILAND_LON_MAX):
        return False
    return True


def parse_coordinate_from_payload(
    project_id: str,
    payload: dict[str, Any],
    *,
    alternate_records: list[dict[str, Any]] | None = None,
) -> CoordinateEvidence:
    """Parse one project's coordinate evidence from RealXtate project_master payload."""
    coord = payload.get("coordinate") or {}
    lat, lng = _extract_lat_lng(coord)
    state = str(coord.get("state") or "NONE")
    acceptance = str(coord.get("acceptance_status") or "NONE")
    source = str(coord.get("source_family") or "project_master_v01")
    trust = str(coord.get("trust_label") or "")

    evidence: list[str] = []
    conflicts: list[str] = []
    quality: list[str] = []

    if state == "VERIFIED" and _valid_range(lat, lng):
        tier = TIER_T1
        coord_state = STATE_VERIFIED
        evidence.append("owner_or_canonical_verified_pin")
    elif state == "SOURCE_PROVIDED" and acceptance == "ACCEPTED" and _valid_range(lat, lng):
        tier = TIER_T2
        coord_state = STATE_CANDIDATE
        evidence.append("source_provided_accepted_pin")
    elif _valid_range(lat, lng):
        tier = TIER_T4
        coord_state = STATE_CANDIDATE
        evidence.append("coordinate_present_unverified")
    else:
        tier = TIER_T5 if lat is not None or lng is not None else TIER_T5
        coord_state = STATE_INVALID if (lat is not None or lng is not None) else STATE_MISSING
        if coord_state == STATE_INVALID:
            conflicts.append("invalid_or_incomplete_coordinate")

    # Legacy Phase W bug detector: had lat in payload but old parser used coord.lat only.
    if state == "SOURCE_PROVIDED" and acceptance == "ACCEPTED" and _valid_range(lat, lng):
        if coord.get("lat") is None and coord.get("latitude") is not None:
            evidence.append("schema_uses_latitude_longitude_not_lat")

    if lat is not None and lng is not None and _valid_range(lat, lng):
        if not (BKK_LAT_MIN <= lat <= BKK_LAT_MAX and BKK_LON_MIN <= lng <= BKK_LON_MAX):
            quality.append("outside_bangkok_metro_bbox")

    # Alternate source agreement (T3).
    if alternate_records and lat is not None and lng is not None:
        for alt in alternate_records:
            alt_lat, alt_lng = alt.get("latitude"), alt.get("longitude")
            if alt_lat is None or alt_lng is None:
                continue
            dist = haversine_meters(lat, lng, alt_lat, alt_lng)
            if dist <= 50:
                tier = TIER_T3
                evidence.append(f"independent_source_agreement:{alt.get('source','unknown')}")
            elif dist > 500:
                conflicts.append(f"coordinate_source_conflict:{alt.get('source','unknown')}:{int(dist)}m")
                coord_state = STATE_CONFLICT

    if coord_state == STATE_CONFLICT:
        tier = TIER_T5

    return CoordinateEvidence(
        project_id=project_id,
        latitude=lat if _valid_range(lat, lng) else None,
        longitude=lng if _valid_range(lat, lng) else None,
        source=source,
        source_record_id=project_id,
        evidence_tier=tier,
        coordinate_state=coord_state,
        acceptance_state=acceptance,
        evidence=evidence,
        conflicts=conflicts,
        quality_flags=quality,
    )


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in meters — NOT walking distance."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def coordinate_usable_tier(ev: CoordinateEvidence) -> bool:
    return ev.evidence_tier in USABLE_TIERS and ev.coordinate_state in {STATE_VERIFIED, STATE_CANDIDATE}


def coordinate_evaluable(ev: CoordinateEvidence) -> bool:
    """Project has a coordinate pin usable for geographic evaluation (T1–T4)."""
    return (
        ev.evidence_tier in EVALUABLE_TIERS
        and ev.coordinate_state in {STATE_VERIFIED, STATE_CANDIDATE}
        and ev.latitude is not None
        and ev.longitude is not None
    )


def load_coordinate_inventory(
    trusted_db: Path,
    project_ids: list[str] | None = None,
) -> dict[str, CoordinateEvidence]:
    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    cur = conn.cursor()
    rows = cur.execute("SELECT project_id, payload_json FROM project_master_v01").fetchall()
    conn.close()

    wanted = set(project_ids) if project_ids else None
    out: dict[str, CoordinateEvidence] = {}
    for project_id, payload in rows:
        if wanted is not None and project_id not in wanted:
            continue
        try:
            body = json.loads(payload or "{}")
        except json.JSONDecodeError:
            out[project_id] = CoordinateEvidence(
                project_id=project_id,
                latitude=None,
                longitude=None,
                source="project_master_v01",
                source_record_id=project_id,
                evidence_tier=TIER_T5,
                coordinate_state=STATE_INVALID,
                acceptance_state="NONE",
                conflicts=["payload_json_invalid"],
            )
            continue
        out[project_id] = parse_coordinate_from_payload(project_id, body)
    return out


def summarize_inventory(inventory: dict[str, CoordinateEvidence]) -> dict[str, Any]:
    tier_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    for ev in inventory.values():
        tier_counts[ev.evidence_tier] += 1
        state_counts[ev.coordinate_state] += 1

    coord_key_clusters: dict[str, list[str]] = defaultdict(list)
    for ev in inventory.values():
        if ev.latitude is not None and ev.longitude is not None:
            key = f"{ev.latitude:.6f},{ev.longitude:.6f}"
            coord_key_clusters[key].append(ev.project_id)

    duplicate_clusters = [
        {"coordinate": k, "project_count": len(v), "project_ids": v[:10]}
        for k, v in coord_key_clusters.items()
        if len(v) > 1
    ]
    duplicate_clusters.sort(key=lambda x: -x["project_count"])

    usable = sum(1 for ev in inventory.values() if coordinate_usable_tier(ev))
    total = len(inventory)
    return {
        "total_projects": total,
        "tier_counts": dict(tier_counts),
        "state_counts": dict(state_counts),
        "coordinate_usable": usable,
        "coordinate_usable_pct": round(100 * usable / total, 2) if total else 0.0,
        "missing": state_counts.get(STATE_MISSING, 0),
        "conflict": state_counts.get(STATE_CONFLICT, 0),
        "invalid": state_counts.get(STATE_INVALID, 0),
        "duplicate_coordinate_clusters": len(duplicate_clusters),
        "top_duplicate_clusters": duplicate_clusters[:20],
    }


def legacy_phase_w_coordinate_class(coord: dict[str, Any]) -> str:
    """Reproduce the Phase W bug for before/after comparison."""
    state = coord.get("state", "NONE")
    if state == "VERIFIED" and coord.get("lat"):
        return "COORD_VERIFIED_REFERENCE_AVAILABLE"
    if state == "SOURCE_PROVIDED" and coord.get("lat"):
        return "COORD_CANDIDATE_REFERENCE_AVAILABLE"
    if state == "NONE":
        return "COORD_MISSING"
    return "COORD_CONFLICT"
