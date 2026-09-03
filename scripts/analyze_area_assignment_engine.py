#!/usr/bin/env python3
"""Phase Z0 — evidence-based area assignment engine discovery analysis.

READ-ONLY. Never mutates inputs or production data.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.area_assignment_engine import (
    CLASS_AUTO_SAFE,
    CLASS_NOT_EVALUABLE,
    CLASS_REJECT_QUARANTINE,
    CLASS_REVIEW,
    SUPPORT_IMPLAUSIBLE,
    SUPPORT_QUESTIONABLE,
    SUPPORT_SUPPORTED,
    SUPPORT_UNSUPPORTED,
    ProjectContext,
    coordinate_usable,
    evaluate_project,
    haversine_meters,
    load_area_seeds,
    load_project_contexts,
    load_stations,
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
DEFAULT_CATALOG = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-catalog.sqlite"
)
ASPIRE_ONNUT_ID = "d9a5d2b2-355a-55e6-b471-773b9badc8c6"


def nearest_transit_report(lat: float, lon: float, stations: dict) -> list[dict]:
    rows = []
    for st in stations.values():
        m = haversine_meters(lat, lon, st.latitude, st.longitude)
        rows.append({"station_id": st.station_id, "name_th": st.name_th, "line": st.line, "straight_line_meters": int(m)})
    rows.sort(key=lambda r: r["straight_line_meters"])
    return rows[:8]


def build_adjacency_graph(seeds) -> dict:
    graph: dict[str, list[dict]] = {}
    by_key = {s.identity_key: s for s in seeds}
    for seed in seeds:
        edges = []
        for adj in seed.adjacent_keys:
            target = by_key.get(adj)
            if target:
                edges.append(
                    {
                        "to_identity_key": adj,
                        "to_area_id": target.area_id,
                        "to_name_th": target.name_th,
                        "relation": "DIRECT_NEIGHBOR",
                        "source": "market_area_seed_8z2b.adjacent_json",
                        "confidence": "SEED_DECLARED",
                    }
                )
        graph[seed.identity_key] = edges
    return graph


def run_analysis(output_dir: Path, *, crosswalk_path: Path, trusted_db: Path, catalog_db: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    seeds = load_area_seeds(trusted_db)
    stations = load_stations(trusted_db)
    contexts = load_project_contexts(trusted_db, catalog_db, crosswalk)

    # Population keyed by Phase W LIVE project ids.
    project_ids = [r.get("pantip_project_id") for r in crosswalk if r.get("pantip_project_id")]
    results = []
    class_counts = Counter()
    audit_counts = Counter()
    evaluable = 0

    for pid in project_ids:
        ctx = contexts.get(pid)
        if not ctx:
            continue
        result = evaluate_project(ctx, seeds, stations)
        results.append(result)
        class_counts[result["classification"]] += 1
        if result["coordinate_usable"]:
            evaluable += 1
        for row in result["existing_assignment_audit"]:
            audit_counts[row["audit"]] += 1

    # Aspire Onnut deep dive.
    aspire = contexts.get(ASPIRE_ONNUT_ID)
    aspire_eval = evaluate_project(aspire, seeds, stations) if aspire else {}
    aspire_candidates = evaluate_project(
        aspire,
        seeds,
        stations,
        candidate_keys=["onnut", "charoen_nakhon", "khlong_toei", "suan_luang", "pattanakarn"],
    ) if aspire else {}

    nearest_transit = []
    if aspire and aspire.latitude and aspire.longitude:
        nearest_transit = nearest_transit_report(aspire.latitude, aspire.longitude, stations)

    # Negative control: same coordinate, inject far area token in listing bag only.
    negative = None
    if aspire:
        neg_ctx = ProjectContext(
            project_id="TEST_ONLY_NEGATIVE_CONTROL",
            name=aspire.name,
            latitude=aspire.latitude,
            longitude=aspire.longitude,
            coordinate_state=aspire.coordinate_state,
            acceptance_status=aspire.acceptance_status,
            listing_locations=["เจริญนคร"],
            listing_transit=[],
            pantip_zones=[],
            existing_assignments=[],
        )
        charoen = next(s for s in seeds if s.identity_key == "charoen_nakhon")
        from src.hub.area_assignment_engine import evaluate_area

        negative = evaluate_area(neg_ctx, charoen, stations)

    # Positive control: Life Asoke Rama 9 if present.
    positive = None
    life_pid = "ec5214c9-c9fb-5ca5-98fb-852703044e4a"
    life_ctx = contexts.get(life_pid)
    if life_ctx:
        positive = evaluate_project(life_ctx, seeds, stations)

    total = len(project_ids)
    auto_safe = class_counts[CLASS_AUTO_SAFE]
    review = class_counts[CLASS_REVIEW]
    reject = class_counts[CLASS_REJECT_QUARANTINE]
    not_eval = class_counts[CLASS_NOT_EVALUABLE]

    manual_before = total
    manual_after = review + reject
    reduction = round(100 * (1 - manual_after / manual_before), 1) if manual_before else 0.0

    summary = {
        "phase": "Z0",
        "total_projects": total,
        "projects_evaluable": evaluable,
        "projects_not_evaluable": not_eval,
        "classification": {
            CLASS_AUTO_SAFE: auto_safe,
            CLASS_REVIEW: review,
            CLASS_REJECT_QUARANTINE: reject,
            CLASS_NOT_EVALUABLE: not_eval,
        },
        "existing_assignment_audit": dict(audit_counts),
        "owner_workload_estimate": {
            "manual_reviews_without_engine": manual_before,
            "manual_reviews_with_engine": manual_after,
            "auto_safe": auto_safe,
            "manual_review_reduction_percent": reduction,
        },
        "aspire_onnut_station": {
            "project_id": ASPIRE_ONNUT_ID,
            "nearest_transit": nearest_transit,
            "evaluation": aspire_eval,
            "candidate_focus": aspire_candidates.get("candidate_evaluations", []),
        },
        "negative_control": {
            "classification": negative.classification if negative else None,
            "contradictions": negative.contradictions if negative else [],
            "score": negative.score if negative else None,
        },
        "positive_control": {
            "project_id": life_pid,
            "classification": positive.get("classification") if positive else None,
            "picked_areas": positive.get("picked_areas") if positive else [],
        },
        "market_area_spatial": {
            "approved_count": len(seeds),
            "spatial_strong": sum(1 for s in seeds if s.station_ids and s.adjacent_keys),
            "spatial_partial": sum(1 for s in seeds if (s.station_ids or s.road_ids) and not (s.station_ids and s.adjacent_keys)),
        },
        "transit_master": {
            "stations_total": len(stations),
            "stations_with_coordinates": len(stations),
        },
        "coordinate_inventory": {
            "project_master_total": len(contexts),
            "coordinates_accepted": sum(1 for c in contexts.values() if coordinate_usable(c)),
            "coordinates_missing": sum(1 for c in contexts.values() if not coordinate_usable(c)),
        },
        "adjacency_graph_nodes": len(build_adjacency_graph(seeds)),
    }

    (output_dir / "area-engine-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "project-area-candidates.json").write_text(
        json.dumps(results, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "area-adjacency-graph.json").write_text(
        json.dumps(build_adjacency_graph(seeds), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    conflicts = []
    unsupported = []
    review_sample = []
    for row in results:
        for audit in row.get("existing_assignment_audit", []):
            if audit["audit"] in {SUPPORT_IMPLAUSIBLE, SUPPORT_QUESTIONABLE}:
                conflicts.append(
                    {
                        "project_id": row["project_id"],
                        "project_name": row["project_name"],
                        **audit,
                    }
                )
            if audit["audit"] == SUPPORT_IMPLAUSIBLE:
                unsupported.append(
                    {
                        "project_id": row["project_id"],
                        "project_name": row["project_name"],
                        **audit,
                    }
                )
        if row["classification"] == CLASS_REVIEW:
            review_sample.append(
                {
                    "project_id": row["project_id"],
                    "project_name": row["project_name"],
                    "classification": row["classification"],
                    "picked_areas": row["picked_areas"],
                }
            )

    (output_dir / "assignment-conflicts.json").write_text(
        json.dumps(conflicts, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with (output_dir / "unsupported-assignments.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "project_id",
                "project_name",
                "area_id",
                "name_th",
                "existing_role",
                "existing_confidence",
                "audit",
                "straight_line_meters",
            ],
        )
        writer.writeheader()
        for row in unsupported:
            writer.writerow({k: row.get(k) for k in writer.fieldnames})

    with (output_dir / "review-sample.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["project_id", "project_name", "classification", "picked_areas"])
        writer.writeheader()
        for row in review_sample[:200]:
            writer.writerow(row)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase Z0 area assignment engine discovery")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_PHASE_W)
    parser.add_argument("--trusted-db", type=Path, default=DEFAULT_TRUSTED)
    parser.add_argument("--catalog-db", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()

    if not args.crosswalk.is_file():
        raise SystemExit(f"Crosswalk not found: {args.crosswalk}")
    if not args.trusted_db.is_file():
        raise SystemExit(f"Trusted DB not found: {args.trusted_db}")

    summary = run_analysis(args.output_dir, crosswalk_path=args.crosswalk, trusted_db=args.trusted_db, catalog_db=args.catalog_db)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
