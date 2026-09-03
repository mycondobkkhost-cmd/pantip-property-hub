# Phase B — Backup & Restore Plan (design only)

## Scope

See `docs/DATA-FILE-POLICY.md` for full classification.

### Authoritative (must backup)

- `properties.json`, `projects.json`

### Runtime important (include when present)

- `customer_cases.json`, `current_tenants.json`, `focus_properties.json`
- `wait_post_queue.json`, `group_publish_jobs.json`, group post state JSON
- `auto_follow.json`, `fetch_post_jobs.json`, reference masters

### Excluded from ordinary backup

- Cache dirs: `propertyhub_cache/`, `thumb_cache/`, `living_cache/`, `publish_uploads/`, `co_traffic/`
- Derived: `preview-data.js`, CSV exports, `hub.db`
- Secrets: `fb_agent.json`, `.env`, `credentials/`, `cookies/`

## Local tool

`scripts/backup_data_dir.py`:

```bash
python3 scripts/backup_data_dir.py backup /path/to/data
python3 scripts/backup_data_dir.py verify /path/to/backups/data-backup-...
python3 scripts/backup_data_dir.py restore /path/to/backup /path/to/new-data --dry-run
```

Manifest: `manifest.json` with schema `pantip-data-backup/v1`, per-file SHA-256, classification.

## Restore policy

1. Restore into **new** directory first (never default overwrite)
2. Verify manifest checksums
3. Validate JSON + spot-check property/project IDs
4. Only then replace volume contents (owner-approved maintenance window)

## Future Fly production backup (not configured in Phase B)

1. **Fly volume snapshot** — weekly + before deploy; retain 4 weekly / 3 pre-deploy
2. **Application backup** — daily `backup_data_dir` to private object storage (S3/R2), retain 30 days
3. **Restore drill** — quarterly restore to staging volume, verify counts + checksum
4. **Secrets** — recover from Fly secrets + separate credential vault; never rely on `fb_agent.json` backup alone

## Secret recovery (separate policy)

- Rotate FB tokens via agent re-auth
- Google SA from Fly secret `GOOGLE_SERVICE_ACCOUNT_JSON`
- Hub users from `HUB_USERS_JSON` + `HUB_SESSION_SECRET`

Do **not** store these in ordinary data backups.
