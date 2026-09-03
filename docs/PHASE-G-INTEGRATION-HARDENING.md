# Phase G — Integration Hardening

Offline implementation of Facebook publish claim/lease, LINE webhook durable
dedupe, login rate limiting, and agent_token exposure reduction.

**No push. No deploy. No credential rotation. No live Facebook/LINE/OpenAI.**

## Facebook publish state machine

```
pending / due / failed / awaiting_join
        |
        v  claim_due_for_publish()  [atomic]
     running  (+ attempt_id, idempotency_key, claimed_at, lease_until)
        |
        +--> pre-external failure (e.g. switch_failed, pre_external_failed)
        |         -> failed (retryable; claimable again)
        |
        +--> mark_external_action_started()
        |         |
        |         +--> confirmed success -> posted
        |         +--> known join-needed -> awaiting_join
        |         +--> ambiguous / callback lost -> needs_reconcile
        |
        +--> lease expired, no external_action_started_at -> pending
        +--> lease expired, external_action_started_at set -> needs_reconcile
```

Canonical ambiguous status name: **`needs_reconcile`**.

### Claim / lease

- `claim_due_for_publish()` selects eligible jobs under store lock, assigns
  `attempt_id` + `idempotency_key`, sets `running`, `claimed_at`, `lease_until`
  (15 minutes), increments `attempt_count`, persists, returns claimed jobs.
- `list_due_for_publish()` is an alias that **claims** (not a bare list).
- `needs_reconcile` and `posted` are never claimable.
- Two concurrent workers cannot claim the same job.

### Idempotency key

`sha256(property_id|normalized_group_url|campaign_id)[:32]`

### Ambiguous external result

Once `external_action_started_at` is set, automatic blind retry is forbidden.
Operator must reconcile manually (check Facebook for duplicate posts).

### Callbacks

- Duplicate success on already-`posted`: no-op (keeps first evidence).
- Failure cannot reopen `posted`.
- Stale `attempt_id` is ignored.
- Agent reports `attempt_id` and may set `ambiguous=true`.

### Legacy jobs

Missing/ambiguous `property_id` (including duplicate `property_code` without id)
→ transition to `needs_reconcile` rather than guess-repost. No mass migration.

## LINE webhook dedupe

Store: `data/line_event_dedupe.json` (gitignored runtime state).

Event key:

1. Prefer `webhookEventId` → `wev:{id}`
2. Else message `id` only → `msg:{id}`
3. Else **fail closed** (do not send)

Lifecycle: claim → `processing` → mark outbound started → deliver → `completed`.
On error after outbound started → `needs_reconcile` (no auto-resend).

TTL: **72 hours** for terminal records. Stale `processing` without outbound
may be reclaimed after 15 minutes; with outbound started → remain ambiguous.

## Auth

### Login rate limit

- Module: `src/hub/login_rate_limit.py` (in-memory, single-machine).
- Key: client IP (`Fly-Client-IP` / `CF-Connecting-IP` preferred; `X-Forwarded-For`
  last resort — may be spoofable if edge does not overwrite).
- Policy: **5 failures / 10 minutes** → lockout **~15 minutes**.
- Success clears failure state for that IP.
- HTTP **429** with generic Thai message; 401 remains generic (no username enumeration).
- Passwords never logged.

### agent_token exposure

- `/api/fb-agent/status` always uses `include_token=False`.
- Token returned only from explicit `/api/fb-agent/rotate-token`.
- Starter downloads / install-mac / bootstrap clipboard commands no longer embed
  token or put `?t=` in URLs. Operator sets `COMMENT_AGENT_TOKEN` after rotate.
- Remaining P1: any Hub user who can call rotate still receives a token (no RBAC).

## Runtime files

| Path | Classification |
|------|----------------|
| `data/line_event_dedupe.json` | runtime, gitignored |
| `data/group_publish_jobs.json` | runtime, already gitignored |

Do **not** untrack production SoT (`properties.json` / `projects.json`) in Phase G.

## Remaining limitations

- Operator must manually reconcile `needs_reconcile` Facebook/LINE cases.
- No distributed lock (single-machine JSON architecture by design).
- Rotate-token still exposes token to any authenticated Hub user.
- Historical README credentials may still be POSSIBLY_LIVE — rotate before deploy
  (owner action; not done in Phase G).
- Runtime Git migration / push / deploy still blocked.
