#!/usr/bin/env python3
"""Phase Z1 — build coordinate evidence inventory (READ-ONLY)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.coordinate_evidence import (  # noqa: E402
    legacy_phase_w_coordinate_class,
    load_coordinate_inventory,
    summarize_inventory,
)

DEFAULT_PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
DEFAULT_TRUSTED = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-trusted-master.sqlite"
)


def _legacy_before_counts(crosswalk: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {"COORD_VERIFIED_REFERENCE_AVAILABLE": 0, "COORD_CANDIDATE_REFERENCE_AVAILABLE": 0, "COORD_MISSING": 0, "COORD_CONFLICT": 0}
    for row in crosswalk:
        label = row.get("coordinate_state") or "COORD_MISSING"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _recompute_before_from_payload(trusted_db: Path, project_ids: list[str]) -> dict[str, int]:
    import sqlite3

    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    cur = conn.cursor()
    counts: dict[str, int] = {}
    wanted = set(project_ids)
    for project_id, payload in cur.execute("SELECT project_id, payload_json FROM project_master_v01"):
        if project_id not in wanted:
            continue
        body = json.loads(payload or "{}")
        label = legacy_phase_w_coordinate_class(body.get("coordinate") or {})
        counts[label] = counts.get(label, 0) + 1
    conn.close()
    return counts


def run(output_dir: Path, *, crosswalk_path: Path, trusted_db: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    project_ids = [r["pantip_project_id"] for r in crosswalk if r.get("pantip_project_id")]

    inventory = load_coordinate_inventory(trusted_db, project_ids)
    summary = summarize_inventory(inventory)

    before_legacy = _legacy_before_counts(crosswalk)
    before_parser = _recompute_before_from_payload(trusted_db, project_ids)
    before_usable = before_parser.get("COORD_VERIFIED_REFERENCE_AVAILABLE", 0) + before_parser.get(
        "COORD_CANDIDATE_REFERENCE_AVAILABLE", 0
    )
    after_usable = summary["coordinate_usable"]
    after_evaluable = sum(
        1
        for ev in inventory.values()
        if ev.latitude is not None and ev.longitude is not None and ev.evidence_tier != "T5_COORD"
    )

    conflicts = []
    for ev in inventory.values():
        if ev.conflicts:
            conflicts.append(ev.to_dict())

    suspicious = []
    for cluster in summary.get("top_duplicate_clusters") or []:
        if cluster["project_count"] >= 5:
            suspicious.append(cluster)

    coverage = {
        "coverage_before": {
            "usable_legacy_parser": before_usable,
            "usable_pct": round(100 * before_usable / len(project_ids), 2) if project_ids else 0,
            "phase_w_labels": before_legacy,
            "legacy_parser_labels": before_parser,
        },
        "coverage_after": {
            "usable_t1_t3": after_usable,
            "evaluable_t1_t4": after_evaluable,
            "usable_pct": summary["coordinate_usable_pct"],
            "evaluable_pct": round(100 * after_evaluable / len(project_ids), 2) if project_ids else 0,
            "tier_counts": summary["tier_counts"],
            "state_counts": summary["state_counts"],
        },
        "coverage_gain": {
            "usable_delta": after_usable - before_usable,
            "evaluable_delta": after_evaluable - before_usable,
        },
    }

    acquisition = {
        "A_recoverable_local": summary["state_counts"].get("MISSING", 0),
        "B_url_reference_parse": 0,
        "C_external_geocoding_later": summary["state_counts"].get("MISSING", 0),
        "D_owner_manual": summary["state_counts"].get("CONFLICT", 0) + summary["state_counts"].get("INVALID", 0),
    }

    report = {
        "phase": "Z1",
        "total_projects": len(project_ids),
        **summary,
        **coverage,
        "acquisition_plan": acquisition,
    }

    (output_dir / "coordinate-evidence-summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "coordinate-inventory.json").write_text(
        json.dumps({k: v.to_dict() for k, v in inventory.items()}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with (output_dir / "coordinate-conflicts.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["project_id", "latitude", "longitude", "evidence_tier", "coordinate_state", "conflicts"],
        )
        writer.writeheader()
        for row in conflicts:
            writer.writerow(
                {
                    "project_id": row["project_id"],
                    "latitude": row.get("latitude"),
                    "longitude": row.get("longitude"),
                    "evidence_tier": row.get("evidence_tier"),
                    "coordinate_state": row.get("coordinate_state"),
                    "conflicts": ";".join(row.get("conflicts") or []),
                }
            )

    with (output_dir / "suspicious-coordinate-clusters.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["coordinate", "project_count", "sample_project_ids"])
        writer.writeheader()
        for row in suspicious:
            writer.writerow(
                {
                    "coordinate": row["coordinate"],
                    "project_count": row["project_count"],
                    "sample_project_ids": ";".join(row.get("project_ids") or []),
                }
            )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase Z1 coordinate evidence inventory")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_PHASE_W)
    parser.add_argument("--trusted-db", type=Path, default=DEFAULT_TRUSTED)
    args = parser.parse_args()
    if not args.crosswalk.is_file():
        raise SystemExit(f"Crosswalk not found: {args.crosswalk}")
    if not args.trusted_db.is_file():
        raise SystemExit(f"Trusted DB not found: {args.trusted_db}")
    report = run(args.output_dir, crosswalk_path=args.crosswalk, trusted_db=args.trusted_db)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
