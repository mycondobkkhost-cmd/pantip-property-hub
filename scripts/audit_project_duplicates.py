#!/usr/bin/env python3
"""Audit near-duplicate projects → high / medium / low groups."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.project_identity import (  # noqa: E402
    classify_duplicate_pair,
    soft_norm,
)
from src.hub.project_store import load_projects  # noqa: E402

OUT_DIR = ROOT / "data" / "project_dedupe"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-pairs", type=int, default=5000)
    args = ap.parse_args()

    projects = load_projects()
    by_soft: dict[str, list[dict]] = defaultdict(list)
    for p in projects:
        soft = soft_norm(p.get("canonical_name") or "") or (p.get("bucket_key") or "")
        by_soft[soft].append(p)

    # exact soft collisions
    high: list[dict] = []
    medium: list[dict] = []
    low: list[dict] = []

    # Group 1: identical soft_norm across different bucket_keys
    for soft, group in by_soft.items():
        if len(group) < 2:
            continue
        buckets = {g.get("bucket_key") for g in group}
        if len(buckets) < 2:
            continue
        # pick canonical = highest listing_count
        group_sorted = sorted(group, key=lambda x: -int(x.get("listing_count") or 0))
        keep = group_sorted[0]
        merge = group_sorted[1:]
        high.append(
            {
                "reason": "same_soft_norm",
                "soft": soft,
                "keep": {
                    "id": keep["id"],
                    "bucket_key": keep.get("bucket_key"),
                    "name": keep.get("canonical_name"),
                    "listings": keep.get("listing_count") or 0,
                },
                "merge": [
                    {
                        "id": m["id"],
                        "bucket_key": m.get("bucket_key"),
                        "name": m.get("canonical_name"),
                        "listings": m.get("listing_count") or 0,
                    }
                    for m in merge
                ],
                "confidence": "high",
            }
        )

    # Group 2: pairwise among top projects (by listings) for fuzzy
    ranked = sorted(projects, key=lambda x: -int(x.get("listing_count") or 0))
    # only compare projects with at least 1 listing to keep runtime sane
    candidates = [p for p in ranked if int(p.get("listing_count") or 0) >= 1][:800]
    seen_pairs: set[tuple[str, str]] = set()
    pairs_checked = 0

    for i, a in enumerate(candidates):
        sa = soft_norm(a.get("canonical_name") or "") or a.get("bucket_key") or ""
        if len(sa) < 6:
            continue
        for b in candidates[i + 1 : i + 80]:
            pairs_checked += 1
            if pairs_checked > args.limit_pairs:
                break
            sb = soft_norm(b.get("canonical_name") or "") or b.get("bucket_key") or ""
            if not sb or sa == sb:
                continue
            # cheap prefilter: share first 5 chars or edit-distance candidate
            if sa[:5] != sb[:5] and abs(len(sa) - len(sb)) > 4:
                continue
            ba, bb = a.get("bucket_key") or "", b.get("bucket_key") or ""
            key = tuple(sorted([ba, bb]))
            if key in seen_pairs or ba == bb:
                continue
            seen_pairs.add(key)
            conf = classify_duplicate_pair(
                ba,
                bb,
                a.get("canonical_name") or "",
                b.get("canonical_name") or "",
                int(a.get("listing_count") or 0),
                int(b.get("listing_count") or 0),
            )
            if conf == "low":
                continue
            keep, other = (a, b) if int(a.get("listing_count") or 0) >= int(
                b.get("listing_count") or 0
            ) else (b, a)
            row = {
                "reason": "fuzzy_pair",
                "soft_a": sa,
                "soft_b": sb,
                "keep": {
                    "id": keep["id"],
                    "bucket_key": keep.get("bucket_key"),
                    "name": keep.get("canonical_name"),
                    "listings": keep.get("listing_count") or 0,
                },
                "merge": [
                    {
                        "id": other["id"],
                        "bucket_key": other.get("bucket_key"),
                        "name": other.get("canonical_name"),
                        "listings": other.get("listing_count") or 0,
                    }
                ],
                "confidence": conf,
            }
            if conf == "high":
                high.append(row)
            elif conf == "medium":
                medium.append(row)
            else:
                low.append(row)
        if pairs_checked > args.limit_pairs:
            break

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "projects_total": len(projects),
        "high_count": len(high),
        "medium_count": len(medium),
        "low_count": len(low),
        "high": high,
        "medium": medium,
        "low": low[:50],
    }
    (OUT_DIR / "audit_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # Human-readable medium checklist
    lines = ["# Medium duplicate candidates (need human decision)\n"]
    for i, g in enumerate(medium, 1):
        keep = g["keep"]
        merge = g["merge"][0]
        lines.append(
            f"{i}. KEEP `{keep['name']}` ({keep['listings']})  ←?  `{merge['name']}` ({merge['listings']})\n"
            f"   buckets: `{keep['bucket_key']}` vs `{merge['bucket_key']}`\n"
        )
    (OUT_DIR / "medium_review.md").write_text("".join(lines), encoding="utf-8")

    print(
        json.dumps(
            {
                "projects_total": len(projects),
                "high": len(high),
                "medium": len(medium),
                "report": str(OUT_DIR / "audit_report.json"),
                "medium_md": str(OUT_DIR / "medium_review.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
