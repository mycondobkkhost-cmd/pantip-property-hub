# Phase Z2 — Evidence Acquisition

Phase Z2 builds a deterministic coordinate evidence acquisition pipeline without production apply.

## Pipeline

1. Authoritative population reconciliation (2,175 LIVE projects)
2. Missing-coordinate queue with P0–P3 prioritization
3. Local-first recovery (propertyhub acquisition, location profile, location facts, projects.json URLs)
4. Bounded public reference fetch (≤100 high-priority, respectful rate)
5. Cross-source agreement (75m / 250m thresholds)
6. Area candidate evidence packets (Suan Luang, Pattanakarn, Rama 9)
7. Engine v0.2 rerun with acquired overlay (T4 candidates do not inflate AUTO_SAFE)

## Scripts

```bash
python3 scripts/build_coordinate_acquisition_queue.py
python3 scripts/acquire_coordinate_evidence.py --fetch-public --batch-limit 100
python3 scripts/analyze_phase_z2_evidence.py --fetch-public --batch-limit 100
python3 scripts/test_phase_z2_evidence_acquisition.py
```

Outputs: `/tmp/pantip-phase-z2-evidence/`

## Safety

- No production writes
- No paid geocoding APIs
- Single-source coordinates remain T4 candidates
- Identity-ambiguous projects blocked from automatic acquisition
