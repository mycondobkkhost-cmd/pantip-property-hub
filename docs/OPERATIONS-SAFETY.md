# Operations Safety

Rules for anyone operating Property Hub in production or on a developer machine.

## Never do casually

| Action | Risk |
|--------|------|
| Set `HUB_ALLOW_SHEET_PULL=1` | Sheet **overwrites** Hub volume (data loss) |
| Set `HUB_STARTUP_SHEET_SYNC=1` on Fly | Boot pull may overwrite local edits |
| `fly scale count` > 1 | Split-brain on JSON files |
| `git add -A` + commit | Commits 7k+ property rows by mistake |
| Run `comment_agent.py` on wrong Hub URL | Posts/comments to Facebook |
| Start LINE bot pointed at production without review | Customer messages / OpenAI replies |
| Delete Fly volume `hub_data` | **Total catalog loss** |

## Source of Truth

- **Properties:** `/app/data/properties.json` (Fly volume)
- **Projects:** `/app/data/projects.json` (Fly volume)
- **Google Sheet:** export copy only — not authoritative

## Fly deployment preconditions

Before `fly deploy`:

1. Code reviewed separately from data diffs
2. `HUB_USERS_JSON` and `HUB_SESSION_SECRET` set via `scripts/fly_set_secrets.sh` or `scripts/verify_fly_secrets.py`
3. `HUB_ALLOW_SHEET_PULL=0`, `HUB_STARTUP_SHEET_SYNC=0`
4. Scale = **1 machine**
5. Volume `hub_data` attached

**Do not deploy** from a dirty tree that mixes unreviewed data churn.

## Facebook agent side effects

`scripts/comment_agent.py` can:

- Post to Facebook groups (publish jobs)
- Comment on group posts
- Upload images / fetch posts

Always confirm Hub URL and agent token. Use `--dry-run` on `comment_group_posts.py` for comment-only tests.

## LINE side effects

- Hub `/line/webhook` replies to menu keywords
- `line_bot/app.py` can auto-reply with OpenAI when enabled

Do not start bots against production LINE channel without `LINE_AUTO_REPLY` review.

## Secret handling

- Configure accounts via **`HUB_USERS_JSON`** (Fly secret / local `.env`)
- Never put passwords in README or committed docs
- Rotate credentials if they ever appeared in Git history
- Local demo users require **`HUB_LOCAL_DEV=1`** — never enabled on cloud

## Safe local tests

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

These tests use mocks/temp dirs — no Facebook, LINE, Sheets, or Fly.

## Local Hub startup

```bash
# Set in .env:
# HUB_USERS_JSON={...}
# or for dev only:
# HUB_LOCAL_DEV=1

python3 scripts/hub_server.py
# open http://127.0.0.1:8765/
```

## Backup (Phase B tooling)

- Local/volume backup: `scripts/backup_data_dir.py`
- Restore drill (synthetic): `scripts/restore_drill.py`
- Fly secret checklist: `scripts/verify_fly_secrets.py`

**Production volume backup is still required before deploy.** Tooling exists; scheduled Fly snapshots are not yet automated in-repo.

## Rollback

- Fly: deploy previous release image (volume data persists)
- Git: revert code commit — **does not** revert volume data
- Sheet: not a restore source for Hub catalog under normal policy
