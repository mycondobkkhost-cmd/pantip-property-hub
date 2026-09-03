# Property Hub

Python-based admin platform for property catalog, Facebook group workflows, Co-Agent, and Google Sheets export.

**Production:** https://hub.realxtateth.com/ (Fly.io, volume-backed)

> This replaces the obsolete “Next.js Phase 1 empty table” description. The live system is `scripts/hub_server.py` + `hub/preview.html`.

## What it does

- Property & project CRUD (JSON on disk)
- Hub UI: focus, wait-post queue, CRM, group publish, comments
- Co-Agent public catalog (`/co/`)
- One-way export to Google Sheets (Hub → Sheet)
- Facebook automation via **local agent** (Playwright on Mac/Windows)

## Source of Truth

| Data | Authoritative location |
|------|------------------------|
| Properties | `data/properties.json` (Fly: `/app/data/`) |
| Projects | `data/projects.json` |
| Google Sheet | **Export copy only** — not SoT |

See `docs/DATA-FILE-POLICY.md` and `docs/ARCHITECTURE.md`.

## Run locally (safe)

```bash
cd /path/to/pantip-property-automation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-hub.txt

# Required: set login accounts in .env (never commit .env)
# HUB_USERS_JSON={"username":{"password":"[REDACTED]","name":"Display"}}

# Optional: weak demo accounts for local dev ONLY
# HUB_LOCAL_DEV=1

python3 scripts/hub_server.py
```

Open http://127.0.0.1:8765/

Accounts are configured through **`HUB_USERS_JSON`** in environment (or `.env` locally).  
**Never store production or test passwords in repository documentation.**

## Login configuration

| Variable | Purpose |
|----------|---------|
| `HUB_USERS_JSON` | JSON object of `{username: {password, name}}` |
| `HUB_SESSION_SECRET` | Cookie signing secret (**required on Fly**) |
| `HUB_LOCAL_DEV=1` | Enables weak local demo users when `HUB_USERS_JSON` unset (**local only**) |

Cloud hosts **fail closed** if `HUB_USERS_JSON` or `HUB_SESSION_SECRET` is missing.

> **Credential history:** Plaintext demo passwords previously appeared in this README and remain in Git history. Rotate any credentials that were ever used in production before deploy.

## Tests (offline, safe)

```bash
python3 scripts/test_hub_persist_survive.py
python3 scripts/test_hub_codes.py
python3 scripts/test_caption_variant.py
python3 scripts/test_phase_a_safety.py
python3 scripts/test_phase_b_identity.py
python3 scripts/test_phase_b_public.py
python3 scripts/test_phase_b_backup.py
python3 scripts/test_phase_c_ops.py
python3 scripts/test_phase_d_reconciliation.py
```

## Facebook agent (local PC only)

Not run on Fly. See `scripts/comment_agent.py` and Hub → FB Agent panel for token.

**Side effects:** real Facebook posts/comments. Use dry-run for comment script tests.

## Dangerous commands (avoid without review)

- `git add -A` (may commit entire catalog)
- Enabling `HUB_ALLOW_SHEET_PULL=1` (Sheet overwrites Hub)
- `fly deploy` from unreviewed mixed data/code tree
- Running agent against production Hub without intent

See `docs/OPERATIONS-SAFETY.md`.

## Documentation index

| Doc | Topic |
|-----|--------|
| `docs/ARCHITECTURE.md` | System design |
| `docs/DATA-FILE-POLICY.md` | Data file classes |
| `docs/REPOSITORY-DATA-SEPARATION.md` | Git vs runtime data |
| `docs/DUPLICATE-CODE-TRIAGE.md` | Duplicate property codes |
| `docs/OPERATIONS-SAFETY.md` | Production safety rules |
| `docs/PROPERTY-IDENTITY.md` | Phase B identity rules |
| `docs/PHASE-C-OPERATIONS.md` | Dev seed & recovery tooling |
| `DEPLOY_FLY.md` | Fly deployment |

## UI assets

- `hub/preview.html` — main Hub SPA
- `hub/co/index.html` — Co-Agent
- `data/preview-data.js` — generated catalog (served from data volume)

Legacy `npm run dev` Next.js flow is **not** the current stack.
