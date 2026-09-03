"""Market area candidate evidence builder — Phase Z2."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.hub.coordinate_evidence import STATE_MISSING, coordinate_evaluable, parse_coordinate_from_payload
from src.hub.location_evidence import MARKETPLACE_TOKENS, classify_location_token

DEFAULT_PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
DEFAULT_TRUSTED = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-trusted-master.sqlite"
)
SPATIAL_SEED = Path(__file__).resolve().parent.parent.parent / "data_fixtures" / "area_engine" / "market_area_spatial_seed_v0.2.json"

AREA_STATE_DISCOVERED = "DISCOVERED"
AREA_STATE_EVIDENCE_BUILDING = "EVIDENCE_BUILDING"
AREA_STATE_READY_FOR_OWNER_REVIEW = "READY_FOR_OWNER_REVIEW"

CANDIDATE_KEYS = ("suan_luang", "phatthanakan", "rama9")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_seed_by_key() -> dict[str, dict[str, Any]]:
    if not SPATIAL_SEED.is_file():
        return {}
    payload = json.loads(SPATIAL_SEED.read_text(encoding="utf-8"))
    return {a["identity_key"]: a for a in payload.get("areas", [])}


def collect_project_coordinates(
    *,
    crosswalk_path: Path | None = None,
    trusted_db: Path | None = None,
) -> dict[str, tuple[float, float]]:
    crosswalk_path = crosswalk_path or DEFAULT_PHASE_W
    trusted_db = trusted_db or DEFAULT_TRUSTED
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    cur = conn.cursor()
    coords: dict[str, tuple[float, float]] = {}
    for row in crosswalk:
        pid = row.get("pantip_project_id")
        if not pid:
            continue
        r = cur.execute("SELECT payload_json FROM project_master_v01 WHERE project_id=?", (pid,)).fetchone()
        if not r:
            continue
        ev = parse_coordinate_from_payload(pid, json.loads(r[0] or "{}"))
        if coordinate_evaluable(ev) and ev.latitude is not None and ev.longitude is not None:
            coords[pid] = (ev.latitude, ev.longitude)
    conn.close()
    return coords


def build_area_candidate_packet(
    identity_key: str,
    *,
    crosswalk_path: Path | None = None,
    trusted_db: Path | None = None,
    catalog_db: Path | None = None,
) -> dict[str, Any]:
    crosswalk_path = crosswalk_path or DEFAULT_PHASE_W
    trusted_db = trusted_db or DEFAULT_TRUSTED
    catalog_db = catalog_db or Path(
        "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-catalog.sqlite"
    )
    seed = load_seed_by_key().get(identity_key, {})
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    cur = conn.cursor()
    cconn = sqlite3.connect(f"file:{catalog_db}?mode=ro", uri=True) if catalog_db.is_file() else None
    ccur = cconn.cursor() if cconn else None

    supporting: list[dict[str, Any]] = []
    token_counter: Counter[str] = Counter()
    coord_points: list[tuple[float, float]] = []

    for row in crosswalk:
        pid = row.get("pantip_project_id")
        zones = list(row.get("pantip_zone_verified") or [])
        locs: list[str] = []
        if ccur and pid:
            cat = ccur.execute("SELECT locations_json FROM property_projects WHERE id=?", (pid,)).fetchone()
            if cat and cat[0]:
                locs = json.loads(cat[0])
        for tok in zones + locs:
            cls = classify_location_token(tok)
            if cls.marketplace_identity_key == identity_key:
                token_counter[tok] += 1
                supporting.append({"project_id": pid, "token": tok, "source": "legacy_bag"})
        r = cur.execute("SELECT payload_json FROM project_master_v01 WHERE project_id=?", (pid,)).fetchone()
        if r:
            ev = parse_coordinate_from_payload(pid, json.loads(r[0] or "{}"))
            if coordinate_evaluable(ev) and ev.latitude is not None:
                name = json.loads(r[0]).get("catalog_name", "")
                if identity_key.replace("_", " ") in name.lower() or any(
                    k for k, v in MARKETPLACE_TOKENS.items() if v == identity_key and k in name.lower()
                ):
                    coord_points.append((ev.latitude, ev.longitude))
                    supporting.append({"project_id": pid, "name": name, "source": "name_branding"})

    # cluster centroid if enough points
    cluster = None
    if coord_points:
        lat = sum(p[0] for p in coord_points) / len(coord_points)
        lng = sum(p[1] for p in coord_points) / len(coord_points)
        cluster = {"latitude": lat, "longitude": lng, "project_count": len(coord_points)}

    semantic = seed.get("semantic_kind") or "MARKETPLACE_AREA"
    if identity_key == "rama9":
        semantic = "UMBRELLA_GROUP"
    if identity_key == "phatthanakan":
        semantic = "CORRIDOR"

    recommended = "INSUFFICIENT_EVIDENCE"
    review_status = seed.get("review_status") or "REVIEW_REQUIRED"
    area_state = AREA_STATE_EVIDENCE_BUILDING
    if identity_key == "suan_luang":
        if seed.get("anchors") and len(supporting) >= 5:
            area_state = AREA_STATE_READY_FOR_OWNER_REVIEW
            recommended = "REVIEW_REQUIRED"
        else:
            recommended = "INSUFFICIENT_EVIDENCE"
    elif identity_key == "phatthanakan":
        if len(supporting) >= 20:
            area_state = AREA_STATE_READY_FOR_OWNER_REVIEW
            recommended = "REVIEW_REQUIRED"
        else:
            recommended = "INSUFFICIENT_EVIDENCE"
    elif identity_key == "rama9":
        recommended = "REVIEW_REQUIRED — model as UMBRELLA_GROUP not single point-radius"
        if len(supporting) >= 50:
            area_state = AREA_STATE_READY_FOR_OWNER_REVIEW

    packet = {
        "identity_key": identity_key,
        "canonical_name_th": seed.get("canonical_name_th") or identity_key,
        "canonical_name_en": seed.get("canonical_name_en") or identity_key,
        "semantic_kind": semantic,
        "status": seed.get("status") or "CANDIDATE",
        "area_state": area_state,
        "supporting_project_count": len({s.get("project_id") for s in supporting if s.get("project_id")}),
        "token_frequency": dict(token_counter.most_common(10)),
        "representative_cluster": cluster,
        "transit_anchors": seed.get("transit_anchor_ids") or [],
        "adjacent_areas": seed.get("adjacent_identity_keys") or [],
        "evidence_sources": ["legacy_bag_tokens", "coordinate_name_match", "market_area_spatial_seed_v0.2"],
        "contradictions": [],
        "confidence": seed.get("confidence") or "LOW",
        "recommended_status": recommended,
        "review_status": review_status,
        "notes_th": seed.get("notes_th") or "",
        "admin_vs_marketplace": (
            "เขตสวนหลวง (ADMIN) is distinct from marketplace สวนหลวง"
            if identity_key == "suan_luang"
            else None
        ),
    }

    if cconn:
        cconn.close()
    conn.close()
    return packet


def build_all_candidate_packets() -> dict[str, dict[str, Any]]:
    return {key: build_area_candidate_packet(key) for key in CANDIDATE_KEYS}


def discover_other_candidates(limit: int = 20) -> list[dict[str, Any]]:
    seed_keys = {a["identity_key"] for a in json.loads(SPATIAL_SEED.read_text()).get("areas", []) if SPATIAL_SEED.is_file()}
    counts: Counter[str] = Counter()
    crosswalk = json.loads(DEFAULT_PHASE_W.read_text(encoding="utf-8"))
    for row in crosswalk:
        for tok in row.get("pantip_zone_verified") or []:
            cls = classify_location_token(tok)
            if cls.marketplace_identity_key and cls.marketplace_identity_key not in seed_keys:
                counts[cls.marketplace_identity_key] += 1
    out = []
    for key, cnt in counts.most_common(limit):
        out.append(
            {
                "identity_key": key,
                "supporting_project_count": cnt,
                "semantic_kind": "MARKETPLACE_AREA",
                "recommended_status": "INSUFFICIENT_EVIDENCE",
            }
        )
    return out
