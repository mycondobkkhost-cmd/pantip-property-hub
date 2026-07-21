#!/usr/bin/env python3
"""Explode compound transit tags on projects + listings into atomic stations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.project_store import (  # noqa: E402
    dedupe_stations,
    load_projects,
    load_properties,
    persist,
    sync_project_listings_location_ref,
)


def cleanup_project_transits(projects: list[dict]) -> int:
    changed = 0
    for proj in projects:
        before_v = list(proj.get("transit_verified") or [])
        before_u = list(proj.get("transit_unverified") or [])
        verified = dedupe_stations(before_v)
        unverified = dedupe_stations(before_u)
        # drop unverified that are already covered by verified
        vset = set(verified)
        unverified = [t for t in unverified if t not in vset]
        if verified != before_v or unverified != before_u:
            proj["transit_verified"] = verified
            proj["transit_unverified"] = unverified
            changed += 1
    return changed


def cleanup_listing_transits(properties: list[dict]) -> int:
    changed = 0
    for prop in properties:
        before = list(prop.get("transit_from_sheet") or [])
        after = dedupe_stations(before)
        if after != before:
            prop["transit_from_sheet"] = after
            changed += 1
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    projects = load_projects()
    properties = load_properties()
    pc = cleanup_project_transits(projects)
    lc = cleanup_listing_transits(properties)
    synced = 0
    if not args.dry_run:
        for proj in projects:
            synced += sync_project_listings_location_ref(proj, properties)
        persist(projects, properties)

    print(
        json.dumps(
            {
                "projects_transit_cleaned": pc,
                "listings_transit_cleaned": lc,
                "listings_location_synced": synced,
                "dry_run": args.dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
