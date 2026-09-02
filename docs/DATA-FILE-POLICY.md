# Data File Policy — Property Hub

This document classifies important files under `data/` and related paths.
It does **not** change runtime behavior. Production Source of Truth (SoT) on Fly is the **persistent volume** at `/app/data`.

## Legend

| Column | Meaning |
|--------|---------|
| **SoT** | Authoritative runtime data (Hub volume on Fly) |
| **Derived** | Generated from SoT or other inputs |
| **Commit?** | Safe to commit to Git in normal workflow |

## Core runtime (SoT on Fly)

| Path | Format | Role | SoT | Mutable | Commit? | Regenerate? | Backup |
|------|--------|------|-----|---------|---------|-------------|--------|
| `data/properties.json` | JSON | All property listings | **Yes** | Yes | **No** (see migration options) | Partial (sheet pull disabled by default) | **Critical** |
| `data/projects.json` | JSON | Project master | **Yes** | Yes | **No** | Partial | **Critical** |
| `data/hub.db` | SQLite | Search/index cache | Derived | Yes | No | Yes from JSON | Optional |
| `data/wait_post_queue.json` | JSON | Post queue | Yes | Yes | No | Partial | High |
| `data/focus_properties.json` | JSON | Focus pins | Yes | Yes | No | Partial | Medium |
| `data/customer_cases.json` | JSON | CRM follow-up cases | Yes | Yes | **Avoid** (PII) | Partial | High |
| `data/current_tenants.json` | JSON | Current tenants | Yes | Yes | No | Partial | High |
| `data/facebook_groups.json` | JSON | Group directory | Reference + runtime | Yes | Reference OK | Partial | Medium |
| `data/project_aliases.json` | JSON | Project name aliases | Reference | Yes | Caution | Partial | Medium |
| `data/zone_master.json` | JSON | Zone master | Reference/runtime | Yes | Caution | Seed possible | Medium |
| `data/transit_master.json` | JSON | Transit master | Reference/runtime | Yes | Caution | Seed possible | Medium |

## Job / agent state (runtime, not in Git today)

| Path | Role | SoT | Commit? | Backup |
|------|------|-----|---------|--------|
| `data/group_publish_jobs.json` | FB group publish queue | Yes | No (gitignored) | High |
| `data/group_post_links.json` | Group comment links | Yes | No | High |
| `data/group_post_codes.json` | Comment code settings | Yes | No | High |
| `data/fetch_post_jobs.json` | Agent fetch-post jobs | Yes | No | Medium |
| `data/fb_agent.json` | Agent tokens/credentials | Yes | No | High |
| `data/auto_follow.json` | Auto-follow queue | Yes | No | Medium |
| `data/post_footer_snippets.json` | Caption footers | Yes | No | Medium |
| `data/caption_copy_history.json` | Caption variant history | Derived | No | Low |

## Exports & snapshots (derived)

| Path | Role | SoT | Commit? | Regenerate? |
|------|------|-----|---------|-------------|
| `data/hub_overview_export.csv` | Overview export snapshot | No | **No** | Yes (sync/export) |
| `data/main_sheet.csv` | Main sheet CSV snapshot | No | **No** | Yes |
| `data/hub_sheet_export.csv` | Hub tab export | No | No | Yes |
| `data/wait_post_sheet.csv` | Wait-post export | No | No | Yes |
| `data/customer_followup_export.csv` | CRM export | No | No | Yes |

## Generated catalog (derived, public when served)

| Path | Role | SoT | Commit? | Regenerate? |
|------|------|-----|---------|-------------|
| `data/preview-data.js` | Hub UI embedded catalog | No | No (gitignored) | Yes (`ensure_preview_js`) |
| `data/preview-data.meta.json` | Catalog metadata | No | No | Yes |
| `hub/preview-data.js` | Legacy mirror path | No | **No** | Yes (mirror only) |

Public catalog fields are projected via `src/hub/public_projection.py` (Phase B). Authenticated full catalog uses `/api/hub/catalog`.

## Cache & logs (never commit)

| Path | Role | Commit? |
|------|------|---------|
| `data/thumb_cache/` | Image thumb cache | No |
| `data/propertyhub_cache/` | PropertyHub scrape cache | No |
| `data/living_cache/` | Living location cache | No |
| `data/publish_uploads/` | Uploaded publish images | No |
| `data/co_traffic/` | Co-Agent analytics | No |
| `logs/` | Runtime logs | No |

## Secrets & sessions (never commit)

| Path | Role |
|------|------|
| `.env` | Local env + `HUB_USERS_JSON` |
| `credentials/` | Google service account files |
| `cookies/` | Facebook browser sessions |

## Fly volume vs Git vs Docker seed

1. **Production:** `/app/data` on Fly volume = SoT. Survives deploy/restart.
2. **Docker boot:** `scripts/docker_entrypoint.sh` runs `cp -an data_seed/. data/` — **never overwrites** existing volume files.
3. **Git today:** `data/properties.json` and `data/projects.json` are still **tracked** (historical). They may be **older or divergent** from production volume.
4. **New clones:** Get tracked JSON as a **starting snapshot**, not live production.
5. **Dev seed:** `data_seed/` holds synthetic fixtures (Phase C) — not production data.
6. **Do not** `git add -A` after local Hub edits — see `docs/REPOSITORY-DATA-SEPARATION.md`.

## Backup requirement summary

**Must backup on Fly (volume snapshot or scheduled export):**

- `properties.json`, `projects.json`
- CRM/queue/agent JSON listed above

**Nice to have:**

- `hub.db`, CSV exports, `preview-data.js`

Use `scripts/backup_data_dir.py` for local/volume backup drills. See `docs/OPERATIONS-SAFETY.md` and `docs/PHASE-B-BACKUP-PLAN.md`.
