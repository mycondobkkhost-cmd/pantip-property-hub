#!/usr/bin/env bash
# Always-on Hub on this Mac (no Render). Keep Mac awake + online.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="$ROOT/bin:$HOME/.fly/bin:$PATH"
mkdir -p "$ROOT/logs" "$HOME/.cloudflared"

# Load .env without printing
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8765}"
export HUB_STARTUP_SHEET_SYNC="${HUB_STARTUP_SHEET_SYNC:-0}"
export HUB_ALLOW_SHEET_PULL="${HUB_ALLOW_SHEET_PULL:-0}"
export HUB_AUTO_SYNC_TO_SHEET="${HUB_AUTO_SYNC_TO_SHEET:-1}"

# Kill stale listener on same port
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  lsof -tiTCP:"$PORT" -sTCP:LISTEN | xargs kill 2>/dev/null || true
  sleep 1
fi

exec python3 "$ROOT/scripts/hub_server.py" >>"$ROOT/logs/hub_local.log" 2>&1
