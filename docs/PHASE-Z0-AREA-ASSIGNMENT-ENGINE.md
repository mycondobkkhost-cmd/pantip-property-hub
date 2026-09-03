# Phase Z0 — Evidence-Based Area Assignment Engine

## Problem statement

~2,175 LIVE Pantip projects need marketplace area classification. Manual review of 153+ queue items does not scale. Existing RealXtate 8z3 assignments are useful **reference evidence** but contain geographically implausible EDGE assignments driven by legacy zone bags (see Aspire Onnut → Charoen Nakhon).

## Current failure mode

1. Employee sheet copies multi-zone bags into Pantip/catalog.
2. 8z3 treats bag tokens as `catalog_listing_bag` evidence.
3. LOW/EDGE slots fill to max 3 without distance veto.
4. Owner review surfaces weak assignments alongside strong PRIMARY.

## Source hierarchy (conservative)

| Tier | Source | AUTO_SAFE eligible? |
|---|---|---|
| T1 | Verified owner decision / verified coordinate | YES (with corroboration) |
| T2 | Trusted deterministic geographic reference (pins, transit anchors) | YES (with corroboration) |
| T3 | Multiple agreeing independent internal sources | REVIEW only |
| T4 | Employee sheet zone bags | NEVER alone |
| T5 | Fuzzy/name inference | NEVER alone |

Existing RealXtate assignment tier depends on evidence families: HIGH+coordinate = T2/T3; LOW+catalog_listing_bag only = T4/T5.

## Prototype architecture

```
ProjectContext (coordinate, listing bag, pantip zones)
        ↓
AreaSeed (31 approved marketplace areas + station anchors)
        ↓
evaluate_area() — explainable evidence scoring
        ↓
pick_output_areas() — 0–3 relations, no forced filler
        ↓
Classification: AUTO_SAFE | REVIEW | REJECT_QUARANTINE | NOT_EVALUABLE
```

## Evidence dimensions

| Code | Description |
|---|---|
| A | PROJECT_COORDINATE (straight-line distance to area anchor) |
| B | AREA_SPATIAL_DISTANCE (CORE ≤1000m, EXTENDED ≤2200m) |
| C | ADMIN_GEOGRAPHY_COMPATIBILITY (zone token — weak) |
| D | TRANSIT_COMPATIBILITY (nearest station alignment) |
| E | AREA_ADJACENCY (seed-declared neighbors) |
| F | CORRIDOR_RELATIONSHIP (road anchors — future) |
| G | VERIFIED_OWNER_DECISION (future) |
| H | EXISTING_REALXTATE_ASSIGNMENT (small weight only) |

**H alone cannot AUTO_SAFE.**

## Scoring weights (prototype v0)

| Rule | Weight |
|---|---|
| coordinate_core (≤1000m) | +40 |
| coordinate_extended (≤2200m) | +20 |
| distance beyond extended | -35 |
| weak-only + far | -25 |
| name_branding | +8 |
| catalog_listing_bag | +3 |
| admin zone token | +2 |
| existing_rx_high/med/low | +5/+3/+1 |

## Classification rules

### AUTO_SAFE
- Coordinate usable (T2 pin)
- Straight-line distance ≤ CORE (1000m)
- ≥2 independent evidence families including coordinate
- No major geographic contradiction

### REVIEW
- Partial evidence, borderline distance, competing areas, missing coordinate, or mixed signals

### REJECT_QUARANTINE
- Coordinate available but straight-line distance > EXTENDED (2200m) without geographic evidence
- Weak-only far assignments (catalog bag contamination pattern)
- Does **not** delete production data

### NOT_EVALUABLE
- No usable coordinate — fail conservative to REVIEW queue, not AUTO_SAFE

## Multi-area output

Preserves `marketplace_area_relations[]` max 3 with roles PRIMARY/SECONDARY/EDGE. Valid outputs: 1, 2, or 3 areas. **No forced third slot.**

## Admin geography

Admin district/subdistrict remains separate semantic dimension. Zone tokens may provide weak evidence or veto checks but must not flatten into marketplace area identity.

## Transit master

Use straight-line distance to station anchors. Never label haversine as walking distance.

## Adjacency graph

Versioned edges from `market_area_seed_8z2b.adjacent_json` only — provenance required. Example: On Nut ↔ Phra Khanong (seed-declared). No name-sound inference.

## Future apply boundary

```
DISCOVER → SCORE → CLASSIFY → REVIEW → OWNER APPROVAL → PROMOTION CANDIDATE → SEPARATE APPLY PHASE
```

Z0 implements DISCOVER + SCORE + CLASSIFY prototype only.

## Implementation

- Module: `src/hub/area_assignment_engine.py`
- Analysis: `scripts/analyze_area_assignment_engine.py`
- Output: `/tmp/pantip-phase-z0-area-engine/` (local only, not committed)

## Aspire Onnut regression policy

Case used for validation only. **No project-name or Charoen Nakhon blacklist hard-coding.**

## Z1 readiness criteria

- Coordinate coverage >50% (met for CANDIDATE pins)
- Implausible assignment detector proven on real cases (met)
- AUTO_SAFE precision-first threshold validated (partial — only 51/2175 at current evidence)
- Additional approved areas (Suan Luang, Pattanakarn) need seed research before automation expands
