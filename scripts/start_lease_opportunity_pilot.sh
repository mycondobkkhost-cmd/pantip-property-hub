#!/usr/bin/env bash
# Local-only lease opportunity pilot (Phase Z5). Skips heavy preview-data boot.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HUB_PORT:-8765}"

export HUB_LOCAL_DEV=1
export HUB_SKIP_PREVIEW_BOOT=1
export LEASE_OPPORTUNITY_PILOT_MODE=1

echo "Starting lease opportunity pilot..."
echo "  URL: http://127.0.0.1:${PORT}/lease-opportunities/"
echo "  Login: local demo account (HUB_LOCAL_DEV)"
echo "  Storage: .local/lease_opportunity_phase_z5/ (gitignored)"
echo ""

cd "${ROOT}"
export PORT="${PORT}"
exec python3 scripts/hub_server.py
