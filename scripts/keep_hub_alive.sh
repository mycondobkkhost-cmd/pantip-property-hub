#!/bin/bash
# Keep Property Hub (:8765) alive — restart with project .env applied.
cd "$(dirname "$0")/.."
mkdir -p logs

PY="python3"
if [ -x .venv/bin/python ]; then
  PY=".venv/bin/python"
fi

FAILS=0

port_listening() {
  lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1
}

free_port() {
  local pids
  pids=$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pids" ]; then
    kill $pids 2>/dev/null || true
    sleep 1
    pids=$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$pids" ]; then
      kill -9 $pids 2>/dev/null || true
      sleep 1
    fi
  fi
  pkill -f "scripts/hub_server.py" 2>/dev/null || true
}

load_dotenv_into_shell() {
  # Prefer python dotenv — .env may contain characters that break `source`.
  if [ ! -f .env ]; then
    return 0
  fi
  eval "$("$PY" - <<'PY'
from dotenv import dotenv_values
from shlex import quote
vals = dotenv_values(".env") or {}
for k, v in vals.items():
    if k and v is not None:
        print(f"export {k}={quote(str(v))}")
PY
)"
}

while true; do
  if curl -sf --max-time 8 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    FAILS=0
  else
    FAILS=$((FAILS + 1))
    # During sheet refresh health may be slow — don't kill if port still listens.
    if port_listening; then
      echo "$(date '+%F %T') health slow but :8765 still listening (fail=$FAILS)" >> logs/hub_keepalive.log
      FAILS=0
    elif [ "$FAILS" -lt 3 ]; then
      echo "$(date '+%F %T') health miss $FAILS/3" >> logs/hub_keepalive.log
    else
      echo "$(date '+%F %T') restart hub_server after $FAILS misses" >> logs/hub_keepalive.log
      free_port
      unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
      set -a
      load_dotenv_into_shell
      set +a
      PYTHONUNBUFFERED=1 nohup "$PY" scripts/hub_server.py >> logs/hub_server.log 2>&1 &
      FAILS=0
      sleep 5
    fi
  fi
  sleep 10
done
