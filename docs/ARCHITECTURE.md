# Architecture — Property Hub (actual)

This describes the **current** system as implemented in code (not the obsolete Next.js Phase 1 README).

## Overview

```
Admin browser → hub/preview.html (SPA)
Co-Agent browser → hub/co/index.html
        ↓ HTTP
scripts/hub_server.py (Python ThreadingHTTPServer)
        ↓
src/hub/*_store.py  →  data/*.json  (+ hub.db, preview-data.js)
        ↓ optional background
Google Sheets export (one-way, Hub → Sheet)
        ↓
Local Mac/Windows: scripts/comment_agent.py (Playwright)
        ↓
Facebook (post, comment, thumb, fetch-post)
```

**Production host:** Fly.io app `property-hub`, region `sin`, domain `https://hub.realxtateth.com/`

**Source of Truth:** Fly volume `/app/data/properties.json` and `projects.json`.

## Hub server

- Entry: `scripts/hub_server.py`
- Serves static UI from `hub/` and API under `/api/*`
- Auth: cookie session (`HUB_USERS_JSON` + `HUB_SESSION_SECRET`)
- Persistence: JSON files + SQLite index; `threading.RLock` on property writes
- Sheet sync: background queue pushes Hub → Google Sheets (`HUB_AUTO_SYNC_TO_SHEET=1`); pull disabled by default

## Data stores (selected)

| Module | File |
|--------|------|
| `project_store` | properties.json, projects.json, preview-data.js, hub.db |
| `queue_store` | wait_post_queue.json |
| `group_post_publish_store` | group_publish_jobs.json |
| `group_post_store` | group_post_links.json, group_post_codes.json |
| `customer_store` | customer_cases.json |
| `fb_agent_store` | fb_agent.json |

## Google Sheets

- **Direction:** Hub volume → Sheet tabs (export copy)
- **Not SoT** on Fly (`HUB_ALLOW_SHEET_PULL=0`, `HUB_STARTUP_SHEET_SYNC=0`)
- Emergency pull requires explicit env + owner approval

## Facebook agent

- Runs on owner/admin PCs, not on Fly
- Polls Hub with agent bearer token
- Playwright + Chrome CDP (`FB_BROWSER_MODE=auto`)
- Jobs: group publish, group comments, thumb upload, optional full post fetch

## LINE

1. **Hub embedded:** `src/hub/line_menu_webhook.py` — Rich Menu keyword replies on Fly (`LINE_MENU_WEBHOOK=1`), no OpenAI
2. **Standalone bot:** `line_bot/app.py` — FastAPI + optional OpenAI auto-reply (separate process/tunnel)

## OpenAI

- Hub caption generation: **local templates** (`src/hub/text_gen.py`); optional EN polish if key set
- LINE bot: `line_bot/openai_reply.py`, `ops_analyst.py`

## Co-Agent

- Public catalog: `GET /api/co/catalog` (slim fields via `src/hub/co_catalog.py`)
- Traffic: `data/co_traffic/`

## Identity model

- **`property_id` (UUID):** canonical unique internal identity
- **`property_code` (e.g. PTPxxxx):** human-facing reference; **not guaranteed unique** in current data

See `docs/DUPLICATE-CODE-TRIAGE.md`.

## Deployment

- `Dockerfile` → `scripts/docker_entrypoint.sh` → `hub_server.py`
- Volume mount: `/app/data`
- **Exactly 1 Fly machine** (split-brain if >1)

See `DEPLOY_FLY.md` and `docs/OPERATIONS-SAFETY.md`.
