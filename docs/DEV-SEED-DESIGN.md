# Developer Seed Data

**Status: implemented** (`data_seed/` + `scripts/build_data_seed.py`)

Minimal synthetic dataset for local Hub/Co-Agent/tests after runtime JSON leaves Git.

## Goals

- No owner PII, no real credentials
- Enough rows to test duplicate codes, project relations, search, caption, Co-Agent

## Proposed layout

```
data_seed/
  properties.json   # ~20 rows
  projects.json     # ~8 projects
  README.md         # how seed is copied on Docker first boot
```

## Required test shapes

1. **Duplicate code block** — 3+ rows sharing `PTP4734`-style code, distinct `id` + `project_id`
2. **Unique codes** — `RXT0001`, `COA0001` for happy-path mutations
3. **Project linkage** — each property references valid `project_id`
4. **Co-Agent rows** — at least 5 with `post_url` or `post_pages_url`
5. **No private fields populated** — empty `notes`, no owner contact arrays

## Bootstrap

Existing Docker entrypoint: `cp -an data_seed/. data/` (no overwrite).

Developers run tests against temp dirs (see Phase B test fixtures) or copy seed once locally.

## Not in seed

- `customer_cases.json` (PII) — empty `[]` or omitted
- `fb_agent.json`, `.env`
- Cache directories
