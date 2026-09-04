#!/usr/bin/env bash
# Z10 internal pilot — isolated E2E / local dev (no sheet sync, no production).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${HUB_PORT:-8765}"
E2E_DIR="${PANTIP_E2E_DATA_ROOT:-${ROOT}/.local/phase_z10_e2e}"

mkdir -p "${E2E_DIR}"
if [ ! -f "${E2E_DIR}/projects.json" ]; then
  cp "${ROOT}/data/projects.json" "${E2E_DIR}/projects.json"
fi
if [ ! -f "${E2E_DIR}/properties.json" ]; then
  echo '[]' > "${E2E_DIR}/properties.json"
fi

export HUB_LOCAL_DEV=1
export HUB_SKIP_PREVIEW_BOOT=1
export HUB_AUTO_SYNC_TO_SHEET=0
export HUB_ALLOW_SHEET_PULL=0
export HUB_STARTUP_SHEET_SYNC=0
export PANTIP_E2E_DATA_ROOT="${E2E_DIR}"
export Z8_PILOT_MODE=1
export Z7_PILOT_MODE=1

echo "Starting Z10 internal pilot (isolated E2E data: ${E2E_DIR})"
echo "  Hub: http://127.0.0.1:${PORT}/"
echo "  Recheck panel: ฟอโล่ว → ติดตามทรัพย์เก่า"
echo ""

cd "${ROOT}"
export PORT="${PORT}"
exec python3 scripts/hub_server.py
