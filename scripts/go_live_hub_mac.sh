#!/usr/bin/env bash
# One-shot: ensure Hub + Cloudflare Tunnel are running on this Mac.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$ROOT/bin:$PATH"
chmod +x "$ROOT/scripts/start_hub_local.sh" "$ROOT/scripts/start_hub_tunnel.sh"

mkdir -p "$ROOT/logs"

# Start Hub if needed
if ! curl -sf --max-time 2 "http://127.0.0.1:8765/api/health" >/dev/null; then
  echo "Starting local Hub…"
  nohup "$ROOT/scripts/start_hub_local.sh" >/dev/null 2>&1 &
  for i in $(seq 1 30); do
    curl -sf --max-time 2 "http://127.0.0.1:8765/api/health" >/dev/null && break
    sleep 1
  done
fi
curl -sf "http://127.0.0.1:8765/api/health" | head -c 120; echo

if [[ ! -f "$HOME/.cloudflared/cert.pem" ]]; then
  echo ""
  echo "=== ต้อง authorize Cloudflare Tunnel ครั้งเดียว ==="
  echo "กำลังเปิดเบราว์เซอร์ — ล็อกอิน Cloudflare แล้วเลือกโดเมน realxtateth.com"
  cloudflared tunnel login
fi

# Kill old tunnel runners
pkill -f "cloudflared tunnel.*property-hub-mac" 2>/dev/null || true
pkill -f "cloudflared tunnel --config" 2>/dev/null || true
sleep 1

nohup "$ROOT/scripts/start_hub_tunnel.sh" >>"$ROOT/logs/hub_tunnel.log" 2>&1 &
echo "Tunnel starting… log: $ROOT/logs/hub_tunnel.log"
sleep 4
curl -sS -o /tmp/hub_domain_health.json -w "hub.realxtateth.com HTTP %{http_code}\n" --max-time 30 "https://hub.realxtateth.com/api/health" || true
head -c 200 /tmp/hub_domain_health.json; echo
