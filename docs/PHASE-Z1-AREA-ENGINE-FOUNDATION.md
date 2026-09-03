# Phase Z1 — Area Engine Foundation

Phase Z1 builds the evidence foundation for marketplace area assignment without production apply.

## Scope

- Canonical coordinate evidence parser (`src/hub/coordinate_evidence.py`)
- Legacy token classification and evidence lineage (`src/hub/location_evidence.py`)
- Scoring engine v0.2 (`src/hub/area_assignment_engine.py`)
- Market area spatial seed v0.2 fixture (`data_fixtures/area_engine/market_area_spatial_seed_v0.2.json`)
- Owner Review read-only overlay (`src/hub/area_engine_overlay.py`)

## Project outcomes (mutually exclusive)

| Outcome | Meaning |
|---------|---------|
| `AUTO_SAFE` | Strong geographic + independent evidence |
| `OWNER_REVIEW_REQUIRED` | Owner should inspect |
| `AUTO_QUARANTINED` | Implausible — excluded from promotion without owner review |
| `NOT_EVALUABLE` | No usable coordinate |

## Scripts

```bash
python3 scripts/build_coordinate_evidence_inventory.py --output-dir /tmp/pantip-phase-z1-area-engine
python3 scripts/analyze_area_assignment_engine_v02.py --output-dir /tmp/pantip-phase-z1-area-engine
python3 scripts/test_phase_z1_area_engine_foundation.py
```

## Safety

- No production writes
- Phase W crosswalk immutable
- RealXtate read-only
