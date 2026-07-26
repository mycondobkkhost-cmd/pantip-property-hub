#!/usr/bin/env bash
# Deploy Property Hub to Fly.io and point hub.realxtateth.com at it.
# Does NOT touch apex realxtateth.com / LivingBKK / LINE.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.fly/bin:${HOME}/bin:${PATH}"

APP="${FLY_APP:-property-hub}"
DOMAIN="${HUB_DOMAIN:-hub.realxtateth.com}"
ZONE_DOMAIN="${ZONE_DOMAIN:-realxtateth.com}"

if ! fly auth whoami >/dev/null 2>&1; then
  echo "Fly not authenticated. Opening login…"
  fly auth login || true
  if ! fly auth whoami >/dev/null 2>&1; then
    echo "Still not logged in. Create a free Fly account, then re-run."
    exit 1
  fi
fi

echo "=== Fly whoami ==="
fly auth whoami

# Create app if missing
if ! fly apps list --json 2>/dev/null | python3 -c "import sys,json; apps=json.load(sys.stdin); sys.exit(0 if any(a.get('Name')=='$APP' or a.get('name')=='$APP' for a in apps) else 1)"; then
  echo "Creating app $APP in sin…"
  fly apps create "$APP" --org personal 2>/dev/null || fly apps create "$APP" || true
fi

# Secrets from Render export (or local)
if [[ -f /tmp/property-hub-migrate-env.json ]]; then
  RENDER_ENV_JSON=/tmp/property-hub-migrate-env.json "$ROOT/scripts/fly_set_secrets.sh"
else
  echo "WARN: /tmp/property-hub-migrate-env.json missing — set secrets manually"
fi

echo "=== fly deploy ==="
fly deploy -a "$APP" --remote-only

echo "=== certificates for $DOMAIN ==="
fly certs add "$DOMAIN" -a "$APP" 2>/dev/null || fly certs show "$DOMAIN" -a "$APP" || true

FLY_HOSTNAME="${APP}.fly.dev"
echo "Fly hostname: https://${FLY_HOSTNAME}"

# Point Cloudflare DNS hub → fly.dev (DNS-only so Fly can issue certs, or proxied with Full SSL)
LBKK_ENV="${LIVINGBKK_ENV:-$HOME/Desktop/LivingBKK_App/.env.local}"
if [[ -f "$LBKK_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$LBKK_ENV"
  set +a
fi

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
  echo "CLOUDFLARE_API_TOKEN missing — set DNS manually:"
  echo "  CNAME hub → ${FLY_HOSTNAME} (DNS only recommended for fly certs)"
  exit 0
fi

ZONE_JSON="$(curl -sS "https://api.cloudflare.com/client/v4/zones?name=${ZONE_DOMAIN}" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}")"
ZONE_ID="$(echo "$ZONE_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result'][0]['id'] if d.get('success') and d['result'] else '')")"
if [[ -z "$ZONE_ID" ]]; then
  echo "Could not resolve Cloudflare zone for $ZONE_DOMAIN"
  exit 1
fi

REC_JSON="$(curl -sS "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records?name=${DOMAIN}" \
  -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}")"
REC_ID="$(echo "$REC_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); r=d.get('result') or []; print(r[0]['id'] if r else '')")"

BODY="$(python3 -c "import json; print(json.dumps({'type':'CNAME','name':'hub','content':'$FLY_HOSTNAME','proxied':False,'ttl':1}))")"

if [[ -n "$REC_ID" ]]; then
  echo "Updating DNS record $REC_ID → CNAME hub → $FLY_HOSTNAME (DNS only)"
  curl -sS -X PUT "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records/${REC_ID}" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print('success', d.get('success'), d.get('errors'))"
else
  echo "Creating CNAME hub → $FLY_HOSTNAME"
  curl -sS -X POST "https://api.cloudflare.com/client/v4/zones/${ZONE_ID}/dns_records" \
    -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print('success', d.get('success'), d.get('errors'))"
fi

echo ""
echo "Admin URL: https://${DOMAIN}/"
echo "Health:    https://${DOMAIN}/api/health"
echo "Co-Agent:  https://${DOMAIN}/co/"
echo "Fly app:   https://${FLY_HOSTNAME}/"
echo ""
echo "Render: leave sleeping or suspend from dashboard — admins should use ${DOMAIN} only."
