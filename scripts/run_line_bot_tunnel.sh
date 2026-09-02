#!/bin/bash
# เปิด/ตรวจ LINE Bot — ใช้ hostname คงที่ line.realxtateth.com (named tunnel)
# ไม่แตะ hub.realxtateth.com / LivingBKK apex
set -e
cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
mkdir -p logs

get_env() {
  local key="$1"
  grep -E "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//'
}

SECRET="$(get_env LINE_CHANNEL_SECRET)"
TOKEN="$(get_env LINE_CHANNEL_ACCESS_TOKEN)"
PORT="$(get_env LINE_BOT_PORT)"
PORT="${PORT:-8787}"
STABLE_HOST="${LINE_BOT_PUBLIC_HOST:-line.realxtateth.com}"
WEBHOOK="https://${STABLE_HOST}/webhook"
PLIST="$HOME/Library/LaunchAgents/com.realxtate.line-bot.plist"

if [ -z "$SECRET" ] || [ -z "$TOKEN" ]; then
  echo "❌ ยังไม่มี LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN ใน .env"
  echo "รัน: bash scripts/set_line_credentials.sh 'SECRET' 'TOKEN'"
  exit 1
fi

# Ensure LaunchAgent exists (KeepAlive)
if [ ! -f "$PLIST" ]; then
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.realxtate.line-bot</string>
  <key>WorkingDirectory</key><string>${ROOT}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${ROOT}/.venv/bin/python</string>
    <string>-m</string>
    <string>line_bot</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${ROOT}/logs/line_bot.launchd.out.log</string>
  <key>StandardErrorPath</key><string>${ROOT}/logs/line_bot.launchd.err.log</string>
</dict>
</plist>
EOF
fi

# Start / restart via launchd when local health fails
if ! curl -sf "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
  echo "สตาร์ท LINE Bot (LaunchAgent)..."
  launchctl bootout "gui/$(id -u)/com.realxtate.line-bot" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
  for _ in $(seq 1 20); do
    sleep 1
    if curl -sf "http://127.0.0.1:${PORT}/" >/dev/null 2>&1; then
      break
    fi
  done
fi

if ! curl -sf "http://127.0.0.1:${PORT}/" >/dev/null; then
  echo "บอทสตาร์ทไม่สำเร็จ ดู logs/line_bot.launchd.err.log"
  exit 1
fi

if ! curl -sf "https://${STABLE_HOST}/" >/dev/null; then
  echo "⚠️  public https://${STABLE_HOST}/ ยังไม่ตอบ — ตรวจ named tunnel ingress / DNS"
  exit 1
fi

echo "$WEBHOOK" > logs/line_webhook_url.txt
lsof -ti "tcp:${PORT}" | head -1 > logs/line_bot.pid || true

echo "ตั้ง LINE webhook → ${WEBHOOK}"
python3 - <<PY
import json, urllib.request
token = """${TOKEN}"""
webhook = """${WEBHOOK}"""

def call(method, url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", errors="replace")

try:
    st, _ = call("PUT", "https://api.line.me/v2/bot/channel/webhook/endpoint", {"endpoint": webhook})
    print(f"  set: ok status={st}")
except Exception as e:
    detail = getattr(e, "read", lambda: b"")()
    print(f"  set: FAIL {e} {detail[:300] if isinstance(detail, bytes) else detail}")

try:
    # LINE docs: POST /v2/bot/channel/webhook/test
    st, body = call("POST", "https://api.line.me/v2/bot/channel/webhook/test", {})
    print(f"  verify: {body or st}")
except Exception as e:
    detail = getattr(e, "read", lambda: b"")()
    print(f"  verify: FAIL {e} {detail[:300] if isinstance(detail, bytes) else detail}")
PY

echo ""
python3 - <<PY
import json, urllib.request
token = """${TOKEN}"""
try:
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/info",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        info = json.loads(r.read().decode())
    mode = info.get("chatMode")
    print(f"OA: {info.get('displayName')} ({info.get('basicId')}) chatMode={mode}")
    if mode == "chat":
        print("")
        print("⚠️  Response mode ยังเป็น Chat — Messaging API ตอบลูกค้าอาจไม่ขึ้นในแชท")
        print("   ไปที่ https://manager.line.biz/ → Settings → Response settings")
        print("   ตั้ง Response mode = Bot แล้วเปิด Use webhook")
except Exception as e:
    print(f"(ข้ามตรวจ chatMode: {e})")
PY

echo ""
echo "========================================"
echo "✅ LINE Bot พร้อม"
echo "Webhook: ${WEBHOOK}"
echo "ลองกดเมนู Rich Menu เช่น \"รับคูปองล้างแอร์\""
echo "หยุด: bash scripts/stop_line_bot.sh"
echo "========================================"
echo "$(date '+%Y-%m-%d %H:%M:%S') started webhook=${WEBHOOK}" >> logs/ops_workday.log
