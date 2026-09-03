#!/usr/bin/env python3
"""Phase Z2 — acquire coordinate evidence (bounded public batch)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.coordinate_acquisition import (
    OUTCOME_CANDIDATE_SINGLE_SOURCE,
    OUTCOME_COORDINATE_CONFLICT,
    OUTCOME_IDENTITY_REVIEW_REQUIRED,
    OUTCOME_NO_EVIDENCE_FOUND,
    OUTCOME_RECOVERED_CORROBORATED,
    OUTCOME_RECOVERED_TRUSTED,
    OUTCOME_RETRIEVAL_FAILED,
    OUTCOME_UNSUPPORTED_SPATIAL_TYPE,
    acquire_for_entry,
    build_missing_coordinate_queue,
)
from src.hub.population_accounting import DEFAULT_TRUSTED

DEFAULT_OUT = Path("/tmp/pantip-phase-z2-evidence")
DEFAULT_BATCH_LIMIT = 100


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire coordinate evidence")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--batch-limit", type=int, default=DEFAULT_BATCH_LIMIT)
    parser.add_argument("--fetch-public", action="store_true", help="Fetch public reference URLs (bounded)")
    parser.add_argument("--priority", default="P0,P1", help="Comma-separated priority bands")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = args.output_dir / "cache"
    cache_dir.mkdir(exist_ok=True)

    bands = set(args.priority.split(","))
    queue = [e for e in build_missing_coordinate_queue() if e.priority_band in bands]

    results = []
    public_requests = 0
    for entry in queue:
        do_fetch = args.fetch_public and public_requests < args.batch_limit and entry.known_reference_urls
        if do_fetch:
            public_requests += 1
        result = acquire_for_entry(entry, trusted_db=DEFAULT_TRUSTED, fetch_public=do_fetch)
        results.append(result.to_dict())

    outcomes = Counter(r["outcome"] for r in results)
    report = {
        "processed": len(results),
        "priority_bands": sorted(bands),
        "public_fetch_enabled": args.fetch_public,
        "public_request_count": public_requests,
        "outcomes": dict(outcomes),
    }
    (args.output_dir / "acquisition-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "acquisition-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
