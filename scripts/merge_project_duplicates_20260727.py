#!/usr/bin/env python3
"""Merge duplicate project clusters from logs/project_duplicates_20260727.json."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.project_identity import (  # noqa: E402
    load_aliases,
    project_bucket,
    save_aliases,
    soft_norm,
)
from src.hub.project_store import (  # noqa: E402
    dedupe_stations,
    parse_tag_list,
    persist,
    sync_project_listings_location_ref,
)

REPORT = ROOT / "logs" / "project_duplicates_20260727.json"
OUT_LOG = ROOT / "logs" / "project_merge_20260727_result.json"


def _extract_thai(name: str) -> str:
    m = re.search(r"\(([^)]*[ก-๙][^)]*)\)", name or "")
    return (m.group(1) or "").strip() if m else ""


def _strip_parens(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", (name or "").strip()).strip()


def _union_tags(*lists: list, stations: bool = False) -> list[str]:
    merged: list[str] = []
    for lst in lists:
        for x in lst or []:
            if x and str(x).strip():
                merged.append(str(x).strip())
    return dedupe_stations(merged) if stations else parse_tag_list(merged)


def _pick_nonempty(*vals):
    for v in vals:
        if v not in (None, "", [], {}):
            return v
    return vals[-1] if vals else None


def build_canonical(cluster: dict, keep: dict) -> str:
    """Propertyhub EN when known; else report target / most-rooms; keep Thai parens."""
    variants = cluster.get("variants") or []
    top = max(variants, key=lambda v: int(v.get("rooms") or 0)) if variants else None
    top_name = (top or {}).get("name") or keep.get("canonical_name") or ""
    thai = (
        (cluster.get("propertyhub_thai") or "").strip()
        or _extract_thai(top_name)
        or _extract_thai(keep.get("canonical_name") or "")
    )

    ph_name = (cluster.get("propertyhub_name") or "").strip()
    ph_status = cluster.get("propertyhub_status") or ""
    target = (cluster.get("suggested_merge_target") or "").strip()
    confirmed = ("ยืนยัน" in ph_status) or ("คาดว่าตรง" in ph_status)

    if confirmed and ph_name:
        en = ph_name
    elif target:
        if _extract_thai(target):
            # already Hub-style EN (TH)
            return target
        en = _strip_parens(target)
    else:
        # Prefer most-rooms Hub display (already has EN+TH)
        return top_name or keep.get("canonical_name") or ""

    if thai:
        return f"{en} ({thai})"
    return en


def merge_project_records(keep: dict, donors: list[dict]) -> dict:
    aliases: list[str] = list(keep.get("aliases") or [])
    for d in donors:
        old = (d.get("canonical_name") or "").strip()
        if old and old not in aliases and old != keep.get("canonical_name"):
            aliases.append(old)
        for a in d.get("aliases") or []:
            a = (a or "").strip()
            if a and a not in aliases and a != keep.get("canonical_name"):
                aliases.append(a)

    keep["aliases"] = aliases
    keep["transit_verified"] = _union_tags(
        keep.get("transit_verified"),
        *[d.get("transit_verified") for d in donors],
        stations=True,
    )
    keep["zone_verified"] = _union_tags(
        keep.get("zone_verified"),
        *[d.get("zone_verified") for d in donors],
    )
    keep["transit_unverified"] = _union_tags(
        keep.get("transit_unverified"),
        *[d.get("transit_unverified") for d in donors],
        stations=True,
    )
    keep["zone_unverified"] = _union_tags(
        keep.get("zone_unverified"),
        *[d.get("zone_unverified") for d in donors],
    )

    # Prefer verified status / richer location metadata
    statuses = [keep.get("location_status")] + [d.get("location_status") for d in donors]
    if "verified" in statuses:
        keep["location_status"] = "verified"
    elif any(s for s in statuses if s):
        keep["location_status"] = next(s for s in statuses if s)

    keep["location_source"] = _pick_nonempty(
        keep.get("location_source"),
        *[d.get("location_source") for d in donors],
    ) or keep.get("location_source") or ""
    keep["living_zone"] = _pick_nonempty(
        keep.get("living_zone"),
        *[d.get("living_zone") for d in donors],
    ) or keep.get("living_zone") or ""
    keep["living_project_url"] = _pick_nonempty(
        keep.get("living_project_url"),
        *[d.get("living_project_url") for d in donors],
    ) or keep.get("living_project_url") or ""
    keep["is_thru_thonglor"] = bool(keep.get("is_thru_thonglor")) or any(
        d.get("is_thru_thonglor") for d in donors
    )
    return keep


def main() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    clusters = report.get("clusters") or []
    # Explicitly skip false-positive exclusion pairs
    skip_keys = {
        c.get("cluster_key")
        for c in (report.get("review_needed_suspects") or [])
        if c.get("false_positive_suspect") or c.get("fp_reason")
    }

    projects = json.loads((ROOT / "data" / "projects.json").read_text(encoding="utf-8"))
    properties = json.loads((ROOT / "data" / "properties.json").read_text(encoding="utf-8"))
    by_id = {p["id"]: p for p in projects}

    aliases_data = load_aliases()
    vmap = dict(aliases_data.get("variant_to_canonical") or {})
    decisions = list(aliases_data.get("decisions") or [])

    merge_log: list[dict] = []
    props_updated = 0
    names_removed: list[str] = []
    clusters_merged = 0
    remove_ids: set[str] = set()

    for cluster in clusters:
        key = cluster.get("cluster_key")
        if key in skip_keys:
            continue
        variants = cluster.get("variants") or []
        if len(variants) < 2:
            continue

        keep_id = cluster.get("suggested_keep_id") or variants[0]["id"]
        keep = by_id.get(keep_id)
        if not keep:
            # fallback: most rooms among present
            present = [by_id[v["id"]] for v in variants if v["id"] in by_id]
            if not present:
                continue
            keep = max(present, key=lambda p: int(p.get("listing_count") or 0))
            keep_id = keep["id"]

        donor_ids = [
            v["id"]
            for v in variants
            if v["id"] != keep_id and v["id"] in by_id and v["id"] not in remove_ids
        ]
        donors = [by_id[i] for i in donor_ids]
        if not donors and not any(
            (p.get("project_id") in {v["id"] for v in variants} and p.get("project_id") != keep_id)
            for p in properties
        ):
            # still rename keep to canonical if needed
            pass

        canonical = build_canonical(cluster, keep)
        old_keep_name = keep.get("canonical_name")

        # Merge master fields
        if donors:
            merge_project_records(keep, donors)

        # Old keep name becomes alias if renamed
        if old_keep_name and old_keep_name != canonical:
            als = list(keep.get("aliases") or [])
            if old_keep_name not in als:
                als.append(old_keep_name)
            keep["aliases"] = als

        keep["canonical_name"] = canonical
        # Keep existing bucket_key (most-rooms) for UUID stability; aliases redirect others
        keep_bucket = keep.get("bucket_key") or project_bucket(canonical) or soft_norm(canonical)

        # Update properties pointing at any variant id
        variant_ids = {v["id"] for v in variants}
        variant_names = {v["name"] for v in variants}
        cluster_prop_updates = 0
        for prop in properties:
            pid = prop.get("project_id")
            pname = prop.get("project_name") or ""
            hit = pid in variant_ids or pname in variant_names
            if not hit:
                continue
            changed = False
            if prop.get("project_id") != keep_id:
                prop["project_id"] = keep_id
                changed = True
            if prop.get("project_name") != canonical:
                prop["project_name"] = canonical
                changed = True
            if changed:
                cluster_prop_updates += 1
                props_updated += 1

        sync_project_listings_location_ref(keep, properties)

        for d in donors:
            names_removed.append(d.get("canonical_name") or d["id"])
            remove_ids.add(d["id"])

        # Alias map: every variant soft/bucket → keep_bucket
        for v in variants:
            vid = v["id"]
            proj = by_id.get(vid) or {}
            for label in [
                v.get("name"),
                proj.get("canonical_name"),
                proj.get("bucket_key"),
                soft_norm(v.get("name") or ""),
                soft_norm(proj.get("canonical_name") or ""),
            ]:
                if not label:
                    continue
                vmap[str(label)] = keep_bucket
            for a in proj.get("aliases") or []:
                if a:
                    vmap[a] = keep_bucket
                    sn = soft_norm(a)
                    if sn:
                        vmap[sn] = keep_bucket

        # also map new canonical soft key → keep bucket
        sn_new = soft_norm(canonical)
        if sn_new:
            vmap[sn_new] = keep_bucket
        pb_new = project_bucket(canonical)
        if pb_new:
            vmap[pb_new] = keep_bucket

        decisions.append(
            {
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "action": "merge_duplicates_20260727",
                "cluster_key": key,
                "confidence": cluster.get("confidence"),
                "keep_id": keep_id,
                "keep_bucket": keep_bucket,
                "canonical_name": canonical,
                "removed_ids": donor_ids,
                "propertyhub_status": cluster.get("propertyhub_status"),
                "propertyhub_name": cluster.get("propertyhub_name"),
            }
        )

        merge_log.append(
            {
                "cluster_key": key,
                "confidence": cluster.get("confidence"),
                "canonical_name": canonical,
                "keep_id": keep_id,
                "removed": [
                    {"id": d["id"], "name": d.get("canonical_name")} for d in donors
                ],
                "properties_updated": cluster_prop_updates,
                "total_rooms": cluster.get("total_rooms"),
            }
        )
        clusters_merged += 1

    # Drop removed projects
    projects = [p for p in projects if p["id"] not in remove_ids]
    by_id = {p["id"]: p for p in projects}

    # Recount listing_count
    counts: dict[str, int] = {}
    for prop in properties:
        pid = prop.get("project_id") or ""
        if pid:
            counts[pid] = counts.get(pid, 0) + 1
    for proj in projects:
        proj["listing_count"] = counts.get(proj["id"], 0)

    projects.sort(
        key=lambda x: (-int(x.get("listing_count") or 0), x.get("canonical_name") or "")
    )

    aliases_data["variant_to_canonical"] = vmap
    aliases_data["decisions"] = decisions[-500:]  # keep recent
    save_aliases(aliases_data)

    persist(projects, properties)

    result = {
        "merged_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "clusters_merged": clusters_merged,
        "project_names_removed": len(names_removed),
        "removed_names": names_removed,
        "properties_updated": props_updated,
        "projects_after": len(projects),
        "properties_total": len(properties),
        "merges": merge_log,
        "skipped_exclusion_keys": sorted(skip_keys),
    }
    OUT_LOG.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: result[k] for k in (
        "clusters_merged", "project_names_removed", "properties_updated",
        "projects_after", "properties_total"
    )}, ensure_ascii=False, indent=2))
    # Niche Pride sanity
    niche = [p for p in projects if "niche pride" in (p.get("canonical_name") or "").lower()
             and "thonglor" in (p.get("canonical_name") or "").lower()
             and "phetchaburi" in soft_norm(p.get("canonical_name") or "")]
    print("niche_pride_entries", len(niche))
    for n in niche:
        print(" ", n["canonical_name"], "rooms=", n["listing_count"], "id=", n["id"][:8])


if __name__ == "__main__":
    main()
