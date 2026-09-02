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

# Use `fly secrets set` via argv (NOT `secrets import`).
# Import's dotenv parser turns bare JSON {"a":"b"} into {\"a\":\"b\"}, which
# breaks HUB_USERS_JSON / GOOGLE_SERVICE_ACCOUNT_JSON login & Sheets auth.
python3 - <<'PY' "$ENV_JSON" "$ROOT/.env" "$APP"
import json, subprocess, sys
from pathlib import Path

env_json = Path(sys.argv[1])
local = Path(sys.argv[2])
app = sys.argv[3]

out = {}
if env_json.exists():
    raw = json.loads(env_json.read_text())
    for k, v in raw.items():
        # Normalize: migrate dumps sometimes store JSON objects as dicts
        if isinstance(v, (dict, list)):
            out[k] = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        else:
            out[k] = v

if local.exists():
    for line in local.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k not in out or not str(out.get(k) or "").strip():
            out[k] = v

sa = Path("credentials/service_account.json")
if (not out.get("GOOGLE_SERVICE_ACCOUNT_JSON")) and sa.exists():
    out["GOOGLE_SERVICE_ACCOUNT_JSON"] = sa.read_text().strip()

out.setdefault("HOST", "0.0.0.0")
out.setdefault("PORT", "8080")
out.setdefault("PYTHONUNBUFFERED", "1")
out.setdefault("HUB_STARTUP_SHEET_SYNC", "0")
out.setdefault("HUB_ALLOW_SHEET_PULL", "0")
out.setdefault("HUB_AUTO_SYNC_TO_SHEET", "1")
out.setdefault("HUB_OVERVIEW_SHEET_NAME", "ทรัพย์รวม")
out.setdefault("HUB_SHEET_NAME", "ทรัพย์ Hub")
out.setdefault("HUB_QUEUE_SHEET_SYNC", "0")
out.setdefault("HUB_ALLOW_QUEUE_SHEET_PULL", "0")
out.setdefault("HUB_FOCUS_SHEET_SYNC", "1")
out.setdefault("HUB_CUSTOMERS_SHEET_SYNC", "1")
out.setdefault("LINE_MENU_WEBHOOK", "1")
out.setdefault("HUB_FOCUS_SHEET_NAME", "Hubโฟกัส")
out.setdefault("HUB_CUSTOMERS_SHEET_NAME", "Hubฟอโล่ว")

allow = {
    "HOST", "PORT", "PYTHONUNBUFFERED",
    "HUB_USERS_JSON", "HUB_SESSION_SECRET",
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "HUB_GOOGLE_SHEETS_ID", "GOOGLE_SHEETS_ID",
    "SOURCE_GOOGLE_SHEETS_ID", "MAIN_SHEET_CSV_URL", "MAIN_SHEET_GID", "MAIN_SHEET_NAME",
    "WAIT_POST_SHEET_CSV_URL", "WAIT_POST_SHEET_NAME",
    "HUB_OVERVIEW_SHEET_NAME", "HUB_SHEET_NAME", "HUB_SHEET_GID", "HUB_SHEET_CSV_URL",
    "HUB_STARTUP_SHEET_SYNC", "HUB_ALLOW_SHEET_PULL", "HUB_AUTO_SYNC_TO_SHEET",
    "HUB_OVERVIEW_SHEET_GID",
    "HUB_QUEUE_SHEET_SYNC", "HUB_ALLOW_QUEUE_SHEET_PULL", "HUB_FOCUS_SHEET_SYNC", "HUB_CUSTOMERS_SHEET_SYNC",
    "HUB_FOCUS_SHEET_NAME", "HUB_CUSTOMERS_SHEET_NAME", "HUB_STATE_GOOGLE_SHEETS_ID",
    "LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN", "LINE_MENU_WEBHOOK",
}

pairs = []
for k, v in sorted(out.items()):
    if k not in allow or v is None or str(v) == "":
        continue
    val = str(v)
    # Undo accidental quote-escaping from a previous bad import
    if k in {"HUB_USERS_JSON", "GOOGLE_SERVICE_ACCOUNT_JSON"} and '\\"' in val:
        try:
            json.loads(val)
        except json.JSONDecodeError:
            fixed = val.replace('\\"', '"')
            json.loads(fixed)  # raise if still bad
            val = fixed
    if k == "HUB_USERS_JSON":
        data = json.loads(val)
        if not isinstance(data, dict) or not data:
            raise SystemExit("HUB_USERS_JSON must be a non-empty JSON object")
    pairs.append(f"{k}={val}")

print(f"Setting {len(pairs)} secrets on app={app} via fly secrets set ...")
# Batch in chunks to stay under arg limits; JSON secrets stay intact as argv.
chunk = 8
for i in range(0, len(pairs), chunk):
    batch = pairs[i : i + chunk]
    r = subprocess.run(["fly", "secrets", "set", "-a", app, *batch], check=False)
    if r.returncode != 0:
        raise SystemExit(r.returncode)
print("Done. Verify: fly secrets list -a", app)
PY
