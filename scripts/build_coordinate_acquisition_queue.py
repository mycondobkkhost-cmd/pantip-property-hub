#!/usr/bin/env python3
"""Phase Z2 — build missing-coordinate acquisition queue."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.coordinate_acquisition import build_missing_coordinate_queue
from src.hub.population_accounting import reconcile_population

DEFAULT_OUT = Path("/tmp/pantip-phase-z2-evidence")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build missing-coordinate queue")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    pop = reconcile_population()
    queue = build_missing_coordinate_queue()
    bands = Counter(e.priority_band for e in queue)
    identity = Counter(e.identity_confidence for e in queue)
    with_urls = sum(1 for e in queue if e.known_reference_urls)

    summary = {
        "population": pop.to_dict(),
        "queue_total": len(queue),
        "priority_bands": dict(bands),
        "identity_confidence": dict(identity),
        "with_reference_urls": with_urls,
    }
    (args.output_dir / "missing-coordinate-queue.json").write_text(
        json.dumps([e.to_dict() for e in queue], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "queue-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
