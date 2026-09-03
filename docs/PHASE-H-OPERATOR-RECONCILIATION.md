# Phase H — Operator Reconciliation + Privileged Token Control

Offline safety phase. **No push. No deploy. No real Facebook/LINE. No credential rotation.**

## Facebook reconciliation

Jobs in `needs_reconcile` are never auto-claimed.

Operator API (privileged):

- `GET /api/groups/publish/reconcile` — list attention jobs
- `POST /api/groups/publish/reconcile` — mutate by canonical `job_id` only

Actions:

| Action | Result |
|--------|--------|
| `confirm_posted` | → `posted` (requires `external_post_url`) |
| `confirm_not_posted` | → `pending` (explicit safe retry) |
| `cancel` | → `cancelled` |
| `keep_unresolved` | no mutation |

Audit fields: `reconciled_at`, `reconciliation_action`, `reconciled_by`.
Preserves `property_id` and `idempotency_key`. Never posts to Facebook.

UI: deferred (API + tests + docs prioritized to avoid large preview.html churn).

## LINE reconciliation

Privileged API:

- `GET /api/line/reconcile`
- `POST /api/line/reconcile` with `event_key` + action

| Action | Result |
|--------|--------|
| `mark_completed` | → `completed` |
| `allow_reprocess` | clears record (future claim allowed); **does not send** |
| `suppress` | → `completed` + suppressed |
| `keep_unresolved` | no mutation |

No LINE network calls. No token storage. Minimal PII (no message text in listing).

## Privilege model

Ordinary Hub session ≠ privileged operator.

Configuration:

1. `role` / `privilege` on `HUB_USERS_JSON` entries (`admin` / `operator` / `owner`)
2. `HUB_ADMIN_USERS_JSON` — JSON username list
3. `HUB_ADMIN_USERS` — comma-separated usernames

Missing admin config on cloud → **fail closed**.

Local `HUB_LOCAL_DEV=1` without admin config: only `angkarn1996` is privileged.

Protected:

- `/api/fb-agent/rotate-token`
- publish + LINE reconcile list/mutate

`/api/fb-agent/status` remains token-free. Hub `_json` strips `agent_token` unless `allow_agent_token=True` (rotate only).

Agent auth no longer accepts `?t=` query tokens (Authorization / X-Agent-Token only).

## Proxy / IP

Trust: Fly-Client-IP → CF-Connecting-IP → socket peer.

`X-Forwarded-For` only if `HUB_TRUST_X_FORWARDED_FOR=1`.

## Remaining limitations

- Operator UI panel deferred
- Historical Git history may still contain old credentials (rotation gate)
- Runtime SoT still tracked (migration not executed)
- Other Hub authenticated endpoints exist; only token rotate + reconcile elevated in Phase H

See also: `docs/CREDENTIAL-ROTATION-RUNBOOK.md`
