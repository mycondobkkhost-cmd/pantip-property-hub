"""Coordinate evidence acquisition orchestration — Phase Z2."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.hub.coordinate_agreement import resolve_agreement
from src.hub.coordinate_evidence import (
    STATE_MISSING,
    TIER_T2,
    TIER_T4,
    parse_coordinate_from_payload,
)
from src.hub.coordinate_sources.base import (
    CoordinateCandidate,
    LOCATION_ROLE_PROJECT_SITE,
    URL_PROPERTY_DIRECTORY,
    classify_url,
    hash_coordinate,
    utc_now_iso,
)
from src.hub.coordinate_sources.reference_url import fetch_and_extract
from src.hub.population_accounting import DEFAULT_PHASE_W, DEFAULT_TRUSTED, reconcile_population

OUTCOME_RECOVERED_TRUSTED = "RECOVERED_TRUSTED"
OUTCOME_RECOVERED_CORROBORATED = "RECOVERED_CORROBORATED"
OUTCOME_CANDIDATE_SINGLE_SOURCE = "CANDIDATE_SINGLE_SOURCE"
OUTCOME_COORDINATE_CONFLICT = "COORDINATE_CONFLICT"
OUTCOME_IDENTITY_REVIEW_REQUIRED = "IDENTITY_REVIEW_REQUIRED"
OUTCOME_NO_EVIDENCE_FOUND = "NO_EVIDENCE_FOUND"
OUTCOME_UNSUPPORTED_SPATIAL_TYPE = "UNSUPPORTED_SPATIAL_TYPE"
OUTCOME_RETRIEVAL_FAILED = "RETRIEVAL_FAILED"

IDENTITY_HIGH = "HIGH"
IDENTITY_MEDIUM = "MEDIUM"
IDENTITY_LOW = "LOW"
IDENTITY_AMBIGUOUS = "AMBIGUOUS"

SPATIAL_POINT = "POINT_PROJECT"
SPATIAL_MULTI = "MULTI_BUILDING_PROJECT"
SPATIAL_ESTATE = "ESTATE"
SPATIAL_CORRIDOR = "CORRIDOR_PROPERTY"
SPATIAL_UNKNOWN = "UNKNOWN_SPATIAL_TYPE"

LINEAGE_PANTIP_PROJECTS_JSON = "lineage:pantip_projects_json"
LINEAGE_PROPERTYHUB_ACQUISITION = "lineage:propertyhub_acquisition"
LINEAGE_LOCATION_PROFILE = "lineage:location_profile_8z2d"
LINEAGE_LOCATION_FACT = "lineage:location_fact"
LINEAGE_LIVINGINSIDER = "lineage:livinginsider_directory"
LINEAGE_OSM_NOMINATIM = "lineage:osm_nominatim"

MULTI_PHASE_PATTERNS = (
    r"life asoke",
    r"life asoke rama 9",
    r"life asoke hype",
    r"the base",
    r"aspire",
    r"ideo",
    r"plum condo",
)

ESTATE_PATTERNS = (r"townhouse", r"village", r"estate", r"บ้านเดี่ยว", r"ทาวน์เฮ้าส์")


@dataclass
class QueueEntry:
    project_id: str
    canonical_name: str
    aliases: list[str]
    bucket_key: str
    listing_count: int
    current_admin_tokens: list[str]
    current_marketplace_tokens: list[str]
    transit_tokens: list[str]
    known_reference_urls: list[dict[str, str]]
    identity_confidence: str
    acquisition_strategy: str
    priority_score: int
    priority_band: str
    evidence_state: str
    spatial_type: str
    z1_project_outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "canonical_name": self.canonical_name,
            "aliases": self.aliases,
            "bucket_key": self.bucket_key,
            "listing_count": self.listing_count,
            "current_admin_tokens": self.current_admin_tokens,
            "current_marketplace_tokens": self.current_marketplace_tokens,
            "transit_tokens": self.transit_tokens,
            "known_reference_urls": self.known_reference_urls,
            "identity_confidence": self.identity_confidence,
            "acquisition_strategy": self.acquisition_strategy,
            "priority_score": self.priority_score,
            "priority_band": self.priority_band,
            "evidence_state": self.evidence_state,
            "spatial_type": self.spatial_type,
            "z1_project_outcome": self.z1_project_outcome,
        }


@dataclass
class AcquisitionResult:
    project_id: str
    outcome: str
    candidates: list[CoordinateCandidate] = field(default_factory=list)
    agreement: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "outcome": self.outcome,
            "candidates": [c.to_dict() for c in self.candidates],
            "agreement": self.agreement,
            "notes": self.notes,
        }


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def assess_identity_confidence(name: str, aliases: list[str], listing_count: int) -> str:
    if not name or len(name) < 3:
        return IDENTITY_AMBIGUOUS
    if listing_count >= 5 and len(name) >= 6:
        return IDENTITY_HIGH
    if listing_count >= 1:
        return IDENTITY_MEDIUM
    return IDENTITY_LOW


def classify_spatial_type(name: str) -> str:
    low = (name or "").lower()
    if any(re.search(p, low) for p in ESTATE_PATTERNS):
        return SPATIAL_ESTATE
    if any(re.search(p, low) for p in MULTI_PHASE_PATTERNS):
        return SPATIAL_MULTI
    return SPATIAL_POINT


def is_identity_ambiguous_for_geocoding(entry: QueueEntry) -> bool:
    if entry.identity_confidence == IDENTITY_AMBIGUOUS:
        return True
    name = _normalize_name(entry.canonical_name)
    if not name:
        return True
    # Multi-phase family without disambiguating tokens
    for pat in MULTI_PHASE_PATTERNS:
        if re.search(pat, name) and "rama 9" not in name and "hype" not in name and "48" not in name:
            if entry.listing_count < 3:
                return True
    return False


def compute_priority(entry: QueueEntry, *, z1_outcome: str = "") -> tuple[int, str]:
    score = 0
    if z1_outcome == "OWNER_REVIEW_REQUIRED":
        score += 50
    if entry.listing_count >= 10:
        score += 40
    elif entry.listing_count >= 5:
        score += 25
    elif entry.listing_count >= 2:
        score += 10
    if entry.known_reference_urls:
        score += 20
    if entry.identity_confidence == IDENTITY_HIGH:
        score += 15
    elif entry.identity_confidence == IDENTITY_MEDIUM:
        score += 5
    if entry.spatial_type == SPATIAL_UNKNOWN:
        score -= 20
    if entry.identity_confidence == IDENTITY_AMBIGUOUS:
        score -= 50

    if score >= 70:
        band = "P0"
    elif score >= 40:
        band = "P1"
    elif score >= 15:
        band = "P2"
    else:
        band = "P3"
    return score, band


def load_projects_json_reference(projects_path: Path) -> dict[str, dict[str, Any]]:
    if not projects_path.is_file():
        return {}
    data = json.loads(projects_path.read_text(encoding="utf-8"))
    return {p.get("id"): p for p in data if p.get("id")}


def build_missing_coordinate_queue(
    *,
    crosswalk_path: Path | None = None,
    trusted_db: Path | None = None,
    catalog_db: Path | None = None,
    projects_json_path: Path | None = None,
    z1_outcomes: dict[str, str] | None = None,
) -> list[QueueEntry]:
    crosswalk_path = crosswalk_path or DEFAULT_PHASE_W
    trusted_db = trusted_db or DEFAULT_TRUSTED
    catalog_db = catalog_db or Path(
        "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-catalog.sqlite"
    )
    projects_json_path = projects_json_path or Path(__file__).resolve().parent.parent.parent / "data" / "projects.json"
    z1_outcomes = z1_outcomes or {}

    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    pantip_projects = load_projects_json_reference(projects_json_path)

    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    cur = conn.cursor()
    cconn = sqlite3.connect(f"file:{catalog_db}?mode=ro", uri=True) if catalog_db.is_file() else None
    ccur = cconn.cursor() if cconn else None

    queue: list[QueueEntry] = []
    for row in crosswalk:
        pid = row.get("pantip_project_id")
        if not pid:
            continue
        payload_row = cur.execute("SELECT payload_json FROM project_master_v01 WHERE project_id=?", (pid,)).fetchone()
        if not payload_row:
            ev_state = STATE_MISSING
            body: dict[str, Any] = {}
        else:
            body = json.loads(payload_row[0] or "{}")
            ev = parse_coordinate_from_payload(pid, body)
            ev_state = ev.coordinate_state
        if ev_state != STATE_MISSING:
            continue

        name = body.get("catalog_name") or row.get("project_name") or ""
        aliases = list(body.get("aliases") or [])
        listing_count = int(row.get("live_snapshot_listing_count") or 0)
        bucket_key = ""
        transit_tokens: list[str] = []
        marketplace_tokens: list[str] = []
        admin_tokens = list(row.get("pantip_zone_verified") or [])

        if ccur:
            cat = ccur.execute(
                "SELECT bucket_key, locations_json, transit_json, listing_count FROM property_projects WHERE id=?",
                (pid,),
            ).fetchone()
            if cat:
                bucket_key = cat[0] or ""
                listing_count = max(listing_count, int(cat[3] or 0))
                marketplace_tokens = json.loads(cat[1] or "[]") if cat[1] else []
                transit_tokens = [
                    t.get("label", "") for t in json.loads(cat[2] or "[]") if isinstance(t, dict)
                ]

        urls: list[dict[str, str]] = []
        pantip_ref = pantip_projects.get(pid) or {}
        living = pantip_ref.get("living_project_url")
        if living:
            urls.append(
                {
                    "url": living,
                    "provider": "livinginsider",
                    "category": URL_PROPERTY_DIRECTORY,
                    "source": "pantip_projects_json",
                }
            )

        ext_rows = cur.execute(
            "SELECT source_url, source_name FROM project_external_refs WHERE realxtate_project_id=?",
            (pid,),
        ).fetchall()
        for url, src in ext_rows:
            if url:
                urls.append({"url": url, "provider": src or "external_ref", "category": classify_url(url), "source": "project_external_refs"})

        identity = assess_identity_confidence(name, aliases, listing_count)
        spatial = classify_spatial_type(name)
        z1_out = z1_outcomes.get(pid, "")
        entry = QueueEntry(
            project_id=pid,
            canonical_name=name,
            aliases=aliases,
            bucket_key=bucket_key,
            listing_count=listing_count,
            current_admin_tokens=admin_tokens,
            current_marketplace_tokens=marketplace_tokens if isinstance(marketplace_tokens, list) else [],
            transit_tokens=transit_tokens,
            known_reference_urls=urls,
            identity_confidence=identity,
            acquisition_strategy="LOCAL_FIRST_THEN_PUBLIC" if urls else "LOCAL_ONLY",
            priority_score=0,
            priority_band="P3",
            evidence_state="QUEUED",
            spatial_type=spatial,
            z1_project_outcome=z1_out,
        )
        entry.priority_score, entry.priority_band = compute_priority(entry, z1_outcome=z1_out)
        queue.append(entry)

    if cconn:
        cconn.close()
    conn.close()
    queue.sort(key=lambda e: (-e.priority_score, e.canonical_name))
    return queue


def scan_local_sources(entry: QueueEntry, *, trusted_db: Path) -> list[CoordinateCandidate]:
    candidates: list[CoordinateCandidate] = []
    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    cur = conn.cursor()
    pid = entry.project_id
    now = utc_now_iso()

    for table in ("propertyhub_acquisition_8z2f", "propertyhub_acquisition_8z2g", "propertyhub_acquisition_8z2h"):
        try:
            row = cur.execute(
                f"SELECT latitude, longitude, confidence, url, identity_match FROM {table} "
                "WHERE catalog_project_id=? AND latitude IS NOT NULL AND longitude IS NOT NULL "
                "ORDER BY retrieved_at DESC LIMIT 1",
                (pid,),
            ).fetchone()
            if row:
                lat, lng, conf, url, ident = row
                tier = TIER_T2 if ident == "MATCH" else TIER_T4
                candidates.append(
                    CoordinateCandidate(
                        project_id=pid,
                        latitude=float(lat),
                        longitude=float(lng),
                        provider="propertyhub_directory",
                        source_url=url or "",
                        source_record_id=f"{table}:{pid}",
                        extraction_method="local_propertyhub_acquisition",
                        retrieved_at=now,
                        evidence_lineage_id=LINEAGE_PROPERTYHUB_ACQUISITION,
                        tier=tier,
                        confidence=str(conf or "MEDIUM").upper(),
                        location_role=LOCATION_ROLE_PROJECT_SITE,
                        raw_value_hash=hash_coordinate(float(lat), float(lng)),
                    )
                )
        except sqlite3.OperationalError:
            pass

    prof = cur.execute("SELECT profile_json FROM project_location_profile_8z2d WHERE project_id=?", (pid,)).fetchone()
    if prof:
        profile = json.loads(prof[0] or "{}")
        for c in profile.get("coordinateCandidates") or []:
            lat, lng = c.get("latitude"), c.get("longitude")
            if lat is None or lng is None:
                continue
            fam = c.get("sourceFamily") or ""
            lineage = LINEAGE_OSM_NOMINATIM if "nominatim" in fam.lower() else LINEAGE_LOCATION_PROFILE
            candidates.append(
                CoordinateCandidate(
                    project_id=pid,
                    latitude=float(lat),
                    longitude=float(lng),
                    provider=fam or "location_profile",
                    source_url="",
                    source_record_id=f"profile:{pid}",
                    extraction_method=c.get("method") or "profile_coordinate_candidate",
                    retrieved_at=now,
                    evidence_lineage_id=lineage,
                    tier=TIER_T4,
                    confidence=str(c.get("confidence") or "LOW").upper(),
                    location_role=LOCATION_ROLE_PROJECT_SITE,
                    independence="INDEPENDENCE_UNKNOWN" if "nominatim" in fam.lower() else "INDEPENDENT",
                    raw_value_hash=hash_coordinate(float(lat), float(lng)),
                )
            )

    for suffix in ("8z2e", "8z2f", "8z2g", "8z2h", "8z2j"):
        table = f"location_fact_{suffix}"
        try:
            for fact_id, raw, url, conf in cur.execute(
                f"SELECT fact_id, raw_value, source_url, confidence FROM {table} "
                "WHERE project_id=? AND fact_type='coordinate'",
                (pid,),
            ):
                parts = str(raw).split(",")
                if len(parts) >= 2:
                    lat, lng = float(parts[0]), float(parts[1])
                    candidates.append(
                        CoordinateCandidate(
                            project_id=pid,
                            latitude=lat,
                            longitude=lng,
                            provider="location_fact",
                            source_url=url or "",
                            source_record_id=str(fact_id),
                            extraction_method="local_location_fact",
                            retrieved_at=now,
                            evidence_lineage_id=LINEAGE_LOCATION_FACT,
                            tier=TIER_T4,
                            confidence=str(conf or "MEDIUM").upper(),
                            location_role=LOCATION_ROLE_PROJECT_SITE,
                            raw_value_hash=hash_coordinate(lat, lng),
                        )
                    )
        except sqlite3.OperationalError:
            pass

    conn.close()
    return candidates


def acquire_for_entry(
    entry: QueueEntry,
    *,
    trusted_db: Path,
    fetch_public: bool = False,
) -> AcquisitionResult:
    if is_identity_ambiguous_for_geocoding(entry):
        return AcquisitionResult(entry.project_id, OUTCOME_IDENTITY_REVIEW_REQUIRED, notes=["Identity too ambiguous for automatic acquisition"])

    if entry.spatial_type == SPATIAL_UNKNOWN:
        return AcquisitionResult(entry.project_id, OUTCOME_UNSUPPORTED_SPATIAL_TYPE)

    candidates = scan_local_sources(entry, trusted_db=trusted_db)

    if fetch_public and entry.known_reference_urls:
        for ref in entry.known_reference_urls[:1]:
            url = ref.get("url") or ""
            if not url:
                continue
            provider = ref.get("provider") or "public_web"
            lineage = LINEAGE_LIVINGINSIDER if "livinginsider" in url else f"lineage:public:{provider}"
            fetched, meta = fetch_and_extract(
                project_id=entry.project_id,
                url=url,
                provider=provider,
                lineage_id=lineage,
            )
            if meta.get("error") and not fetched:
                if not candidates:
                    return AcquisitionResult(
                        entry.project_id,
                        OUTCOME_RETRIEVAL_FAILED,
                        candidates=[],
                        notes=[f"retrieval_failed:{meta.get('error')}"],
                    )
                continue
            candidates.extend(fetched)

    if not candidates:
        return AcquisitionResult(entry.project_id, OUTCOME_NO_EVIDENCE_FOUND)

    agreement = resolve_agreement(candidates)
    site_candidates = [c for c in candidates if c.location_role == LOCATION_ROLE_PROJECT_SITE]
    if not site_candidates:
        return AcquisitionResult(entry.project_id, OUTCOME_NO_EVIDENCE_FOUND, candidates=candidates, notes=["No PROJECT_SITE coordinates"])

    if agreement.agreement_class == "CONFLICT":
        return AcquisitionResult(entry.project_id, OUTCOME_COORDINATE_CONFLICT, candidates=candidates, agreement=agreement.to_dict())

    trusted = [c for c in site_candidates if c.tier == TIER_T2]
    if trusted:
        return AcquisitionResult(entry.project_id, OUTCOME_RECOVERED_TRUSTED, candidates=site_candidates, agreement=agreement.to_dict())

    if agreement.promoted_tier == "T3_COORD" and agreement.independent_lineage_count >= 2:
        for c in site_candidates:
            c.tier = "T3_COORD"
        return AcquisitionResult(entry.project_id, OUTCOME_RECOVERED_CORROBORATED, candidates=site_candidates, agreement=agreement.to_dict())

    return AcquisitionResult(entry.project_id, OUTCOME_CANDIDATE_SINGLE_SOURCE, candidates=site_candidates, agreement=agreement.to_dict())


def apply_acquired_to_context(ctx: Any, acquired: AcquisitionResult | None) -> None:
    """Overlay acquired coordinates onto ProjectContext without mutating source DB."""
    if not acquired or not acquired.candidates:
        return
    best = acquired.candidates[0]
    if acquired.outcome == OUTCOME_RECOVERED_TRUSTED:
        ctx.latitude = best.latitude
        ctx.longitude = best.longitude
        ctx.coordinate_tier = best.tier
        ctx.coordinate_state = "CANDIDATE"
    elif acquired.outcome == OUTCOME_RECOVERED_CORROBORATED:
        ctx.latitude = best.latitude
        ctx.longitude = best.longitude
        ctx.coordinate_tier = "T3_COORD"
        ctx.coordinate_state = "CANDIDATE"
    elif acquired.outcome == OUTCOME_CANDIDATE_SINGLE_SOURCE:
        ctx.latitude = best.latitude
        ctx.longitude = best.longitude
        ctx.coordinate_tier = TIER_T4
        ctx.coordinate_state = "CANDIDATE"
    ctx.acquired_provenance = acquired.to_dict()  # type: ignore[attr-defined]
