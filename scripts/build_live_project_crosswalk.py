#!/usr/bin/env python3
"""Build offline LIVE Pantip ↔ RealXtate project crosswalk.

READ-ONLY analysis. Does NOT connect to Fly, Google Sheets, LINE, Facebook, or OpenAI.
Does NOT modify input files. Production snapshot must be copied separately by operator.

Usage:
  python3 scripts/build_live_project_crosswalk.py \\
    --pantip-projects /tmp/pantip-phase-w-live/projects.json \\
    --pantip-properties /tmp/pantip-phase-w-live/properties.json \\
    --realxtate-catalog /path/to/realxtate-catalog.sqlite \\
    --realxtate-trusted /path/to/realxtate-trusted-master.sqlite \\
    --output-dir /tmp/pantip-phase-w-crosswalk
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path

AREA_MAP = {
    "ทองหล่อ": "thonglor",
    "thonglor": "thonglor",
    "เอกมัย": "ekkamai",
    "ekkamai": "ekkamai",
    "อโศก": "asoke",
    "asoke": "asoke",
    "พระราม 9": "rama9",
    "rama9": "rama9",
    "พระราม9": "rama9",
    "อ่อนนุช": "onnut",
    "onnut": "onnut",
    "พร้อมพงษ์": "phromphong",
    "phrom phong": "phromphong",
    "เจริญนคร": "charoen_nakhon",
    "สุขุมวิท": "sukhumvit",
    "sukhumvit": "sukhumvit",
    "ห้วยขวาง": "huaykhwang",
    "huay khwang": "huaykhwang",
    "รัชดา": "ratchada",
    "ลาดพร้าว": "ladprao",
    "บางนา": "bangna",
    "วัฒนา": "wattana",
    "สาทร": "sathorn",
    "sathorn": "sathorn",
    "เพชรบุรี": "phetchaburi",
}


def soft_norm(name: str) -> str:
    n = (name or "").lower().strip()
    if n.count("(") > n.count(")"):
        n += ")" * (n.count("(") - n.count(")"))
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.split(r"\s*[:：]\s*", n, maxsplit=1)[0]
    n = re.sub(r"\biii\b", "3", n)
    n = re.sub(r"\bii\b", "2", n)
    n = re.sub(r"\bi\b", "1", n)
    n = re.sub(r"ll\b", "2", n)
    n = re.sub(r"[()（）]", " ", n)
    n = re.sub(r"[^a-z0-9ก-๙]", "", n)
    n = re.sub(r"(?<![a-z])kwang|(?<!h)kwang", "khwang", n)
    n = n.replace("petchaburi", "phetchaburi").replace("petchburi", "phetchaburi")
    if n.endswith("thonglo"):
        n += "r"
    return n


def norm_area_token(label: str) -> str:
    s = (label or "").strip().lower()
    if s in AREA_MAP:
        return AREA_MAP[s]
    sn = soft_norm(s)
    for key, val in AREA_MAP.items():
        if soft_norm(key) == sn:
            return val
    return sn or "unknown"


ADMIN_DISTRICT_TOKENS = {
    "wattana",
    "วัฒนา",
    "คลองเตย",
    "khlongtoei",
    "ห้วยขวาง",
    "huaykhwang",
}


def classify_semantic_kind(label: str) -> str:
    low = (label or "").lower()
    if re.search(r"\b(bts|mrt|arl|srt|สถานี)\b", low):
        return "TRANSIT_STATION"
    if re.search(r"\b(ถนน|soi|ซอย)\b", low) or re.search(r"สุขุมวิท\s*\d+", low):
        return "ROAD_CORRIDOR"
    if re.search(r"\b(เขต|แขวง)\b", low):
        return "ADMIN_AREA"
    token = norm_area_token(label)
    if token in ADMIN_DISTRICT_TOKENS or label.strip() in ADMIN_DISTRICT_TOKENS:
        return "ADMIN_AREA"
    if token not in ("unknown", ""):
        return "MARKETPLACE_AREA"
    return "UNKNOWN"


def load_json(path: Path) -> list | dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_no_output_overlap(inputs: list[Path], output_dir: Path) -> None:
    out = output_dir.resolve()
    for inp in inputs:
        p = inp.resolve()
        if p == out or out in p.parents or p in out.parents:
            raise ValueError(f"Output directory must not overlap input path: {p}")


def load_realxtate_projects(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, aliases_json, bucket_key, listing_count FROM property_projects"
    )
    rows = []
    for rid, name, aliases_json, bucket_key, listing_count in cur.fetchall():
        try:
            aliases = json.loads(aliases_json or "[]")
        except json.JSONDecodeError:
            aliases = []
        rows.append(
            {
                "id": rid,
                "name": name,
                "aliases": aliases,
                "bucket_key": bucket_key,
                "listing_count": listing_count,
            }
        )
    conn.close()
    return rows


def load_area_assignments(db_path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        "SELECT project_id, area_id, role, confidence "
        "FROM marketplace_area_assignment_8z3"
    )
    for project_id, area_id, role, confidence in cur.fetchall():
        out[project_id].append(
            {"area_id": area_id, "role": role, "confidence": confidence}
        )
    conn.close()
    return out


def load_coordinate_states(db_path: Path) -> dict[str, str]:
    states: dict[str, str] = {}
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT project_id, payload_json FROM project_master_v01")
    for project_id, payload in cur.fetchall():
        try:
            body = json.loads(payload or "{}")
        except json.JSONDecodeError:
            states[project_id] = "COORD_MISSING"
            continue
        coord = body.get("coordinate") or {}
        state = coord.get("state", "NONE")
        if state == "VERIFIED" and coord.get("lat"):
            states[project_id] = "COORD_VERIFIED_REFERENCE_AVAILABLE"
        elif state == "SOURCE_PROVIDED" and coord.get("lat"):
            states[project_id] = "COORD_CANDIDATE_REFERENCE_AVAILABLE"
        elif state == "NONE":
            states[project_id] = "COORD_MISSING"
        else:
            states[project_id] = "COORD_CONFLICT"
    conn.close()
    return states


def classify_match(project: dict, rx_by_id: dict, rx_by_bucket: dict, rx_by_norm: dict) -> tuple[str, str | None, list[str]]:
    pid = project["id"]
    bucket = project.get("bucket_key", "")
    evidence: list[str] = []
    rx = rx_by_id.get(pid) or rx_by_bucket.get(bucket)
    if rx:
        evidence.append("stable_project_id")
        return "EXACT_ID_MATCH", rx["id"], evidence

    sn = soft_norm(project.get("canonical_name", ""))
    hits = rx_by_norm.get(sn, [])
    if len(hits) == 1 and hits[0].get("bucket_key") == bucket:
        evidence.append("normalized_name_unique")
        return "EXACT_STRONG_MATCH", hits[0]["id"], evidence
    if len(hits) == 1:
        evidence.append("name_match_bucket_mismatch")
        return "CONFLICT", hits[0]["id"], evidence
    if len(hits) > 1:
        evidence.append("multiple_name_matches")
        return "CONFLICT", None, evidence

    pantip_norms = {soft_norm(a) for a in (project.get("aliases") or []) if a}
    pantip_norms.add(sn)
    alias_hits = []
    for candidate in hits:
        pass
    for rx_project in rx_by_id.values():
        rx_norms = {soft_norm(rx_project.get("name", ""))}
        for alias in rx_project.get("aliases") or []:
            rx_norms.add(soft_norm(alias))
        overlap = pantip_norms & rx_norms
        if overlap:
            alias_hits.append(rx_project)
    if len(alias_hits) == 1:
        evidence.append("alias_overlap")
        return "HIGH_CONFIDENCE_CANDIDATE", alias_hits[0]["id"], evidence
    if len(alias_hits) > 1:
        return "MEDIUM_CONFIDENCE_CANDIDATE", None, evidence

    weak = []
    if len(sn) >= 6:
        for rx_project in rx_by_id.values():
            rsn = soft_norm(rx_project.get("name", ""))
            if rsn and (sn in rsn or rsn in sn) and abs(len(sn) - len(rsn)) <= 3:
                weak.append(rx_project)
    if len(weak) == 1:
        evidence.append("weak_prefix_similarity")
        return "LOW_CONFIDENCE_CANDIDATE", weak[0]["id"], evidence
    if len(weak) > 1:
        return "LOW_CONFIDENCE_CANDIDATE", None, evidence
    return "PANTIP_ONLY", None, evidence


def zone_agreement(pantip_zones: list[str], hi_med_areas: list[dict]) -> str:
    if hi_med_areas and not pantip_zones:
        return "PANTIP_MISSING_REALXTATE_HAS_VALUE"
    if pantip_zones and not hi_med_areas:
        return "PANTIP_HAS_VALUE_REALXTATE_MISSING"
    if not pantip_zones and not hi_med_areas:
        return "INSUFFICIENT_EVIDENCE"

    pantip_tokens = {norm_area_token(z) for z in pantip_zones}
    rx_tokens = set()
    for area in hi_med_areas:
        aid = area.get("area_id", "")
        rx_tokens.add(aid.replace("_", ""))
        rx_tokens.add(norm_area_token(aid.replace("_", " ")))
    if pantip_tokens & rx_tokens:
        return "AGREE"
    if any(classify_semantic_kind(z) == "ADMIN_AREA" for z in pantip_zones):
        return "SEMANTICALLY_DIFFERENT_BUT_NOT_CONFLICT"
    if pantip_tokens & {"sukhumvit", "sathorn", "phetchaburi"} and rx_tokens:
        return "PARTIAL_AGREE"
    return "DIRECT_CONFLICT"


def transit_agreement(transit_verified: list[str], legacy_promotion: bool) -> str:
    if not transit_verified:
        return "PANTIP_MISSING"
    if legacy_promotion:
        return "PANTIP_UNVERIFIED_ONLY"
    if all(re.search(r"\b(BTS|MRT|ARL|SRT)\b", label) for label in transit_verified):
        return "EXACT_STATION_AGREE"
    return "INVALID_OR_UNKNOWN_STATION"


def correction_class(match_class: str, zone_class: str, rx_conf: str, listing_count: int) -> str:
    if match_class == "CONFLICT":
        return "MANUAL_REQUIRED"
    if zone_class == "DIRECT_CONFLICT" and rx_conf in ("REALXTATE_HIGH", "REALXTATE_MEDIUM") and listing_count >= 3:
        return "REVIEW_RECOMMENDED"
    if match_class in ("LOW_CONFIDENCE_CANDIDATE", "MEDIUM_CONFIDENCE_CANDIDATE"):
        return "MANUAL_REQUIRED"
    return "DO_NOT_TOUCH"


def priority_score(row: dict) -> int:
    score = 0
    if row["zone_agreement_class"] == "DIRECT_CONFLICT":
        score += 100
    if row["realxtate_area_confidence"] == "REALXTATE_HIGH":
        score += 50
    elif row["realxtate_area_confidence"] == "REALXTATE_MEDIUM":
        score += 30
    score += min(row["live_listing_count"], 50)
    if row["legacy_promotion_suspected"]:
        score += 20
    if row["match_class"] == "CONFLICT":
        score += 40
    return score


def priority_band(score: int) -> str:
    if score >= 120:
        return "P0"
    if score >= 80:
        return "P1"
    if score >= 50:
        return "P2"
    return "P3"


def build_crosswalk(
    live_projects: list[dict],
    live_properties: list[dict],
    rx_projects: list[dict],
    area_by_project: dict[str, list[dict]],
    coord_states: dict[str, str],
) -> tuple[list[dict], dict]:
    rx_by_id = {r["id"]: r for r in rx_projects}
    rx_by_bucket = {r["bucket_key"]: r for r in rx_projects if r.get("bucket_key")}
    rx_by_norm: dict[str, list[dict]] = defaultdict(list)
    for rx in rx_projects:
        for name in [rx.get("name", "")] + (rx.get("aliases") or []):
            key = soft_norm(name)
            if key:
                rx_by_norm[key].append(rx)

    listing_counts = Counter(pr.get("project_id") for pr in live_properties if pr.get("project_id"))

    rows: list[dict] = []
    match_classes = Counter()
    for project in live_projects:
        pid = project["id"]
        match_class, rx_id, evidence = classify_match(project, rx_by_id, rx_by_bucket, rx_by_norm)
        match_classes[match_class] += 1

        areas = area_by_project.get(pid, [])
        hi_med = [a for a in areas if a.get("confidence") in ("HIGH", "MEDIUM")]
        if any(a.get("confidence") == "HIGH" for a in areas):
            rx_conf = "REALXTATE_HIGH"
        elif any(a.get("confidence") == "MEDIUM" for a in areas):
            rx_conf = "REALXTATE_MEDIUM"
        elif areas:
            rx_conf = "REALXTATE_LOW"
        else:
            rx_conf = "NO_REALXTATE_AREA"

        zv = project.get("zone_verified") or []
        zu = project.get("zone_unverified") or []
        tv = project.get("transit_verified") or []
        tu = project.get("transit_unverified") or []
        legacy = (bool(zv) and zv == zu) or (bool(tv) and tv == tu)

        zone_class = zone_agreement(zv, hi_med)
        transit_class = transit_agreement(tv, legacy)
        lc = listing_counts.get(pid, 0)
        corr = correction_class(match_class, zone_class, rx_conf, lc)

        rx = rx_by_id.get(rx_id) if rx_id else None
        rows.append(
            {
                "pantip_project_id": pid,
                "pantip_bucket_key": project.get("bucket_key", ""),
                "pantip_canonical_name": project.get("canonical_name", ""),
                "pantip_aliases": (project.get("aliases") or [])[:5],
                "live_listing_count": lc,
                "realxtate_project_id": rx_id,
                "realxtate_bucket_key": (rx or {}).get("bucket_key"),
                "realxtate_name": (rx or {}).get("name"),
                "match_class": match_class,
                "match_evidence": evidence,
                "identity_conflict_flags": ["bucket_mismatch"] if match_class == "CONFLICT" else [],
                "pantip_zone_verified": zv[:5],
                "pantip_zone_unverified": zu[:3],
                "pantip_transit_verified": tv[:5],
                "pantip_transit_unverified": tu[:3],
                "realxtate_marketplace_areas": areas[:3],
                "realxtate_area_confidence": rx_conf,
                "zone_agreement_class": zone_class,
                "transit_agreement_class": transit_class,
                "legacy_promotion_suspected": legacy,
                "legacy_verification_class": (
                    "LEGACY_PROMOTION_SUSPECTED" if legacy else "INDEPENDENTLY_CORROBORATED"
                ),
                "coordinate_reference_class": coord_states.get(pid, "COORD_MISSING"),
                "correction_class": corr,
                "review_reason": [zone_class] if corr != "DO_NOT_TOUCH" else [],
            }
        )

    summary = {
        "match_classes": dict(match_classes),
        "area_overlay": {
            "REALXTATE_HIGH": sum(1 for r in rows if r["realxtate_area_confidence"] == "REALXTATE_HIGH"),
            "REALXTATE_MEDIUM": sum(1 for r in rows if r["realxtate_area_confidence"] == "REALXTATE_MEDIUM"),
            "REALXTATE_LOW": sum(1 for r in rows if r["realxtate_area_confidence"] == "REALXTATE_LOW"),
            "NO_REALXTATE_AREA": sum(1 for r in rows if r["realxtate_area_confidence"] == "NO_REALXTATE_AREA"),
        },
    }
    return rows, summary


def reconcile_phase_v_conflicts(
    git_projects: list[dict], live_ids: set[str], rx_by_id: dict, rx_by_bucket: dict, rx_by_norm: dict
) -> list[dict]:
    conflicts: list[dict] = []
    for project in git_projects:
        pid = project["id"]
        bucket = project.get("bucket_key", "")
        if pid in rx_by_id or bucket in rx_by_bucket:
            continue
        sn = soft_norm(project.get("canonical_name", ""))
        hits = rx_by_norm.get(sn, [])
        if len(hits) == 1 and hits[0].get("bucket_key") != bucket:
            reason = "name_match_bucket_mismatch"
        elif len(hits) > 1:
            reason = "multiple_rx_name_matches"
        else:
            continue
        if pid not in live_ids:
            klass = "GIT_ONLY_STALE"
        elif bucket in rx_by_bucket:
            klass = "BUCKET_VARIANT"
        elif hits:
            klass = "NAME_VARIANT_ONLY"
        else:
            klass = "TRUE_IDENTITY_CONFLICT"
        conflicts.append(
            {
                "project_id": pid,
                "bucket_key": bucket,
                "canonical_name": project.get("canonical_name", ""),
                "in_live": pid in live_ids,
                "classification": klass,
                "reason": reason,
            }
        )
    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description="Build offline LIVE project crosswalk")
    parser.add_argument("--pantip-projects", type=Path, required=True)
    parser.add_argument("--pantip-properties", type=Path, required=True)
    parser.add_argument("--realxtate-catalog", type=Path, required=True)
    parser.add_argument("--realxtate-trusted", type=Path, required=True)
    parser.add_argument("--git-projects", type=Path, default=None, help="Optional Git snapshot for delta")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    inputs = [args.pantip_projects, args.pantip_properties, args.realxtate_catalog, args.realxtate_trusted]
    if args.git_projects:
        inputs.append(args.git_projects)
    assert_no_output_overlap(inputs, args.output_dir)

    live_projects = load_json(args.pantip_projects)
    live_properties = load_json(args.pantip_properties)
    if not isinstance(live_projects, list) or not isinstance(live_properties, list):
        raise ValueError("Pantip project/property inputs must be JSON arrays")

    live_ids = {p["id"] for p in live_projects}
    if len(live_ids) != len(live_projects):
        raise ValueError("Duplicate canonical project IDs in live projects input")

    rx_projects = load_realxtate_projects(args.realxtate_catalog)
    area_by_project = load_area_assignments(args.realxtate_trusted)
    coord_states = load_coordinate_states(args.realxtate_trusted)

    crosswalk, crosswalk_summary = build_crosswalk(
        live_projects, live_properties, rx_projects, area_by_project, coord_states
    )

    git_delta = {}
    phase_v_conflicts = []
    if args.git_projects and args.git_projects.is_file():
        git_projects = load_json(args.git_projects)
        git_ids = {p["id"] for p in git_projects}
        git_delta = {
            "LIVE_AND_GIT": len(live_ids & git_ids),
            "LIVE_ONLY": len(live_ids - git_ids),
            "GIT_ONLY": len(git_ids - live_ids),
        }
        rx_by_id = {r["id"]: r for r in rx_projects}
        rx_by_bucket = {r["bucket_key"]: r for r in rx_projects if r.get("bucket_key")}
        rx_by_norm: dict[str, list[dict]] = defaultdict(list)
        for rx in rx_projects:
            for name in [rx.get("name", "")] + (rx.get("aliases") or []):
                key = soft_norm(name)
                if key:
                    rx_by_norm[key].append(rx)
        phase_v_conflicts = reconcile_phase_v_conflicts(
            git_projects, live_ids, rx_by_id, rx_by_bucket, rx_by_norm
        )

    area_matrix = Counter()
    area_listings = Counter()
    transit_matrix = Counter()
    coord_matrix = Counter()
    legacy_zone = legacy_transit = 0
    legacy_listings = 0
    zone_top = Counter()
    transit_top = Counter()

    for row in crosswalk:
        area_matrix[row["zone_agreement_class"]] += 1
        area_listings[row["zone_agreement_class"]] += row["live_listing_count"]
        transit_matrix[row["transit_agreement_class"]] += 1
        coord_matrix[row["coordinate_reference_class"]] += 1
        if row["legacy_promotion_suspected"]:
            legacy_listings += row["live_listing_count"]

    for project in live_projects:
        zv = project.get("zone_verified") or []
        zu = project.get("zone_unverified") or []
        tv = project.get("transit_verified") or []
        tu = project.get("transit_unverified") or []
        if zv and zv == zu:
            legacy_zone += 1
        if tv and tv == tu:
            legacy_transit += 1
        for z in zv:
            zone_top[z] += 1
        for t in tv:
            transit_top[t] += 1

    queue = sorted(crosswalk, key=priority_score, reverse=True)[:50]
    for item in queue:
        item["priority"] = priority_band(priority_score(item))

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    overlay = {
        row["pantip_project_id"]: {
            "areas": row["realxtate_marketplace_areas"],
            "confidence": row["realxtate_area_confidence"],
        }
        for row in crosswalk
        if row["realxtate_area_confidence"] in ("REALXTATE_HIGH", "REALXTATE_MEDIUM")
    }

    summary = {
        "live": {
            "projects": len(live_projects),
            "properties": len(live_properties),
            "unique_project_ids": len(live_ids),
            "duplicate_project_ids": len(live_projects) - len(live_ids),
            "missing_project_id": sum(1 for pr in live_properties if not pr.get("project_id")),
            "orphan_project_refs": sum(
                1
                for pr in live_properties
                if pr.get("project_id") and pr["project_id"] not in live_ids
            ),
        },
        "realxtate": {"projects": len(rx_projects)},
        "live_git_delta": git_delta,
        "match_classes": crosswalk_summary["match_classes"],
        "area_overlay": {
            **crosswalk_summary["area_overlay"],
            "hi_med_affected_listings": sum(
                row["live_listing_count"]
                for row in crosswalk
                if row["realxtate_area_confidence"] in ("REALXTATE_HIGH", "REALXTATE_MEDIUM")
            ),
        },
        "phase_v_78_reconciliation": dict(Counter(c["classification"] for c in phase_v_conflicts)),
        "legacy_audit": {
            "zone_verified_equals_unverified": legacy_zone,
            "transit_verified_equals_unverified": legacy_transit,
            "affected_listings_legacy_promotion": legacy_listings,
            "top_zones": zone_top.most_common(10),
            "top_transit": transit_top.most_common(10),
        },
        "area_agreement_matrix_projects": dict(area_matrix),
        "area_agreement_matrix_listings": dict(area_listings),
        "transit_agreement_matrix": dict(transit_matrix),
        "coordinate_reference_matrix": dict(coord_matrix),
        "owner_review_queue_priority": dict(Counter(item["priority"] for item in queue)),
    }

    (out / "live-project-crosswalk.json").write_text(
        json.dumps(crosswalk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "area-reference-overlay.json").write_text(
        json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "identity-conflicts.json").write_text(
        json.dumps(phase_v_conflicts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "phase-w-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with open(out / "owner-review-top50.csv", "w", newline="", encoding="utf-8") as fh:
        fields = [
            "priority",
            "pantip_project_id",
            "pantip_canonical_name",
            "live_listing_count",
            "match_class",
            "realxtate_area_confidence",
            "zone_agreement_class",
            "transit_agreement_class",
            "correction_class",
            "legacy_promotion_suspected",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for item in queue:
            writer.writerow({key: item.get(key, "") for key in fields})

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
