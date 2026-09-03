# Phase F — Integration Hardening Plan

Implementation-ready design. **Not executed against production.**

## Facebook publish idempotency

**Current classification: UNSAFE**

### Lifecycle (today)

Hub `POST /api/publish-jobs/create` → `group_publish_jobs.json` → agent
`GET /api/fb-agent/publish-due` → Playwright Post → `POST /api/fb-agent/publish-result`.

### Failure that creates duplicates

1. Agent pulls an open job (**no claim / lease**).
2. Facebook accepts the post.
3. Hub result callback fails or agent dies before report.
4. Job remains `pending` / `failed` / `awaiting_join`.
5. Next poll pulls the same job → **second Facebook post**.

### Future design (do not blind-retry after ambiguous external success)

| Field / state | Purpose |
|---------------|---------|
| `publish_job_id` | Stable job identity (already present) |
| `idempotency_key` | `hash(property_id, normalized_group_url, campaign_slot)` at create |
| `status=running` | Atomic claim on pull with `lease_until`, `claimed_by`, `attempt_id` |
| `external_action_started_at` | Set before Playwright Post |
| `external_post_url` / `external_post_id` | Persist evidence of success |
| `external_action_confirmed_at` | Set when Hub accepts result |
| `needs_reconcile` / `UNKNOWN_EXTERNAL_RESULT` | Ambiguous outcome — **operator review, no auto re-post** |

Mirror the claim pattern already used in `fetch_post_store.py`.

Offline tests first; no live Facebook in hardening phase.

---

## LINE webhook deduplication

**Hub embedded webhook: UNSAFE** — no `webhookEventId` store; retries can double-reply.

**Standalone `line_bot`:** absent from current branch tip (docs only); treat as UNSAFE if operated elsewhere.

### Future design

```
event received
  → stable key (webhookEventId or message.id)
  → atomic claim (received)
  → process / reply
  → completed
```

Bounded TTL (48–72h). Replay of `completed` → HTTP 200, no second send.

---

## Auth / rate limit / token exposure

| Finding | Severity |
|---------|----------|
| `/api/auth/login` has no rate limit / lockout | P0 |
| `/api/fb-agent/status` returns `agent_token` to **any** authenticated Hub user | P0 |
| Agent download scripts embed token; token-in-query | P1 |
| Long-lived 14-day sessions; CORS `*` for non-localhost | P2 |

Recommendations: login throttle; restrict agent token to admin / one-time reveal; Prefer SameSite + Secure (already on cloud); no large RBAC in first hardening slice.

---

## CI

Add offline-only GitHub Actions running Phase A–F safety tests.
Never inject Fly/Google/Facebook/LINE/OpenAI secrets.

---

## Out of scope for this document's implementation wave

- Live Facebook / LINE behavior changes without offline tests
- Credential rotation
- Runtime Git untrack of SoT
- Fixing the 9 missing `project_id` production records
