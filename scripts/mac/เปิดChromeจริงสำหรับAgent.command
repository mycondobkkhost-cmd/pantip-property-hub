#!/bin/bash
# เปิด Google Chrome จริงตามโปรไฟล์ที่เลือกใน Hub
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1

xattr -d com.apple.quarantine "$0" 2>/dev/null || true
clear
echo "========================================"
echo "  เปิด Chrome จริง สำหรับ Agent"
echo "========================================"
echo ""

# ใช้ token จากไฟล์เปิดระบบ ถ้ามีใน env
export HUB_URL="${HUB_URL:-https://hub.realxtateth.com}"
export COMMENT_AGENT_ID="${COMMENT_AGENT_ID:-owner}"
export FB_CDP_PORT="${FB_CDP_PORT:-9222}"

# ถ้ามีไฟล์เปิดระบบในเครื่อง ดึง token มาให้ (ไม่บังคับ)
if [ -z "$COMMENT_AGENT_TOKEN" ] && [ -f "$ROOT/scripts/mac/เปิดระบบคอมเมนต์.command" ]; then
  TOKEN_LINE=$(grep -E '^COMMENT_AGENT_TOKEN=' "$ROOT/scripts/mac/เปิดระบบคอมเมนต์.command" | head -1 || true)
  if [ -n "$TOKEN_LINE" ]; then
    eval "$TOKEN_LINE"
    export COMMENT_AGENT_TOKEN
  fi
  ID_LINE=$(grep -E '^COMMENT_AGENT_ID=' "$ROOT/scripts/mac/เปิดระบบคอมเมนต์.command" | head -1 || true)
  if [ -n "$ID_LINE" ]; then
    eval "$ID_LINE"
    export COMMENT_AGENT_ID
  fi
fi

PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "ไม่พบ Python3"
  read -r -p "กด Enter เพื่อปิด…"
  exit 1
fi

"$PY" "$ROOT/scripts/launch_chrome_for_agent.py" \
  --hub "$HUB_URL" \
  --token "${COMMENT_AGENT_TOKEN:-}" \
  --agent "${COMMENT_AGENT_ID:-owner}" \
  --port "${FB_CDP_PORT:-9222}"
code=$?
echo ""
read -r -p "กด Enter เพื่อปิดหน้าต่างนี้ (Chrome ยังเปิดอยู่)…"
exit "$code"
