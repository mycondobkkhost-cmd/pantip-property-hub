#!/usr/bin/env bash
# Cloudflare named tunnel → local Property Hub (fallback when Fly/Railway unavailable).
# Requires: cloudflared cert (cloudflared tunnel login) + CLOUDFLARE_API_TOKEN for DNS.
# Does NOT touch apex realxtateth.com / LivingBKK / LINE.
set -euo pipefail

export PATH="${HOME}/bin:${HOME}/.local/bin:${PATH}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="${HUB_DOMAIN:-hub.realxtateth.com}"
TUNNEL_NAME="${TUNNEL_NAME:-property-hub}"
HUB_PORT="${HUB_PORT:-8765}"
CF_DIR="${HOME}/.cloudflared"

if ! command -v cloudflared >/dev/null; then
  echo "cloudflared not found in PATH"
  exit 1
fi

if [[ ! -f "${CF_DIR}/cert.pem" ]]; then
  echo "No Cloudflare tunnel cert. Run: cloudflared tunnel login"
  echo "Authorize zone realxtateth.com, then re-run this script."
  cloudflared tunnel login
fi

# Create tunnel if missing
if ! cloudflared tunnel list 2>/dev/null | grep -q "${TUNNEL_NAME}"; then
  cloudflared tunnel create "${TUNNEL_NAME}"
fi

TUNNEL_ID="$(cloudflared tunnel list | awk -v n="$TUNNEL_NAME" '$1==n || $2==n {print $1; exit}')"
if [[ -z "${TUNNEL_ID}" ]]; then
  TUNNEL_ID="$(python3 - <<PY
import json,subprocess
out=subprocess.check_output(["cloudflared","tunnel","list","--output","json"], text=True)
for t in json.loads(out):
    if t.get("name")=="${TUNNEL_NAME}":
        print(t["id"]); break
PY
)"
fi
echo "Tunnel ${TUNNEL_NAME} id=${TUNNEL_ID}"

CRED="${CF_DIR}/${TUNNEL_ID}.json"
CONFIG="${CF_DIR}/property-hub-config.yml"
cat > "$CONFIG" <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CRED}
ingress:
  - hostname: ${DOMAIN}
    service: http://127.0.0.1:${HUB_PORT}
  - service: http_status:404
EOF

# DNS CNAME via cloudflared (preferred) or Cloudflare API
cloudflared tunnel route dns "${TUNNEL_NAME}" "${DOMAIN}" 2>/dev/null || {
  echo "route dns via cloudflared failed — updating Cloudflare API…"
  LBKK_ENV="${LIVINGBKK_ENV:-$HOME/Desktop/LivingBKK_App/.env.local}"
  set -a; source "$LBKK_ENV"; set +a
  ZONE_ID="$(curl -sS "https://api.cloudflare.com/client/v4/zones?name=realxtateth.com" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'][0]['id'])")"
  TARGET="${TUNNEL_ID}.cfargotunnel.com"
  REC="$(curl -sS "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?name=${DOMAIN}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}")"
  RID="$(echo "$REC" | python3 -c "import sys,json; r=json.load(sys.stdin).get('result') or []; print(r[0]['id'] if r else '')")"
  BODY="$(python3 -c "import json; print(json.dumps({'type':'CNAME','name':'hub','content':'$TARGET','proxied':True,'ttl':1}))")"
  if [[ -n "$RID" ]]; then
    curl -sS -X PUT "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${RID}" \
      -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json" --data "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success'))"
  else
    curl -sS -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
      -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json" --data "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('success'))"
  fi
}

# Ensure hub is running with production env
ENV_JSON="${RENDER_ENV_JSON:-/tmp/property-hub-migrate-env.json}"
export HOST=127.0.0.1
export PORT="$HUB_PORT"
if [[ -f "$ENV_JSON" ]]; then
  eval "$(python3 - <<PY
import json
from pathlib import Path
d=json.loads(Path("$ENV_JSON").read_text())
allow={"HUB_USERS_JSON","HUB_SESSION_SECRET","GOOGLE_SERVICE_ACCOUNT_JSON","HUB_GOOGLE_SHEETS_ID","GOOGLE_SHEETS_ID","SOURCE_GOOGLE_SHEETS_ID","MAIN_SHEET_CSV_URL","MAIN_SHEET_GID","MAIN_SHEET_NAME","WAIT_POST_SHEET_CSV_URL","HUB_OVERVIEW_SHEET_NAME","HUB_SHEET_NAME","HUB_SHEET_GID","HUB_STARTUP_SHEET_SYNC","HUB_AUTO_SYNC_TO_SHEET"}
for k,v in d.items():
    if k in allow and v is not None and str(v)!="":
        # shell-escape
        import shlex
        print(f"export {k}={shlex.quote(str(v))}")
print("export HUB_STARTUP_SHEET_SYNC=1")
print("export HUB_AUTO_SYNC_TO_SHEET=1")
PY
)"
fi

if ! curl -sf "http://127.0.0.1:${HUB_PORT}/api/health" >/dev/null; then
  echo "Starting hub_server on :${HUB_PORT}…"
  cd "$ROOT"
  nohup python3 scripts/hub_server.py >>/tmp/property-hub-server.log 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf "http://127.0.0.1:${HUB_PORT}/api/health" >/dev/null && break
    sleep 0.5
  done
fi

echo "Running tunnel (foreground). Use launchd for always-on."
echo "Admin URL: https://${DOMAIN}/"
exec cloudflared tunnel --config "$CONFIG" run "${TUNNEL_NAME}"
