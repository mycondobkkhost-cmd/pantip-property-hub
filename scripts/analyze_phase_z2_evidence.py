#!/usr/bin/env python3
"""Phase Z2 — evidence acquisition analysis and engine rerun."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.area_assignment_engine import (
    OUTCOME_AUTO_QUARANTINED,
    OUTCOME_AUTO_SAFE,
    OUTCOME_NOT_EVALUABLE,
    OUTCOME_OWNER_REVIEW_REQUIRED,
    evaluate_project,
    load_area_seeds,
    load_project_contexts,
    load_stations,
)
from src.hub.area_candidate_evidence import build_all_candidate_packets, discover_other_candidates
from src.hub.coordinate_acquisition import (
    acquire_for_entry,
    apply_acquired_to_context,
    build_missing_coordinate_queue,
)
from src.hub.population_accounting import reconcile_population

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
DEFAULT_OUT = Path("/tmp/pantip-phase-z2-evidence")
ASPIRE_ID = "d9a5d2b2-355a-55e6-b471-773b9badc8c6"
Z1_BASELINE = {
    OUTCOME_AUTO_SAFE: 27,
    OUTCOME_OWNER_REVIEW_REQUIRED: 621,
    OUTCOME_AUTO_QUARANTINED: 430,
    OUTCOME_NOT_EVALUABLE: 1097,
}


def run_analysis(
    output_dir: Path,
    *,
    fetch_public: bool = False,
    batch_limit: int = 100,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "area-candidates").mkdir(exist_ok=True)

    pop = reconcile_population()
    crosswalk = json.loads(DEFAULT_PHASE_W.read_text(encoding="utf-8"))
    seeds = load_area_seeds(DEFAULT_TRUSTED)
    stations = load_stations(DEFAULT_TRUSTED)
    contexts = load_project_contexts(DEFAULT_TRUSTED, DEFAULT_CATALOG, crosswalk)

    # Z1 baseline run
    z1_outcomes: dict[str, str] = {}
    for pid, ctx in contexts.items():
        r = evaluate_project(ctx, seeds, stations)
        z1_outcomes[pid] = r.get("project_outcome") or r["classification"]

    queue = build_missing_coordinate_queue(z1_outcomes=z1_outcomes)
    (output_dir / "missing-coordinate-queue.json").write_text(
        json.dumps([e.to_dict() for e in queue], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    acquisition_map: dict[str, object] = {}
    public_requests = 0
    for entry in queue:
        do_fetch = fetch_public and public_requests < batch_limit and entry.known_reference_urls
        if do_fetch:
            public_requests += 1
        acq = acquire_for_entry(entry, trusted_db=DEFAULT_TRUSTED, fetch_public=do_fetch)
        acquisition_map[entry.project_id] = acq

    # Rerun with acquired overlay
    z2_outcomes: dict[str, str] = {}
    transitions: Counter[str] = Counter()
    for pid, ctx in contexts.items():
        acq = acquisition_map.get(pid)
        if acq:
            apply_acquired_to_context(ctx, acq)
        r = evaluate_project(ctx, seeds, stations)
        z2 = r.get("project_outcome") or r["classification"]
        z2_outcomes[pid] = z2
        z1 = z1_outcomes.get(pid, "")
        if z1 != z2:
            transitions[f"{z1}->{z2}"] += 1

    z2_counts = Counter(z2_outcomes.values())
    acq_outcomes = Counter(a.outcome for a in acquisition_map.values())  # type: ignore[union-attr]

    # Area candidate packets
    packets = build_all_candidate_packets()
    for key, packet in packets.items():
        (output_dir / "area-candidates" / f"{key}.json").write_text(
            json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    area_review_count = sum(
        1 for p in packets.values() if p.get("area_state") == "READY_FOR_OWNER_REVIEW"
    )

    aspire = evaluate_project(contexts[ASPIRE_ID], seeds, stations)

    summary = {
        "phase": "Z2",
        "population": pop.to_dict(),
        "queue": {
            "total": len(queue),
            "P0": sum(1 for e in queue if e.priority_band == "P0"),
            "P1": sum(1 for e in queue if e.priority_band == "P1"),
            "P2": sum(1 for e in queue if e.priority_band == "P2"),
            "P3": sum(1 for e in queue if e.priority_band == "P3"),
            "with_reference_urls": sum(1 for e in queue if e.known_reference_urls),
        },
        "acquisition": {
            "outcomes": dict(acq_outcomes),
            "public_request_count": public_requests,
            "recovered_trusted": acq_outcomes.get("RECOVERED_TRUSTED", 0),
            "recovered_corroborated": acq_outcomes.get("RECOVERED_CORROBORATED", 0),
            "candidate_single_source": acq_outcomes.get("CANDIDATE_SINGLE_SOURCE", 0),
            "conflict": acq_outcomes.get("COORDINATE_CONFLICT", 0),
            "no_evidence": acq_outcomes.get("NO_EVIDENCE_FOUND", 0),
        },
        "z1_baseline": Z1_BASELINE,
        "z2_outcomes": dict(z2_counts),
        "transitions": dict(transitions),
        "owner_workload": {
            "project_owner_review": z2_counts.get(OUTCOME_OWNER_REVIEW_REQUIRED, 0),
            "area_definition_owner_review": area_review_count,
            "evidence_acquisition_backlog": acq_outcomes.get("CANDIDATE_SINGLE_SOURCE", 0)
            + acq_outcomes.get("NO_EVIDENCE_FOUND", 0),
        },
        "aspire_onnut": aspire,
        "other_area_candidates": discover_other_candidates(15),
        "coordinate_coverage": {
            "usable_before": pop.coord_usable,
            "usable_after_z2": pop.coord_usable
            + acq_outcomes.get("RECOVERED_TRUSTED", 0)
            + acq_outcomes.get("RECOVERED_CORROBORATED", 0),
            "candidate_t4_added": acq_outcomes.get("CANDIDATE_SINGLE_SOURCE", 0),
        },
    }

    (output_dir / "phase-z2-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "acquisition-results.json").write_text(
        json.dumps([a.to_dict() for a in acquisition_map.values()], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase Z2 evidence analysis")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--fetch-public", action="store_true")
    parser.add_argument("--batch-limit", type=int, default=100)
    args = parser.parse_args()
    summary = run_analysis(args.output_dir, fetch_public=args.fetch_public, batch_limit=args.batch_limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
