#!/usr/bin/env bash
# Finish moving hub.realxtateth.com off Render → this Mac via Cloudflare Tunnel.
# Prereq: cloudflared tunnel login (cert in ~/.cloudflared/cert.pem)
# Local Hub must listen on :8765
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$ROOT/bin:$PATH"
DOMAIN="${DOMAIN:-realxtateth.com}"
FQDN="hub.${DOMAIN}"
TUNNEL_NAME="${TUNNEL_NAME:-property-hub-mac}"
LOCAL="${LOCAL:-http://127.0.0.1:8765}"
CONF_DIR="${HOME}/.cloudflared"

if [[ ! -f "$CONF_DIR/cert.pem" ]]; then
  echo "ยังไม่มี cert — รัน: cloudflared tunnel login"
  echo "แล้วเลือกโดเมน ${DOMAIN} ในเบราว์เซอร์"
  exit 1
fi

# Create tunnel if missing
if ! cloudflared tunnel list 2>/dev/null | awk '{print $2}' | grep -qx "$TUNNEL_NAME"; then
  cloudflared tunnel create "$TUNNEL_NAME"
fi

TUNNEL_ID="$(cloudflared tunnel list | awk -v n="$TUNNEL_NAME" '$2==n{print $1; exit}')"
if [[ -z "${TUNNEL_ID}" ]]; then
  echo "หา tunnel id ไม่เจอ"
  cloudflared tunnel list
  exit 1
fi

CRED="$CONF_DIR/${TUNNEL_ID}.json"
cat >"$CONF_DIR/config.yml" <<EOF
tunnel: ${TUNNEL_ID}
credentials-file: ${CRED}

ingress:
  - hostname: ${FQDN}
    service: ${LOCAL}
  - service: http_status:404
EOF

# Route DNS (uses cert.pem; may update Cloudflare DNS)
cloudflared tunnel route dns --overwrite-dns "$TUNNEL_NAME" "$FQDN" || true

echo "Tunnel ${TUNNEL_NAME} (${TUNNEL_ID}) → ${LOCAL}"
echo "Starting cloudflared…"
exec cloudflared tunnel --config "$CONF_DIR/config.yml" run "$TUNNEL_NAME"
