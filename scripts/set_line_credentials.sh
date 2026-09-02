#!/bin/bash
# ใส่ LINE credentials ลง .env แล้ว (ออปชัน) สตาร์ทบอท+tunnel
set -e
cd "$(dirname "$0")/.." || exit 1

SECRET="${1:-}"
TOKEN="${2:-}"

if [ -z "$SECRET" ] || [ -z "$TOKEN" ]; then
  echo "用法: bash scripts/set_line_credentials.sh '<CHANNEL_SECRET>' '<CHANNEL_ACCESS_TOKEN>'"
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
fi

python3 - <<PY
from pathlib import Path
root = Path(".")
path = root / ".env"
text = path.read_text(encoding="utf-8")
secret = """${SECRET}"""
token = """${TOKEN}"""

def upsert(text, key, value):
    lines = text.splitlines()
    out, found = [], False
    for line in lines:
        if line.startswith(key + "="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    return "\n".join(out) + "\n"

text = upsert(text, "LINE_CHANNEL_SECRET", secret)
text = upsert(text, "LINE_CHANNEL_ACCESS_TOKEN", token)
path.write_text(text, encoding="utf-8")
print("บันทึก LINE credentials ลง .env แล้ว")
PY

bash scripts/run_line_bot_tunnel.sh
