#!/usr/bin/env bash
# Local-only master definition review (Phase Z4). Skips heavy preview-data boot.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HUB_PORT:-8765}"

export HUB_LOCAL_DEV=1
export HUB_SKIP_PREVIEW_BOOT=1
export MASTER_REVIEW_PILOT_MODE=1

echo "Starting master definition review pilot..."
echo "  URL: http://127.0.0.1:${PORT}/master-definition-review/"
echo "  Login: local demo account (HUB_LOCAL_DEV)"
echo ""

cd "${ROOT}"
export PORT="${PORT}"
exec python3 scripts/hub_server.py
