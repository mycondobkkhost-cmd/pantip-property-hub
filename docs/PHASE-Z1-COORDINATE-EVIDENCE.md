# Phase Z1 — Coordinate Evidence

## Bug fixed (Phase W / Z0)

Phase W `load_coordinate_states()` checked `coord.lat` while RealXtate schema uses `latitude` / `longitude`. This misclassified ~1,078 accepted pins as `COORD_CONFLICT`.

## Normalized schema

```json
{
  "project_id": "...",
  "latitude": 13.7,
  "longitude": 100.6,
  "source": "project_master_v01",
  "evidence_tier": "T2_COORD",
  "coordinate_state": "CANDIDATE",
  "evidence": [],
  "conflicts": []
}
```

## Tiers

| Tier | Meaning | AUTO_SAFE |
|------|---------|-----------|
| T1 | Owner-verified | Yes (with other evidence) |
| T2 | Trusted reference pin | Yes (with other evidence) |
| T3 | Two+ sources agree ≤50m | Yes (with other evidence) |
| T4 | Single candidate | Evaluable, not AUTO_SAFE alone |
| T5 | Invalid/uncertain | No |

## Quality checks

- Invalid range / zero coordinates
- Outside Thailand / Bangkok metro bbox flag
- Duplicate pin clusters (informational — same-building may share)
- Source conflicts >500m

Outputs: `/tmp/pantip-phase-z1-area-engine/coordinate-evidence-summary.json`
