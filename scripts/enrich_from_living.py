#!/usr/bin/env python3
"""Enrich project master ทำเล + BTS/MRT from Livinginsider listing pages."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.project_location_enrich import (  # noqa: E402
    enrich_all_projects,
    enrich_projects_from_living,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-listings", type=int, default=0)
    ap.add_argument("--max-projects", type=int, default=None)
    ap.add_argument("--samples", type=int, default=2, help="Living listings to sample per project")
    ap.add_argument("--sleep", type=float, default=0.45)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--force", action="store_true", help="Re-fetch even if already Living-verified")
    ap.add_argument(
        "--fallback-corridors",
        action="store_true",
        help="After Living, fill remaining with corridor/override heuristics",
    )
    args = ap.parse_args()

    living = enrich_projects_from_living(
        dry_run=args.dry_run,
        min_listings=args.min_listings,
        max_projects=args.max_projects,
        samples_per_project=args.samples,
        sleep_s=args.sleep,
        use_cache=not args.no_cache,
        force=args.force,
    )
    out: dict = {"living": living}
    if args.fallback_corridors:
        out["fallback"] = enrich_all_projects(
            dry_run=args.dry_run, min_listings=args.min_listings
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("\n(dry-run — nothing written)", file=sys.stderr)
    else:
        print(
            f"\n✓ Living verified {living['projects_verified']} projects, "
            f"synced {living['listings_synced']} listings "
            f"(fetches={living['http_fetches']}, cache={living['cache_hits']})",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
