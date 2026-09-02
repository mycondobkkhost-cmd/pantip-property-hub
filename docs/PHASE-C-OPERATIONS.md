# Phase C — Operational Backup + Dev Seed + Migration Readiness

Phase C builds on Phase B (identity + public boundary + local backup tool).
**No production deploy or Git untrack in this phase** unless owner explicitly approves.

## Completed in Phase C

| Item | Artifact |
|------|----------|
| Synthetic dev seed | `data_seed/` + `scripts/build_data_seed.py` |
| Docker bootstrap | `Dockerfile` copies `data_seed/` only (not production `data/`) |
| Restore drill | `scripts/restore_drill.py` |
| Fly secret name check | `scripts/verify_fly_secrets.py` (names only) |
| Migration readiness | `scripts/migration_readiness.py` |
| Tests | `scripts/test_phase_c_ops.py` |

## Owner actions (production)

### 1. Verify Fly secrets (read-only)

```bash
python3 scripts/verify_fly_secrets.py --app property-hub
# or manually:
fly secrets list -a property-hub
```

Required names: `HUB_USERS_JSON`, `HUB_SESSION_SECRET`  
Recommended: `GOOGLE_SERVICE_ACCOUNT_JSON`, LINE secrets if used.

### 2. Manual backup on Fly (read-only)

SSH or one-off machine with volume access:

```bash
python3 scripts/backup_data_dir.py backup /app/data
python3 scripts/backup_data_dir.py verify /path/to/backup-dir
```

Store archives off-volume (S3/R2). Do **not** include `fb_agent.json` in ordinary backups.

### 3. Restore drill (staging only)

```bash
python3 scripts/restore_drill.py /path/to/staging-data
```

Never run restore directly against production volume without maintenance window.

### 4. Migration readiness check

```bash
python3 scripts/migration_readiness.py
```

When all core checks pass **and** owner approves:

1. `git rm --cached data/properties.json data/projects.json`
2. Update `.gitignore` for runtime SoT
3. Deploy — existing Fly volume unchanged; new clones use `data_seed/`

## Recommended Fly backup schedule (not configured automatically)

| Layer | Frequency | Retention |
|-------|-----------|-----------|
| Fly volume snapshot | Weekly + pre-deploy | 4 weekly, 3 pre-deploy |
| App backup (`backup_data_dir.py`) | Daily | 30 days |
| Restore drill | Quarterly | Staging volume |

## Local developer bootstrap

```bash
python3 scripts/build_data_seed.py   # regenerate seed
mkdir -p data && cp -an data_seed/. data/   # first-time local
```

Or Docker/Fly entrypoint: `scripts/docker_entrypoint.sh` (`cp -an`, no overwrite).

## Tests

```bash
python3 scripts/test_phase_a_safety.py
python3 scripts/test_phase_b_identity.py
python3 scripts/test_phase_b_public.py
python3 scripts/test_phase_b_backup.py
python3 scripts/test_phase_c_ops.py
```

## Still NO-GO without owner approval

- Removing `data/properties.json` / `data/projects.json` from Git
- Scheduled production backup on Fly
- Production restore replacing live volume
- New product features
