#!/usr/bin/env python3
"""Merge duplicate projects into a keep-id; update aliases map + properties."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
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
    load_projects,
    load_properties,
    persist,
    sync_project_listings_location_ref,
    write_preview_js,
)

AUDIT = ROOT / "data" / "project_dedupe" / "audit_report.json"


def merge_tag_lists(*lists: list) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for lst in lists:
        for x in lst or []:
            s = str(x).strip()
            if not s:
                continue
            k = soft_norm(s) or s.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
    return out


def apply_merge(
    projects: list[dict],
    properties: list[dict],
    keep_id: str,
    merge_ids: list[str],
    aliases_data: dict,
) -> dict:
    by_id = {p["id"]: p for p in projects}
    keep = by_id.get(keep_id)
    if not keep:
        raise ValueError(f"keep project not found: {keep_id}")

    merged_names: list[str] = []
    for mid in merge_ids:
        src = by_id.get(mid)
        if not src or mid == keep_id:
            continue
        merged_names.append(src.get("canonical_name") or "")
        # fold aliases
        keep["aliases"] = merge_tag_lists(
            keep.get("aliases") or [],
            [src.get("canonical_name") or ""],
            src.get("aliases") or [],
        )
        keep["transit_verified"] = merge_tag_lists(
            keep.get("transit_verified") or [], src.get("transit_verified") or []
        )[:6]
        keep["transit_unverified"] = merge_tag_lists(
            keep.get("transit_unverified") or [], src.get("transit_unverified") or []
        )[:8]
        keep["zone_verified"] = merge_tag_lists(
            keep.get("zone_verified") or [], src.get("zone_verified") or []
        )[:6]
        keep["zone_unverified"] = merge_tag_lists(
            keep.get("zone_unverified") or [], src.get("zone_unverified") or []
        )[:8]
        keep["listing_count"] = int(keep.get("listing_count") or 0) + int(
            src.get("listing_count") or 0
        )

        # alias map: variant soft → keep bucket
        vmap = aliases_data.setdefault("variant_to_canonical", {})
        keep_bucket = keep.get("bucket_key") or project_bucket(keep.get("canonical_name") or "")
        for name in [src.get("canonical_name") or "", src.get("bucket_key") or ""]:
            soft = soft_norm(name) if name else ""
            if soft and keep_bucket:
                vmap[soft] = keep_bucket
            if name and keep_bucket and name != keep_bucket:
                vmap[name] = keep_bucket
        src_bucket = src.get("bucket_key") or ""
        if src_bucket and keep_bucket:
            vmap[src_bucket] = keep_bucket

        # reassign listings
        for prop in properties:
            if prop.get("project_id") == mid:
                prop["project_id"] = keep_id
                prop["project_name"] = keep.get("canonical_name") or prop.get("project_name")

        projects[:] = [p for p in projects if p["id"] != mid]

    sync_project_listings_location_ref(keep, properties)
    return {
        "keep_id": keep_id,
        "keep_name": keep.get("canonical_name"),
        "merged": merged_names,
        "listing_count": keep.get("listing_count"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-audit-high", action="store_true", help="Merge all high groups from audit")
    ap.add_argument("--keep-id", default="")
    ap.add_argument("--merge-ids", default="", help="Comma-separated project ids")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    projects = load_projects()
    properties = load_properties()
    aliases_data = load_aliases()
    results = []

    jobs: list[tuple[str, list[str]]] = []
    if args.from_audit_high:
        report = json.loads(AUDIT.read_text(encoding="utf-8"))
        for g in report.get("high") or []:
            keep_id = g["keep"]["id"]
            merge_ids = [m["id"] for m in g.get("merge") or []]
            jobs.append((keep_id, merge_ids))
    elif args.keep_id and args.merge_ids:
        jobs.append((args.keep_id, [x.strip() for x in args.merge_ids.split(",") if x.strip()]))
    else:
        raise SystemExit("Use --from-audit-high or --keep-id + --merge-ids")

    # Deduplicate merge jobs (same merge id only once)
    consumed: set[str] = set()
    for keep_id, merge_ids in jobs:
        merge_ids = [m for m in merge_ids if m not in consumed and m != keep_id]
        if not merge_ids:
            continue
        for m in merge_ids:
            consumed.add(m)
        if args.dry_run:
            results.append({"keep_id": keep_id, "merge_ids": merge_ids, "dry_run": True})
            continue
        results.append(apply_merge(projects, properties, keep_id, merge_ids, aliases_data))

    if not args.dry_run:
        # recount listing_count
        counts: dict[str, int] = {}
        for prop in properties:
            pid = prop.get("project_id") or ""
            if pid:
                counts[pid] = counts.get(pid, 0) + 1
        for proj in projects:
            proj["listing_count"] = counts.get(proj["id"], 0)
        projects.sort(key=lambda x: (-int(x.get("listing_count") or 0), x["canonical_name"]))
        persist(projects, properties)
        write_preview_js(projects, properties)
        save_aliases(aliases_data)
        aliases_data.setdefault("decisions", []).append(
            {"action": "auto_merge_high", "count": len(results)}
        )
        save_aliases(aliases_data)

    print(json.dumps({"merged_groups": len(results), "results": results[:30], "total_projects": len(projects)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
