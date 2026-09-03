# Post-Merge Development Baseline

Frozen after PR #1 merge (2026-09-03). This document defines how future development should proceed.

## Authoritative branches

| Branch | Role |
|--------|------|
| `main` | Integration branch — all merged safety work lives here |
| `origin/main` | Always fetch before starting new work |
| `cursor/<short-feature-name>` | Fresh short-lived branches for each new feature |

**Do not reuse** `cursor/co-agent-plain-thai-dashboard` for unrelated work. That branch is merged and archival.

Merge commit: `4711b7554fa70797dd25ebcee54f67a06e0cc118`

## Production source of truth

| Environment | Data location | Authority |
|-------------|---------------|-----------|
| Production (Fly) | `/app/data` on volume `vol_vz8qondpo5pkpmxv` | **Authoritative** |
| Dev boot seed | `data_seed/` in Git | Synthetic fixtures only |
| Git `data/` | Legacy tracked catalog snapshots | **Not** production SoT |

Rules:

- Never restore production merely because a hash differs from an older backup.
- Never copy Git `data/` into production to "sync" counts or hashes.
- `docker_entrypoint.sh` uses `cp -an` — existing volume files are never overwritten.

## Merge ≠ Deploy

- Merging to `main` does **not** deploy production.
- Fly deploy: manual `workflow_dispatch` only (`.github/workflows/fly-deploy.yml`).
- Render deploy: manual `workflow_dispatch` only (`.github/workflows/render-deploy.yml`).
- Production deploy requires **separate explicit owner authorization**.

Production (as of PR #1 merge): Fly release **v97**, 1 machine, 7481 properties / 2175 projects.

## Feature branch protocol

1. `git fetch origin`
2. Create fresh branch from latest `origin/main`:
   ```bash
   git checkout -b cursor/<short-feature-name> origin/main
   ```
3. Make focused changes; run relevant tests.
4. Commit with clear message; push feature branch only.
5. Open PR to `main`; wait for CI (Offline Safety, Docker Build Check).
6. Merge only with explicit owner authorization.
7. Deploy only with separate explicit owner authorization.

**Never** push directly to `main`.

## New feature start checklist (Cursor)

### REPO

- [ ] Correct repository: `pantip-property-automation`
- [ ] Clean worktree (`git status --short` empty)
- [ ] `git fetch origin`
- [ ] New branch from `origin/main`

### SAFETY

- [ ] No deploy unless explicitly authorized in the phase prompt
- [ ] No production mutation unless explicitly authorized
- [ ] No stash pop/apply
- [ ] No secret printing
- [ ] Do not touch other repos (LivingBKK, RealXtate-Web-MVP)

### TEST

- [ ] Identify affected test suites before coding
- [ ] Run relevant `scripts/test_phase_*.py` after changes
- [ ] Verify physical file persistence
- [ ] Verify `git status` / `git diff` before commit

### DATA

- [ ] `property_id` is canonical identity
- [ ] `property_code` may duplicate (fail closed without id)
- [ ] Production `/app/data` is authoritative
- [ ] Do not copy production data into Git

### REPORT

- [ ] One markdown code block for phase completion reports
- [ ] List exact files changed, tests, commit, push, deploy status, blockers

## Preserved recovery material (read-only)

| Item | Purpose | Action |
|------|---------|--------|
| `stash@{0}` | Pre-merge WIP with runtime catalog churn | **Never restore wholesale** |
| Recovery commit `1f95296` | Cloud-agent WIP snapshot | Archival reference only |
| Branch `cursor/cloud-agent-1788379191247-r012r` | Recovery branch | Do not delete; do not merge without forensic review |

Revisit individual files from stash/recovery **only** file-by-file if a specific feature needs them.

## Deferred items (not blocking development)

- Facebook agent token rotation (see `docs/CREDENTIAL-ROTATION-RUNBOOK.md`)
- Runtime Git Migration (untrack production-like `data/` from Git)
- Reconciliation operator UI in Hub SPA
- Broader endpoint RBAC beyond Phase H privileged paths
- 9 properties missing `project_id` on production (known, not mass corruption)
- GitHub branch protection configuration on `main`
- Render legacy service retirement
- Local secret-bearing temp files cleanup

## CI expectations

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| Offline Safety Tests | push, pull_request | Safety test suites |
| Docker Build Check | path-filtered push/PR | Build image only (`push: false`) |
| Fly deploy | `workflow_dispatch` | Manual production deploy |
| Render deploy | `workflow_dispatch` | Manual Render deploy |
| Hub keepalive | schedule | Read-only health ping |
