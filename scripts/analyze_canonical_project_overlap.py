#!/usr/bin/env python3
"""Read-only offline analysis: Pantip vs RealXtate project population overlap.

Safety guarantees:
- Never writes to input data files
- Never connects to Fly, Google Sheets, LINE, Facebook, or OpenAI
- Never modifies RealXtate repository
- Outputs summary JSON to a user-specified report path (default: stdout)

Usage:
  python3 scripts/analyze_canonical_project_overlap.py \\
    --pantip-data data \\
    --realxtate-db /path/to/realxtate-catalog.sqlite \\
    --output /tmp/overlap-summary.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path


def soft_norm(name: str) -> str:
    """Lightweight normalization aligned with Pantip project_identity.soft_norm."""
    n = (name or "").lower().strip()
    if n.count("(") > n.count(")"):
        n = n + (")" * (n.count("(") - n.count(")")))
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
        n = n + "r"
    return n


def uuid5_bucket(bucket: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ptp-project-{bucket}"))


def load_pantip_projects(data_dir: Path) -> list[dict]:
    path = data_dir / "projects.json"
    if not path.is_file():
        raise FileNotFoundError(f"Missing Pantip projects file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_pantip_properties(data_dir: Path) -> list[dict]:
    path = data_dir / "properties.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_realxtate_projects(db_path: Path) -> list[dict]:
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, aliases_json, bucket_key, location_status, listing_count "
        "FROM property_projects"
    )
    cols = [d[0] for d in cur.description]
    rows = []
    for row in cur.fetchall():
        item = dict(zip(cols, row))
        try:
            item["aliases"] = json.loads(item.pop("aliases_json") or "[]")
        except json.JSONDecodeError:
            item["aliases"] = []
        rows.append(item)
    conn.close()
    return rows


def field_profile(projects: list[dict]) -> dict:
    stats: dict[str, dict] = {}
    for p in projects:
        for key, val in p.items():
            fs = stats.setdefault(key, {"populated": 0, "missing": 0, "types": Counter()})
            empty = val is None or val == "" or val == [] or val == {}
            if empty:
                fs["missing"] += 1
            else:
                fs["populated"] += 1
                fs["types"][type(val).__name__] += 1
    return {
        k: {"populated": v["populated"], "missing": v["missing"], "types": dict(v["types"])}
        for k, v in stats.items()
    }


def compare_populations(pantip: list[dict], realxtate: list[dict]) -> dict:
    rx_by_id = {r["id"]: r for r in realxtate}
    rx_by_bucket = {r.get("bucket_key", ""): r for r in realxtate if r.get("bucket_key")}
    rx_by_norm_name: dict[str, list[dict]] = defaultdict(list)
    for r in realxtate:
        for nm in [r.get("name", "")] + (r.get("aliases") or []):
            sn = soft_norm(nm)
            if sn:
                rx_by_norm_name[sn].append(r)

    buckets = {
        "EXACT_ID_MATCH": [],
        "EXACT_STRONG_MATCH": [],
        "HIGH_CONFIDENCE_CANDIDATE": [],
        "MEDIUM_CONFIDENCE_CANDIDATE": [],
        "LOW_CONFIDENCE_CANDIDATE": [],
        "CONFLICT": [],
        "UNMATCHED_PANTIP": [],
    }
    matched_rx: set[str] = set()

    for p in pantip:
        pid = p["id"]
        bucket = p.get("bucket_key", "")
        cname = p.get("canonical_name", "")
        sn = soft_norm(cname)

        rx_hit = rx_by_id.get(pid) or rx_by_id.get(uuid5_bucket(bucket))
        if rx_hit:
            buckets["EXACT_ID_MATCH"].append({"pantip_id": pid, "bucket": bucket, "rx_id": rx_hit["id"]})
            matched_rx.add(rx_hit["id"])
            continue

        rx_bucket = rx_by_bucket.get(bucket)
        if rx_bucket:
            buckets["EXACT_ID_MATCH"].append(
                {"pantip_id": pid, "bucket": bucket, "rx_id": rx_bucket["id"], "via": "bucket_key"}
            )
            matched_rx.add(rx_bucket["id"])
            continue

        rx_name_hits = rx_by_norm_name.get(sn, [])
        if len(rx_name_hits) == 1:
            r = rx_name_hits[0]
            if r.get("bucket_key") == bucket:
                buckets["EXACT_STRONG_MATCH"].append({"pantip_id": pid, "bucket": bucket, "rx_id": r["id"]})
            else:
                buckets["CONFLICT"].append(
                    {
                        "pantip_id": pid,
                        "bucket": bucket,
                        "rx_id": r["id"],
                        "reason": "name_match_bucket_mismatch",
                    }
                )
            matched_rx.add(r["id"])
            continue
        if len(rx_name_hits) > 1:
            buckets["CONFLICT"].append(
                {"pantip_id": pid, "bucket": bucket, "reason": "multiple_rx_name_matches", "count": len(rx_name_hits)}
            )
            continue

        pantip_norms = {soft_norm(a) for a in (p.get("aliases") or []) if a}
        pantip_norms.add(sn)
        alias_hits = []
        for r in realxtate:
            r_norms = {soft_norm(r.get("name", ""))}
            for a in r.get("aliases") or []:
                r_norms.add(soft_norm(a))
            overlap = pantip_norms & r_norms
            if overlap:
                alias_hits.append((r, len(overlap)))
        if len(alias_hits) == 1:
            r, ov = alias_hits[0]
            key = "HIGH_CONFIDENCE_CANDIDATE" if r.get("bucket_key") == bucket else "MEDIUM_CONFIDENCE_CANDIDATE"
            buckets[key].append({"pantip_id": pid, "bucket": bucket, "rx_id": r["id"], "overlap": ov})
            matched_rx.add(r["id"])
            continue
        if len(alias_hits) > 1:
            buckets["MEDIUM_CONFIDENCE_CANDIDATE"].append(
                {"pantip_id": pid, "bucket": bucket, "reason": "multiple_alias_hits", "count": len(alias_hits)}
            )
            continue

        weak = []
        if len(sn) >= 6:
            for r in realxtate:
                rsn = soft_norm(r.get("name", ""))
                if rsn and (sn in rsn or rsn in sn) and abs(len(sn) - len(rsn)) <= 3:
                    weak.append(r)
        if len(weak) == 1:
            buckets["LOW_CONFIDENCE_CANDIDATE"].append(
                {"pantip_id": pid, "bucket": bucket, "rx_id": weak[0]["id"]}
            )
            matched_rx.add(weak[0]["id"])
        elif len(weak) > 1:
            buckets["LOW_CONFIDENCE_CANDIDATE"].append(
                {"pantip_id": pid, "bucket": bucket, "reason": "multiple_weak_prefix", "count": len(weak)}
            )
        else:
            buckets["UNMATCHED_PANTIP"].append({"pantip_id": pid, "bucket": bucket, "name": cname})

    unmatched_rx = [r["id"] for r in realxtate if r["id"] not in matched_rx]
    return {k: len(v) for k, v in buckets.items()} | {"UNMATCHED_REALXTATE": len(unmatched_rx)}


def pantip_quality(projects: list[dict], properties: list[dict]) -> dict:
    by_id = {p["id"]: p for p in projects}
    name_norm_counts = Counter(soft_norm(p.get("canonical_name", "")) for p in projects if p.get("canonical_name"))
    dup_norm = sum(1 for _, c in name_norm_counts.items() if c > 1)

    prefix_groups: dict[str, list[dict]] = defaultdict(list)
    for p in projects:
        sn = soft_norm(p.get("canonical_name", ""))
        if len(sn) >= 8:
            prefix_groups[sn[:8]].append(p)
    near_dup = sum(1 for grp in prefix_groups.values() if len({x["bucket_key"] for x in grp}) > 1)

    zone_top = Counter()
    transit_top = Counter()
    for p in projects:
        for z in p.get("zone_verified") or []:
            zone_top[z] += 1
        for t in p.get("transit_verified") or []:
            transit_top[t] += 1

    return {
        "projects_total": len(projects),
        "properties_total": len(properties),
        "properties_missing_project_id": sum(1 for pr in properties if not pr.get("project_id")),
        "properties_orphan_project_id": sum(
            1 for pr in properties if pr.get("project_id") and pr["project_id"] not in by_id
        ),
        "duplicate_normalized_canonical_names": dup_norm,
        "near_duplicate_prefix_groups": near_dup,
        "projects_missing_zone_verified": sum(1 for p in projects if not p.get("zone_verified")),
        "projects_missing_transit_verified": sum(1 for p in projects if not p.get("transit_verified")),
        "projects_pending_verification": sum(1 for p in projects if p.get("location_status") == "pending_verification"),
        "projects_with_coordinates": sum(1 for p in projects if p.get("latitude") or p.get("longitude")),
        "sparse_identity_projects": sum(
            1 for p in projects if not (p.get("aliases") or []) and (p.get("listing_count") or 0) <= 1
        ),
        "top_zones_verified": zone_top.most_common(5),
        "top_transit_verified": transit_top.most_common(5),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Pantip/RealXtate project overlap analysis")
    parser.add_argument("--pantip-data", type=Path, default=Path("data"), help="Pantip data directory")
    parser.add_argument("--realxtate-db", type=Path, default=None, help="RealXtate catalog SQLite (optional)")
    parser.add_argument("--output", type=Path, default=None, help="Write JSON summary here (default: stdout)")
    args = parser.parse_args()

    pantip_projects = load_pantip_projects(args.pantip_data)
    pantip_properties = load_pantip_properties(args.pantip_data)
    realxtate_projects = load_realxtate_projects(args.realxtate_db) if args.realxtate_db else []

    summary = {
        "pantip_projects": len(pantip_projects),
        "pantip_properties": len(pantip_properties),
        "realxtate_projects": len(realxtate_projects),
        "field_profile": field_profile(pantip_projects),
        "quality": pantip_quality(pantip_projects, pantip_properties),
        "overlap": compare_populations(pantip_projects, realxtate_projects) if realxtate_projects else None,
        "notes": [
            "Read-only analysis; no input files modified.",
            "Git data/ is a repository snapshot; production Fly /app/data is authoritative for live Pantip.",
        ],
    }

    text = json.dumps(summary, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
