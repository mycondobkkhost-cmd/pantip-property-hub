# Credential Rotation Runbook (Owner)

**Phase H prepares this checklist only. Do NOT rotate real credentials inside an agent chat.**

Do not paste secret values into issues, PRs, chat, or commit messages.

## 1. Categories that may require rotation

| Category | Why | Rotate before deploy? |
|----------|-----|------------------------|
| Hub login passwords (`HUB_USERS_JSON`) | Historical README may have exposed demo/live-like passwords (`POSSIBLY_LIVE`) | **YES if ever used live** |
| FB agent token (`data/fb_agent.json` / rotate-token) | Previously returned to any Hub user via status; may exist in local starter scripts | **YES if token was shared or committed locally** |
| LINE / Google / Fly tokens | Present as secrets; **no Phase G/H proof of exposure** | Only if separately compromised |

## 2. Fly secret NAMES involved (values never in Git)

- `HUB_USERS_JSON`
- `HUB_SESSION_SECRET`
- `HUB_ADMIN_USERS` or `HUB_ADMIN_USERS_JSON` (optional privilege allow-list)
- `LINE_*` (if rotating LINE — only with cause)
- `GOOGLE_SERVICE_ACCOUNT_JSON` (only with cause)

## 3. How to rotate without pasting values into reports

1. Generate new secrets in a local password manager / `openssl rand -hex 32`.
2. Update Fly via CLI interactively or from a local file that is **never committed**:
   - `fly secrets set HUB_USERS_JSON=- < users.json` (stdin)
3. Confirm secret **names** with `fly secrets list` (names only).
4. Delete local temp files securely.

## 4. Preserve access during rotation

1. Keep at least one known-good admin session path before changing passwords.
2. Set `HUB_ADMIN_USERS` / roles **before** relying on privileged rotate/reconcile.
3. Rotate Hub users first, verify login, then rotate FB agent token via privileged rotate-token.
4. Update agent machines' `COMMENT_AGENT_TOKEN` env after rotate.

## 5. Verification after rotation

1. Hub login with new credentials works; old password fails.
2. Ordinary user cannot call rotate-token (403).
3. Operator can rotate once; status still has no token.
4. Agent heartbeat with new token succeeds.
5. Login rate limit still returns generic 401/429.

## 6. Rollback considerations

- Keep previous secret values in a secure vault (not Git) until smoke passes.
- Fly secret set is atomic per key; app machines restart on secret change.
- Do not rewrite Git history unless a separate approved process exists.

## 7. What must NOT be committed

- `.env`, password files, service account JSON
- Local `scripts/mac/เปิดระบบคอมเมนต์.command` with embedded tokens (gitignored)
- Runtime `data/fb_agent.json`, queue JSON, dedupe JSON
- Production `properties.json` / `projects.json` mutations
- Backup directories from Phase E

## 8. History rewrite

**Not authorized in Phase H.** Historical exposure ≠ current-tree exposure.
Rotation (or proof never-live) remains a **deployment gate**.
