#!/usr/bin/env python3
"""Phase Z1 — area assignment engine v0.2 population dry run (READ-ONLY)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.area_assignment_engine import (  # noqa: E402
    OUTCOME_AUTO_QUARANTINED,
    OUTCOME_AUTO_SAFE,
    OUTCOME_NOT_EVALUABLE,
    OUTCOME_OWNER_REVIEW_REQUIRED,
    SUPPORT_IMPLAUSIBLE,
    SUPPORT_QUESTIONABLE,
    SUPPORT_SUPPORTED,
    coordinate_usable,
    evaluate_project,
    haversine_meters,
    load_area_seeds,
    load_project_contexts,
    load_stations,
)
from src.hub.location_evidence import measure_duplicate_lineage_problem

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
OUTPUT_DIR_DEFAULT = Path("/tmp/pantip-phase-z1-area-engine")

STRATIFIED_SAMPLE_IDS = [
    "ec5214c9-c9fb-5ca5-98fb-852703044e4a",  # Life Asoke Rama 9 — Rama 9
    "9782b822-d4db-5285-b5a7-87c89eec49a6",  # Life Asoke — Sukhumvit
    "03f2d9d3-b0b4-5fad-86ef-f9de7939cee2",  # THE BASE Phetchaburi-Thonglor
    "5e06d489-a116-5f78-87a4-1c3813aac70b",  # Aspire Sukhumvit 48 — On Nut corridor
    "cc3f0b19-843e-5479-a28d-bf2feb5c7ff9",  # The Diplomat Sathorn
    "f2fad7e4-abc9-5b62-ae23-f2d8bb42b86f",  # ATMOZ BANGNA
    ASPIRE_ONNUT_ID,
]


def discover_missing_area_candidates(crosswalk: list[dict], contexts: dict, seeds: list) -> list[dict]:
    from src.hub.location_evidence import MARKETPLACE_TOKENS, classify_location_token

    approved_keys = {s.identity_key for s in seeds if s.status == "EXISTING_APPROVED"}
    token_counts: Counter[str] = Counter()
    for ctx in contexts.values():
        for loc in ctx.listing_locations + ctx.pantip_zones:
            cls = classify_location_token(loc)
            if cls.marketplace_identity_key and cls.marketplace_identity_key not in approved_keys:
                token_counts[cls.marketplace_identity_key] += 1

    candidates = []
    seed_by_key = {s.identity_key: s for s in seeds}
    for key, count in token_counts.most_common(30):
        seed = seed_by_key.get(key)
        candidates.append(
            {
                "candidate_name_en": key.replace("_", " ").title(),
                "candidate_name_th": next((k for k, v in MARKETPLACE_TOKENS.items() if v == key), key),
                "identity_key": key,
                "semantic_kind": "MARKETPLACE_AREA",
                "supporting_project_count": count,
                "status": seed.status if seed else "NOT_IN_SEED",
                "recommendation": "REVIEW_REQUIRED" if seed and seed.status != "EXISTING_APPROVED" else "INSUFFICIENT_EVIDENCE",
                "confidence": "MEDIUM" if seed else "LOW",
            }
        )
    return candidates


def run_analysis(output_dir: Path, *, crosswalk_path: Path, trusted_db: Path, catalog_db: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    seeds = load_area_seeds(trusted_db)
    stations = load_stations(trusted_db)
    contexts = load_project_contexts(trusted_db, catalog_db, crosswalk)

    project_ids = [r.get("pantip_project_id") for r in crosswalk if r.get("pantip_project_id")]
    results = []
    outcome_counts = Counter()
    audit_counts = Counter()

    for pid in project_ids:
        ctx = contexts.get(pid)
        if not ctx:
            continue
        result = evaluate_project(ctx, seeds, stations)
        results.append(result)
        outcome = result.get("project_outcome") or result["classification"]
        outcome_counts[outcome] += 1
        for row in result.get("existing_assignment_audit", []):
            audit_counts[row["audit"]] += 1

    total = len(project_ids)
    coord_usable = sum(1 for pid in project_ids if contexts.get(pid) and coordinate_usable(contexts[pid]))

    lineage_stats = measure_duplicate_lineage_problem(
        [
            {
                "pantip_zones": contexts[pid].pantip_zones,
                "listing_locations": contexts[pid].listing_locations,
            }
            for pid in project_ids
            if pid in contexts
        ]
    )

    aspire = contexts.get(ASPIRE_ONNUT_ID)
    aspire_eval = evaluate_project(aspire, seeds, stations) if aspire else {}
    aspire_focus = evaluate_project(
        aspire,
        seeds,
        stations,
        candidate_keys=["onnut", "charoen_nakhon", "khlong_toei", "suan_luang", "phatthanakan"],
    ) if aspire else {}

    stratified = []
    for pid in STRATIFIED_SAMPLE_IDS:
        ctx = contexts.get(pid)
        if not ctx:
            continue
        stratified.append({"project_id": pid, **evaluate_project(ctx, seeds, stations)})

    missing_candidates = discover_missing_area_candidates(crosswalk, contexts, seeds)

    z0_comparison = {
        "Z0": {
            "AUTO_SAFE": 51,
            "REVIEW": 810,
            "REJECT_QUARANTINE": 217,
            "NOT_EVALUABLE": 1097,
        },
        "Z1": {
            OUTCOME_AUTO_SAFE: outcome_counts[OUTCOME_AUTO_SAFE],
            OUTCOME_OWNER_REVIEW_REQUIRED: outcome_counts[OUTCOME_OWNER_REVIEW_REQUIRED],
            OUTCOME_AUTO_QUARANTINED: outcome_counts[OUTCOME_AUTO_QUARANTINED],
            OUTCOME_NOT_EVALUABLE: outcome_counts[OUTCOME_NOT_EVALUABLE],
        },
        "notes": [
            "Z1 separates owner review from auto-quarantine",
            "Z1 fixes coordinate parser (latitude/longitude)",
            "Z1 adds lineage de-duplication",
        ],
    }

    owner_review = outcome_counts[OUTCOME_OWNER_REVIEW_REQUIRED]
    auto_safe = outcome_counts[OUTCOME_AUTO_SAFE]
    auto_quarantine = outcome_counts[OUTCOME_AUTO_QUARANTINED]
    not_eval = outcome_counts[OUTCOME_NOT_EVALUABLE]

    summary = {
        "phase": "Z1",
        "total_projects": total,
        "COORDINATE_USABLE": coord_usable,
        "COORDINATE_MISSING": total - coord_usable,
        "outcomes": dict(outcome_counts),
        OUTCOME_AUTO_SAFE: auto_safe,
        OUTCOME_OWNER_REVIEW_REQUIRED: owner_review,
        OUTCOME_AUTO_QUARANTINED: auto_quarantine,
        OUTCOME_NOT_EVALUABLE: not_eval,
        "auto_safe_rate": round(100 * auto_safe / total, 2) if total else 0,
        "owner_review_rate": round(100 * owner_review / total, 2) if total else 0,
        "auto_quarantine_rate": round(100 * auto_quarantine / total, 2) if total else 0,
        "not_evaluable_rate": round(100 * not_eval / total, 2) if total else 0,
        "owner_workload": {
            "owner_review_required": owner_review,
            "auto_quarantined_not_owner_work": auto_quarantine,
            "auto_safe": auto_safe,
            "not_evaluable_needs_evidence": not_eval,
        },
        "existing_assignment_audit": dict(audit_counts),
        "legacy_lineage_duplicate": lineage_stats,
        "z0_vs_z1": z0_comparison,
        "aspire_onnut": {
            "project_id": ASPIRE_ONNUT_ID,
            "evaluation": aspire_eval,
            "focus_candidates": aspire_focus.get("candidate_evaluations", []),
        },
        "stratified_validation": stratified,
        "missing_area_candidates": missing_candidates[:20],
        "market_area_master": {
            "approved": sum(1 for s in seeds if s.status == "EXISTING_APPROVED"),
            "candidates": sum(1 for s in seeds if s.status != "EXISTING_APPROVED"),
            "total_fixture": len(seeds),
        },
        "transit_master": {
            "stations_total": len(stations),
            "stations_with_coordinates": len(stations),
        },
    }

    (output_dir / "area-engine-summary-v02.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "project-area-candidates-v02.json").write_text(
        json.dumps(results, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    conflicts = []
    for row in results:
        for audit in row.get("existing_assignment_audit", []):
            if audit["audit"] in {SUPPORT_IMPLAUSIBLE, SUPPORT_QUESTIONABLE}:
                conflicts.append({"project_id": row["project_id"], "project_name": row["project_name"], **audit})

    (output_dir / "assignment-conflicts-v02.json").write_text(
        json.dumps(conflicts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with (output_dir / "owner-review-required.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["project_id", "project_name", "project_outcome", "coordinate_tier"])
        writer.writeheader()
        for row in results:
            if row.get("project_outcome") == OUTCOME_OWNER_REVIEW_REQUIRED:
                writer.writerow(
                    {
                        "project_id": row["project_id"],
                        "project_name": row["project_name"],
                        "project_outcome": row["project_outcome"],
                        "coordinate_tier": row.get("coordinate_tier"),
                    }
                )

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase Z1 area assignment engine v0.2 dry run")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR_DEFAULT)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_PHASE_W)
    parser.add_argument("--trusted-db", type=Path, default=DEFAULT_TRUSTED)
    parser.add_argument("--catalog-db", type=Path, default=DEFAULT_CATALOG)
    args = parser.parse_args()
    if not args.crosswalk.is_file():
        raise SystemExit(f"Crosswalk not found: {args.crosswalk}")
    if not args.trusted_db.is_file():
        raise SystemExit(f"Trusted DB not found: {args.trusted_db}")
    summary = run_analysis(
        args.output_dir, crosswalk_path=args.crosswalk, trusted_db=args.trusted_db, catalog_db=args.catalog_db
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
