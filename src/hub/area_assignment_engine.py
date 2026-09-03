"""Evidence-based marketplace area assignment engine — Phase Z0 prototype.

READ-ONLY discovery. Does not mutate production data or canonical assignments.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# RealXtate 8z3 thresholds (reference only; prototype may be stricter).
CORE_METERS = 1000
EXTENDED_METERS = 2200
MAX_AREAS_PER_PROJECT = 3

CLASS_AUTO_SAFE = "AUTO_SAFE"
CLASS_REVIEW = "REVIEW"
CLASS_REJECT_QUARANTINE = "REJECT_QUARANTINE"
CLASS_NOT_EVALUABLE = "NOT_EVALUABLE"

SUPPORT_SUPPORTED = "SUPPORTED"
SUPPORT_QUESTIONABLE = "QUESTIONABLE"
SUPPORT_IMPLAUSIBLE = "IMPLAUSIBLE"
SUPPORT_UNSUPPORTED = "UNSUPPORTED"

ROLE_PRIMARY = "PRIMARY"
ROLE_SECONDARY = "SECONDARY"
ROLE_EDGE = "EDGE"

# Conservative prototype weights (explainable, not ML).
WEIGHTS = {
    "coordinate_core": 40,
    "coordinate_extended": 20,
    "transit_compatible": 15,
    "adjacency": 10,
    "name_branding": 8,
    "catalog_listing_bag": 3,
    "admin": 2,
    "existing_rx_high": 5,
    "existing_rx_medium": 3,
    "existing_rx_low": 1,
    "distance_beyond_extended": -35,
    "weak_only_far": -25,
    "coordinate_missing": -10,
    "legacy_zone_contamination": -5,
}


@dataclass
class AreaSeed:
    area_id: str
    identity_key: str
    name_th: str
    name_en: str
    station_ids: list[str]
    road_ids: list[str]
    adjacent_keys: list[str]


@dataclass
class Station:
    station_id: str
    name_th: str
    line: str
    latitude: float
    longitude: float


@dataclass
class ProjectContext:
    project_id: str
    name: str
    latitude: float | None
    longitude: float | None
    coordinate_state: str
    acceptance_status: str
    listing_locations: list[str]
    listing_transit: list[str]
    pantip_zones: list[str]
    existing_assignments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AreaEvidence:
    area_id: str
    identity_key: str
    name_th: str
    score: int
    classification: str
    proposed_role: str | None
    straight_line_meters: float | None
    evidence: list[str]
    contradictions: list[str]
    existing_rx_role: str | None = None
    existing_rx_confidence: str | None = None


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line (haversine) distance in meters — NOT walking distance."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_area_anchor_meters(
    lat: float,
    lon: float,
    area: AreaSeed,
    stations: dict[str, Station],
) -> tuple[float | None, str | None]:
    best_m: float | None = None
    best_sid: str | None = None
    for sid in area.station_ids:
        st = stations.get(sid)
        if not st:
            continue
        m = haversine_meters(lat, lon, st.latitude, st.longitude)
        if best_m is None or m < best_m:
            best_m, best_sid = m, sid
    return best_m, best_sid


def coordinate_usable(ctx: ProjectContext) -> bool:
    return (
        ctx.coordinate_state == "SOURCE_PROVIDED"
        and ctx.acceptance_status == "ACCEPTED"
        and ctx.latitude is not None
        and ctx.longitude is not None
    )


def _token_hit(text: str, token: str) -> bool:
    return token.lower() in (text or "").lower()


def evaluate_area(
    ctx: ProjectContext,
    area: AreaSeed,
    stations: dict[str, Station],
    *,
    existing: dict[str, dict[str, Any]] | None = None,
) -> AreaEvidence:
    evidence: list[str] = []
    contradictions: list[str] = []
    score = 0

    blob = " | ".join([ctx.name, *ctx.listing_locations, *ctx.listing_transit, *ctx.pantip_zones])
    meters, anchor_station = (
        nearest_area_anchor_meters(ctx.latitude, ctx.longitude, area, stations)
        if coordinate_usable(ctx)
        else (None, None)
    )

    if coordinate_usable(ctx) and meters is not None:
        if meters <= CORE_METERS:
            score += WEIGHTS["coordinate_core"]
            evidence.append(f"straight_line_distance_core:{int(meters)}m")
        elif meters <= EXTENDED_METERS:
            score += WEIGHTS["coordinate_extended"]
            evidence.append(f"straight_line_distance_extended:{int(meters)}m")
        else:
            score += WEIGHTS["distance_beyond_extended"]
            contradictions.append(f"straight_line_distance_far:{int(meters)}m")
    elif not coordinate_usable(ctx):
        score += WEIGHTS["coordinate_missing"]
        contradictions.append("coordinate_unavailable")

    if anchor_station:
        st = stations.get(anchor_station)
        if st:
            evidence.append(f"nearest_anchor_station:{st.name_th}")

    name_tokens = [area.name_th, area.name_en, area.identity_key.replace("_", " ")]
    if any(_token_hit(ctx.name, t) for t in name_tokens if t):
        score += WEIGHTS["name_branding"]
        evidence.append("name_branding")

    listing_hit = any(_token_hit(loc, area.name_th) or _token_hit(loc, area.name_en) for loc in ctx.listing_locations)
    if listing_hit:
        score += WEIGHTS["catalog_listing_bag"]
        evidence.append("catalog_listing_bag")

    admin_hit = any(_token_hit(z, area.name_th) or _token_hit(z, area.name_en) for z in ctx.pantip_zones)
    if admin_hit:
        score += WEIGHTS["admin"]
        evidence.append("admin_or_zone_token")

    if ctx.listing_locations and len(ctx.listing_locations) >= 3 and listing_hit:
        contradictions.append("legacy_multi_zone_listing_bag")

    rx = (existing or {}).get(area.area_id)
    rx_role = rx.get("role") if rx else None
    rx_conf = rx.get("confidence") if rx else None
    if rx_conf == "HIGH":
        score += WEIGHTS["existing_rx_high"]
        evidence.append("existing_realxtate_high")
    elif rx_conf == "MEDIUM":
        score += WEIGHTS["existing_rx_medium"]
        evidence.append("existing_realxtate_medium")
    elif rx_conf == "LOW":
        score += WEIGHTS["existing_rx_low"]
        evidence.append("existing_realxtate_low")

    has_geo = any(e.startswith("straight_line_distance_core") or e.startswith("straight_line_distance_extended") for e in evidence)
    weak_only = evidence and not has_geo and all(
        e.startswith(("catalog_listing_bag", "admin_or_zone_token", "existing_realxtate_low", "name_branding"))
        for e in evidence
        if not e.startswith("existing_realxtate")
    )

    if meters is not None and meters > EXTENDED_METERS and not has_geo:
        score += WEIGHTS["weak_only_far"]
        contradictions.append("far_without_geographic_evidence")

    if weak_only and "legacy_multi_zone_listing_bag" in contradictions:
        score += WEIGHTS["legacy_zone_contamination"]

    # Classification thresholds — precision-first.
    if not coordinate_usable(ctx):
        classification = CLASS_REVIEW
    elif meters is not None and meters > EXTENDED_METERS and not has_geo:
        classification = CLASS_REJECT_QUARANTINE
    elif has_geo and meters is not None and meters <= CORE_METERS and len([e for e in evidence if not e.startswith("existing_")]) >= 2:
        classification = CLASS_AUTO_SAFE
    elif has_geo and meters is not None and meters <= EXTENDED_METERS:
        classification = CLASS_REVIEW
    elif weak_only:
        classification = CLASS_REJECT_QUARANTINE if meters and meters > CORE_METERS else CLASS_REVIEW
    else:
        classification = CLASS_REVIEW

    proposed_role: str | None = None
    if classification == CLASS_AUTO_SAFE:
        proposed_role = ROLE_PRIMARY
    elif classification == CLASS_REVIEW and has_geo:
        proposed_role = ROLE_SECONDARY if meters and meters > CORE_METERS else ROLE_PRIMARY
    elif classification == CLASS_REJECT_QUARANTINE:
        proposed_role = None

    return AreaEvidence(
        area_id=area.area_id,
        identity_key=area.identity_key,
        name_th=area.name_th,
        score=score,
        classification=classification,
        proposed_role=proposed_role,
        straight_line_meters=meters,
        evidence=evidence,
        contradictions=contradictions,
        existing_rx_role=rx_role,
        existing_rx_confidence=rx_conf,
    )


def audit_existing_assignment(hit: AreaEvidence) -> str:
    if hit.existing_rx_confidence is None:
        return SUPPORT_UNSUPPORTED
    has_geo = any(
        e.startswith("straight_line_distance_core") or e.startswith("straight_line_distance_extended")
        for e in hit.evidence
    )
    if hit.straight_line_meters is not None and hit.straight_line_meters > EXTENDED_METERS and not has_geo:
        return SUPPORT_IMPLAUSIBLE
    if "far_without_geographic_evidence" in hit.contradictions:
        return SUPPORT_IMPLAUSIBLE
    if has_geo and hit.straight_line_meters is not None and hit.straight_line_meters <= EXTENDED_METERS:
        return SUPPORT_SUPPORTED
    if hit.existing_rx_confidence in {"HIGH", "MEDIUM"} and has_geo:
        return SUPPORT_SUPPORTED
    if hit.existing_rx_confidence == "LOW" and not has_geo:
        return SUPPORT_QUESTIONABLE
    if hit.contradictions:
        return SUPPORT_IMPLAUSIBLE
    return SUPPORT_QUESTIONABLE


def pick_output_areas(hits: list[AreaEvidence]) -> list[AreaEvidence]:
    """Select up to 3 areas; do not force filler slots."""
    ranked = sorted(
        [h for h in hits if h.classification in {CLASS_AUTO_SAFE, CLASS_REVIEW} and h.proposed_role],
        key=lambda h: (-h.score, h.identity_key),
    )
    out: list[AreaEvidence] = []
    for role in (ROLE_PRIMARY, ROLE_SECONDARY, ROLE_EDGE):
        for hit in ranked:
            if hit.proposed_role == role or (role == ROLE_EDGE and hit.classification == CLASS_REVIEW):
                if hit in out:
                    continue
                if role == ROLE_PRIMARY and any(x.proposed_role == ROLE_PRIMARY for x in out):
                    continue
                if role == ROLE_SECONDARY and any(x.proposed_role == ROLE_SECONDARY for x in out):
                    continue
                adjusted = hit
                if role != hit.proposed_role:
                    adjusted = AreaEvidence(**{**hit.__dict__, "proposed_role": role})
                out.append(adjusted)
                break
        if len(out) >= MAX_AREAS_PER_PROJECT:
            break
    return out[:MAX_AREAS_PER_PROJECT]


def load_area_seeds(db_path: Path) -> list[AreaSeed]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT area_id, identity_key, canonical_name_th, canonical_name_en, "
        "road_anchors_json, transit_anchors_json, adjacent_json "
        "FROM market_area_seed_8z2b WHERE outcome='MARKET_AREA_APPROVED'"
    ).fetchall()
    conn.close()
    seeds: list[AreaSeed] = []
    for area_id, ik, th, en, road_j, transit_j, adj_j in rows:
        seeds.append(
            AreaSeed(
                area_id=area_id,
                identity_key=ik,
                name_th=th,
                name_en=en,
                station_ids=json.loads(transit_j or "[]"),
                road_ids=json.loads(road_j or "[]"),
                adjacent_keys=json.loads(adj_j or "[]"),
            )
        )
    return seeds


def load_stations(db_path: Path) -> dict[str, Station]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    out: dict[str, Station] = {}
    for sid, th, _en, line, lat, lon in cur.execute(
        "SELECT station_id, canonical_name_th, canonical_name_en, line, latitude, longitude "
        "FROM transit_stations WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    ):
        out[sid] = Station(sid, th, line or "", float(lat), float(lon))
    conn.close()
    return out


def load_project_contexts(
    trusted_db: Path,
    catalog_db: Path,
    crosswalk_rows: list[dict[str, Any]] | None = None,
) -> dict[str, ProjectContext]:
    conn = sqlite3.connect(str(trusted_db))
    cur = conn.cursor()
    contexts: dict[str, ProjectContext] = {}
    for project_id, payload in cur.execute("SELECT project_id, payload_json FROM project_master_v01"):
        body = json.loads(payload or "{}")
        coord = body.get("coordinate") or {}
        contexts[project_id] = ProjectContext(
            project_id=project_id,
            name=body.get("catalog_name") or "",
            latitude=coord.get("latitude"),
            longitude=coord.get("longitude"),
            coordinate_state=coord.get("state") or "NONE",
            acceptance_status=coord.get("acceptance_status") or "NONE",
            listing_locations=[],
            listing_transit=[],
            pantip_zones=[],
        )
    for project_id, area_id, role, conf in cur.execute(
        "SELECT project_id, area_id, role, confidence FROM marketplace_area_assignment_8z3"
    ):
        if project_id in contexts:
            contexts[project_id].existing_assignments.append(
                {"area_id": area_id, "role": role, "confidence": conf}
            )
    conn.close()

    if catalog_db.is_file():
        cconn = sqlite3.connect(str(catalog_db))
        ccur = cconn.cursor()
        for pid, _name, loc_j, tr_j in ccur.execute(
            "SELECT id, name, locations_json, transit_json FROM property_projects"
        ):
            if pid not in contexts:
                continue
            locs = json.loads(loc_j or "[]")
            trans = [t.get("label", "") for t in json.loads(tr_j or "[]") if isinstance(t, dict)]
            contexts[pid].listing_locations = locs if isinstance(locs, list) else []
            contexts[pid].listing_transit = trans
        cconn.close()

    if crosswalk_rows:
        for row in crosswalk_rows:
            pid = row.get("pantip_project_id") or row.get("realxtate_project_id")
            if pid and pid in contexts:
                contexts[pid].pantip_zones = list(row.get("pantip_zone_verified") or [])

    return contexts


def evaluate_project(
    ctx: ProjectContext,
    seeds: list[AreaSeed],
    stations: dict[str, Station],
    *,
    candidate_keys: list[str] | None = None,
) -> dict[str, Any]:
    existing = {a["area_id"]: a for a in ctx.existing_assignments}
    pool = seeds
    if candidate_keys:
        keys = set(candidate_keys)
        pool = [s for s in seeds if s.identity_key in keys or s.area_id in keys]

    hits = [
        evaluate_area(ctx, area, stations, existing=existing)
        for area in pool
    ]
    picked = pick_output_areas(hits)

    if not coordinate_usable(ctx):
        project_class = CLASS_NOT_EVALUABLE
    elif any(h.classification == CLASS_AUTO_SAFE for h in picked):
        project_class = CLASS_AUTO_SAFE if len(picked) == 1 and picked[0].classification == CLASS_AUTO_SAFE else CLASS_REVIEW
    elif picked:
        project_class = CLASS_REVIEW
    elif any(h.classification == CLASS_REJECT_QUARANTINE for h in hits if h.existing_rx_confidence):
        project_class = CLASS_REJECT_QUARANTINE
    else:
        project_class = CLASS_REVIEW

    existing_audit = []
    for area in seeds:
        hit = next((h for h in hits if h.area_id == area.area_id), None)
        if hit and hit.existing_rx_confidence:
            existing_audit.append(
                {
                    "area_id": area.area_id,
                    "name_th": area.name_th,
                    "existing_role": hit.existing_rx_role,
                    "existing_confidence": hit.existing_rx_confidence,
                    "audit": audit_existing_assignment(hit),
                    "straight_line_meters": hit.straight_line_meters,
                    "evidence": hit.evidence,
                    "contradictions": hit.contradictions,
                }
            )

    return {
        "project_id": ctx.project_id,
        "project_name": ctx.name,
        "coordinate_usable": coordinate_usable(ctx),
        "latitude": ctx.latitude,
        "longitude": ctx.longitude,
        "classification": project_class,
        "picked_areas": [
            {
                "area_id": h.area_id,
                "identity_key": h.identity_key,
                "name_th": h.name_th,
                "role": h.proposed_role,
                "classification": h.classification,
                "score": h.score,
                "straight_line_meters": h.straight_line_meters,
                "evidence": h.evidence,
                "contradictions": h.contradictions,
            }
            for h in picked
        ],
        "candidate_evaluations": [
            {
                "area_id": h.area_id,
                "identity_key": h.identity_key,
                "name_th": h.name_th,
                "classification": h.classification,
                "score": h.score,
                "straight_line_meters": h.straight_line_meters,
                "evidence": h.evidence,
                "contradictions": h.contradictions,
                "existing_rx_role": h.existing_rx_role,
                "existing_rx_confidence": h.existing_rx_confidence,
            }
            for h in sorted(hits, key=lambda x: -x.score)
        ],
        "existing_assignment_audit": existing_audit,
        "listing_locations": ctx.listing_locations,
        "pantip_zones": ctx.pantip_zones,
    }
