# Shared Canonical Master v0.1

Phase Z3 defines the first explicit **Shared Canonical Master** contract between Pantip and RealXtate.

## Three data layers

1. **Shared Canonical Knowledge** — project master, area/group/corridor, transit, admin geography, coordinates, aliases
2. **Product-Specific Data** — Pantip/RealXtate listings, pricing, contact, display caches
3. **Historical / Raw Evidence** — employee sheet values, legacy zone bags, imported tokens

## Architecture

```
SHARED CANONICAL MASTER (versioned JSON/SQLite artifact)
        ↓ explicit promotion
Pantip local runtime          RealXtate local runtime
```

No bidirectional live sync. No network microservice at current scale.

## Modules

- `src/hub/shared_master/schema.py` — entity types, readiness statuses
- `src/hub/shared_master/project_contract.py` — cross-product project contract
- `src/hub/shared_master/area_contract.py` — area taxonomy and semantic reviews
- `src/hub/shared_master/source_authority.py` — T1–T5 source tiers
- `src/hub/shared_master/readiness.py` — per-field promotion readiness

## Canonical project ID

Reuse stable shared UUID (`canonical_project_id` = Pantip ID = RealXtate ID for 2,156 EXACT_ID_MATCH projects). Do not invent a third namespace.

## Export boundary (future)

- `shared-project-master.json`
- `shared-area-master.json`
- `shared-transit-master.json`
- `shared-admin-master.json`
