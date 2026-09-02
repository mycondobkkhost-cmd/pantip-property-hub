# Repository & Data Separation

Goal: keep **application code** separate from **runtime catalog data** so commits and code review stay safe.

## What belongs where

### CODE WORK (commit these)

```
src/
scripts/          # except local-only generated .command/.bat
hub/preview.html
hub/co/
config/
docs/
tests/            # scripts/test_*.py
fly.toml
Dockerfile
requirements*.txt
data_seed/        # synthetic dev fixtures only (Phase C)
```

### RUNTIME DATA (do not commit routine changes)

```
data/properties.json      ← production SoT on Fly
data/projects.json        ← production SoT on Fly
data/*_queue.json
data/customer_cases.json
data/*.csv exports
```

Use `DATA_DIR` / `/app/data` on Fly. Locally: `data/` in the repo folder.

### DERIVED (regenerable)

```
data/preview-data.js
data/hub.db
data/hub_overview_export.csv
hub/preview-data.js       # legacy mirror
```

### SECRETS (never commit)

```
.env
credentials/
cookies/
```

## Safe Git workflow

### Before commit

```bash
git status --short
git diff --stat
```

**Review the diff.** If you see `data/properties.json` or `data/projects.json` with thousands of lines, that is **runtime data**, not a feature commit.

### Prefer selective add

```bash
# Good: code only
git add src/ scripts/hub_server.py hub/preview.html docs/

# Dangerous
git add -A
```

### Staging checklist

- [ ] No accidental `data/properties.json` / `data/projects.json` unless an **approved data migration**
- [ ] No `.env` or `credentials/`
- [ ] No `logs/` or `*_cache/`

## Why runtime data is still tracked today

Historical deploys committed catalog JSON so Docker `data_seed/` and new environments had data.

**Removing from Git** requires a controlled migration (see `docs/RUNTIME-DATA-MIGRATION.md`). Do **not** bulk `git rm` without backup and seed plan.

## Docker / Fly seed model (current)

| Stage | Path | Behavior |
|-------|------|----------|
| Image build | `/app/data_seed/` | Synthetic fixtures copied at build (Phase C) |
| Container start | `cp -an data_seed → data` | Fill **missing** files only |
| Fly volume | `/app/data/` | **Authoritative** after first run |

`data_seed/` contains synthetic properties/projects for dev bootstrap — not a copy of production runtime data.

## Identity & public boundary (Phase B)

- Canonical identity: `property_id` (UUID)
- `property_code` may duplicate — resolve via `src/hub/property_resolve.py`
- Public catalog: explicit allowlist in `src/hub/public_projection.py`

## Cursor / agent guidance

When asking an agent to implement features:

1. Say **"code only — do not commit data files"**
2. Point to this doc
3. Never approve `git add -A` on this repo without reviewing `data/` diff
