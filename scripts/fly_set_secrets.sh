#!/usr/bin/env bash
# Push Property Hub secrets to Fly from Render export or local .env.
# Usage:
#   RENDER_ENV_JSON=/tmp/property-hub-migrate-env.json ./scripts/fly_set_secrets.sh
#   # or with keys already in environment / .env
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.fly/bin:${PATH}"

APP="${FLY_APP:-property-hub}"
ENV_JSON="${RENDER_ENV_JSON:-/tmp/property-hub-migrate-env.json}"

if ! fly auth whoami >/dev/null 2>&1; then
  echo "Not logged in to Fly. Run: fly auth login"
  exit 1
fi

python3 - <<'PY' "$ENV_JSON" "$ROOT/.env" > /tmp/property-hub-fly-secrets.env
import json, sys
from pathlib import Path

out = {}
env_json = Path(sys.argv[1])
if env_json.exists():
    out.update(json.loads(env_json.read_text()))

# Local .env fills gaps (does not override non-empty Render values)
local = Path(sys.argv[2])
if local.exists():
    for line in local.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k not in out or not str(out.get(k) or "").strip():
            out[k] = v

# Service account file if JSON secret missing
sa = Path("credentials/service_account.json")
if (not out.get("GOOGLE_SERVICE_ACCOUNT_JSON")) and sa.exists():
    out["GOOGLE_SERVICE_ACCOUNT_JSON"] = sa.read_text().strip()

# Hub defaults for Fly
out.setdefault("HOST", "0.0.0.0")
out.setdefault("PORT", "8080")
out.setdefault("PYTHONUNBUFFERED", "1")
out.setdefault("HUB_STARTUP_SHEET_SYNC", "1")
out.setdefault("HUB_AUTO_SYNC_TO_SHEET", "1")
out.setdefault("HUB_OVERVIEW_SHEET_NAME", "ทรัพย์รวม")
out.setdefault("HUB_SHEET_NAME", "ทรัพย์ Hub")

# Only hub-relevant keys (never push Facebook/LINE posting secrets to Fly)
allow = {
    "HOST", "PORT", "PYTHONUNBUFFERED",
    "HUB_USERS_JSON", "HUB_SESSION_SECRET",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "HUB_GOOGLE_SHEETS_ID", "GOOGLE_SHEETS_ID",
    "SOURCE_GOOGLE_SHEETS_ID", "MAIN_SHEET_CSV_URL", "MAIN_SHEET_GID", "MAIN_SHEET_NAME",
    "WAIT_POST_SHEET_CSV_URL", "WAIT_POST_SHEET_NAME",
    "HUB_OVERVIEW_SHEET_NAME", "HUB_SHEET_NAME", "HUB_SHEET_GID", "HUB_SHEET_CSV_URL",
    "HUB_STARTUP_SHEET_SYNC", "HUB_AUTO_SYNC_TO_SHEET",
    "HUB_OVERVIEW_SHEET_GID",
}

for k, v in sorted(out.items()):
    if k not in allow:
        continue
    if v is None or str(v) == "":
        continue
    # fly secrets import format: KEY=value (multiline JSON ok if whole file)
    val = str(v).replace("\n", "\\n")
    print(f"{k}={val}")
PY

echo "Setting secrets on app=$APP ..."
fly secrets import -a "$APP" < /tmp/property-hub-fly-secrets.env
rm -f /tmp/property-hub-fly-secrets.env
echo "Done. Verify: fly secrets list -a $APP"
