#!/usr/bin/env bash
# Point LINE webhook → Hub on Fly (rich menu replies only). Stop Mac line-bot.
# Does NOT touch LivingBKK / apex realxtateth.com.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.fly/bin:${PATH}"

APP="${FLY_APP:-property-hub}"
HUB_DOMAIN="${HUB_DOMAIN:-hub.realxtateth.com}"
WEBHOOK="https://${HUB_DOMAIN}/line/webhook"

get_env() {
  local key="$1"
  grep -E "^${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//'
}

SECRET="$(get_env LINE_CHANNEL_SECRET)"
TOKEN="$(get_env LINE_CHANNEL_ACCESS_TOKEN)"
if [[ -z "$SECRET" || -z "$TOKEN" ]]; then
  echo "❌ ต้องมี LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN ใน .env"
  exit 1
fi

echo "=== Push LINE secrets to Fly ($APP) ==="
fly secrets set -a "$APP" \
  "LINE_CHANNEL_SECRET=${SECRET}" \
  "LINE_CHANNEL_ACCESS_TOKEN=${TOKEN}" \
  "LINE_MENU_WEBHOOK=1"

echo "=== Wait for Hub LINE health ==="
ok=0
for _ in $(seq 1 30); do
  if curl -sf "https://${HUB_DOMAIN}/line/health" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('enabled') else 1)"; then
    ok=1
    break
  fi
  sleep 3
done
if [[ "$ok" != "1" ]]; then
  echo "❌ Hub /line/health ยังไม่พร้อม — deploy ก่อนแล้วค่อยรันสคริปต์นี้ใหม่"
  curl -sS "https://${HUB_DOMAIN}/line/health" || true
  exit 1
fi
curl -sS "https://${HUB_DOMAIN}/line/health" | python3 -c "import sys,json; d=json.load(sys.stdin); print('chatMode=', d.get('chat_mode'), 'triggers=', len(d.get('menu_triggers') or []))"

echo "=== Set LINE webhook → ${WEBHOOK} ==="
python3 - <<PY
import json, urllib.request
token = """${TOKEN}"""
webhook = """${WEBHOOK}"""

def call(method, url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", errors="replace")

st, _ = call("PUT", "https://api.line.me/v2/bot/channel/webhook/endpoint", {"endpoint": webhook})
print(f"  set endpoint: ok status={st}")
try:
    st, body = call("POST", "https://api.line.me/v2/bot/channel/webhook/test", {})
    print(f"  verify: {body or st}")
except Exception as e:
    detail = getattr(e, "read", lambda: b"")()
    print(f"  verify: {e} {detail[:200] if isinstance(detail, bytes) else detail}")

req = urllib.request.Request(
    "https://api.line.me/v2/bot/info",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(req, timeout=15) as r:
    info = json.loads(r.read().decode())
mode = info.get("chatMode")
print(f"OA chatMode={mode}")
if mode == "chat":
    print("⚠️  ตั้ง Response mode = Bot ที่ manager.line.biz → Response settings")
    print("   (ตอนนี้ Hub ใช้ push fallback เมื่อ chatMode=chat)")
PY

echo "=== Stop Mac LINE bot LaunchAgent ==="
bash "$ROOT/scripts/stop_line_bot.sh" || true
# Prevent auto-restart on login
PLIST="$HOME/Library/LaunchAgents/com.realxtate.line-bot.plist"
if [[ -f "$PLIST" ]]; then
  /usr/libexec/PlistBuddy -c "Set :RunAtLoad false" "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Set :KeepAlive false" "$PLIST" 2>/dev/null || true
fi

echo ""
echo "✅ Rich menu replies → ${WEBHOOK} (Fly / no Mac)"
echo "ทดสอบ: กดปุ่มเมนูบน LINE เช่น 「รับคูปองล้างแอร์」"
echo "ตรวจ: curl -s https://${HUB_DOMAIN}/line/health"
