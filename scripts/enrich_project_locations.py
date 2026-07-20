#!/usr/bin/env python3
"""Enrich all project master location forms (ทำเล + BTS/MRT)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.project_location_enrich import enrich_all_projects  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--min-listings", type=int, default=0)
    args = ap.parse_args()

    stats = enrich_all_projects(dry_run=args.dry_run, min_listings=args.min_listings)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("\n(dry-run — nothing written)", file=sys.stderr)
    else:
        print(f"\n✓ updated {stats['projects_updated']} projects, synced {stats['listings_synced']} listings", file=sys.stderr)


if __name__ == "__main__":
    main()
