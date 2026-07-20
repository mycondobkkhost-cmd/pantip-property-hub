#!/usr/bin/env python3
"""Export project master ทำเล/สถานี → data/project_loc_lookup.tsv (+ optional sheet tab)."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.project_store import (  # noqa: E402
    load_projects,
    project_transit_display,
    project_zone_display,
)

OUT = ROOT / "data" / "project_loc_lookup.tsv"


def _norm_key(name: str) -> str:
    import re

    n = (name or "").lower()
    n = re.sub(r"[()（）]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def build_rows() -> list[list[str]]:
    rows: list[list[str]] = [["project_key", "ทำเล", "สถานี"]]
    seen: set[str] = set()
    for proj in load_projects():
        zones = ", ".join(project_zone_display(proj)[:5])
        transit = ", ".join(project_transit_display(proj)[:3])
        if not zones and not transit:
            continue
        names = [proj.get("canonical_name") or ""] + list(proj.get("aliases") or [])
        for name in names:
            key = _norm_key(name)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append([key, zones, transit])
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    rows = build_rows()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f, delimiter="\t").writerows(rows)
    print(f"wrote {len(rows) - 1} keys → {args.out}", flush=True)


if __name__ == "__main__":
    main()
