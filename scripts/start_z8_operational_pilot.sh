#!/usr/bin/env bash
# Z8 operational dry-run pilot — capacity-controlled follow-up (TEST_ONLY).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HUB_PORT:-8765}"

export HUB_LOCAL_DEV=1
export HUB_SKIP_PREVIEW_BOOT=1
export Z8_PILOT_MODE=1
export Z7_PILOT_MODE=1
export Z6_PILOT_MODE=1
export LEASE_OPPORTUNITY_PILOT_MODE=1

echo "Starting Z8 operational dry-run pilot..."
echo "  Unified follow-up:   http://127.0.0.1:${PORT}/operator-follow-up/"
echo "  Policy review:       http://127.0.0.1:${PORT}/operator-policy-review/"
echo "  Lease capture:       http://127.0.0.1:${PORT}/lease-capture/"
echo "  Listing freshness:   http://127.0.0.1:${PORT}/listing-freshness/"
echo ""

cd "${ROOT}"
export PORT="${PORT}"
exec python3 scripts/hub_server.py
