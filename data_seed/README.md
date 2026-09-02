# Developer seed data (synthetic — no PII)

This directory bootstraps an empty Hub `data/` volume on first run.

## Contents

- `projects.json` — 8 sample projects
- `properties.json` — 19 sample listings including:
  - **3 rows** sharing code `PTP4734` (distinct `id` / `project_id`) for duplicate-code tests
  - Unique `RXT0001`, `COA0001`
  - 6+ rows with example post URLs for Co-Agent

## Regenerate

```bash
python3 scripts/build_data_seed.py
```

## Docker / Fly

`scripts/docker_entrypoint.sh` copies `data_seed/` → `data/` with `cp -an` (never overwrites existing volume files).

Environment:

- `DATA_SEED_DIR` — default `/app/data_seed`
- `DATA_DIR` — default `/app/data`

## Not included

No `customer_cases.json`, `fb_agent.json`, credentials, or cache directories.
