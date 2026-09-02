#!/bin/bash
# หยุด LINE Bot บน Mac (LaunchAgent) — production ใช้ Fly Hub แล้ว
# Webhook: https://hub.realxtateth.com/line/webhook
set -e
cd "$(dirname "$0")/.." || exit 1

PORT="$(grep -E '^LINE_BOT_PORT=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^["'\'']//;s/["'\'']$//')"
PORT="${PORT:-8787}"
PLIST="$HOME/Library/LaunchAgents/com.realxtate.line-bot.plist"

launchctl bootout "gui/$(id -u)/com.realxtate.line-bot" 2>/dev/null || true
launchctl unload "$PLIST" 2>/dev/null || true
if [ -f "$PLIST" ]; then
  /usr/libexec/PlistBuddy -c "Set :RunAtLoad false" "$PLIST" 2>/dev/null || true
  /usr/libexec/PlistBuddy -c "Set :KeepAlive false" "$PLIST" 2>/dev/null || true
fi

if [ -f logs/line_bot.pid ]; then
  kill "$(cat logs/line_bot.pid)" 2>/dev/null || true
  rm -f logs/line_bot.pid
fi
lsof -ti "tcp:${PORT}" | xargs kill -9 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://127.0.0.1:${PORT}" 2>/dev/null || true
pkill -f "python -m line_bot" 2>/dev/null || true

echo "stopped LINE bot (port ${PORT}) — production webhook is on Fly Hub"
echo "$(date '+%Y-%m-%d %H:%M:%S') stopped (fly cutover)" >> logs/ops_workday.log
