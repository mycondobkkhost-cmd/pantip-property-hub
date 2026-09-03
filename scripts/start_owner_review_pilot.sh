#!/usr/bin/env bash
# Local-only owner review pilot launcher (Phase Y). No production writes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PHASE_W_SOURCE="${HOME}/Backups/pantip-property-automation/phase-w-crosswalk-20260904T035800Z/live-project-crosswalk.json"
DATA_DIR="${ROOT}/.local/master_review_phase_y"

if [[ ! -f "${PHASE_W_SOURCE}" ]]; then
  echo "ERROR: Phase W source not found: ${PHASE_W_SOURCE}" >&2
  exit 1
fi

mkdir -p "${DATA_DIR}"

export HUB_LOCAL_DEV=1
export MASTER_REVIEW_SOURCE_PATH="${PHASE_W_SOURCE}"
export MASTER_REVIEW_DATA_DIR="${DATA_DIR}"

PORT="${HUB_PORT:-8765}"
echo "Starting local owner review pilot..."
echo "  Source: ${PHASE_W_SOURCE}"
echo "  Decisions: ${DATA_DIR}/master_review_decisions.jsonl"
echo "  URL: http://127.0.0.1:${PORT}/master-review/"
echo ""
echo "เปิดเบราว์เซอร์ → ติ๊ก 'แสดงเฉพาะ Pilot (~8 โครงการ)' แล้วกด กรอง"
echo ""

cd "${ROOT}"
exec python3 scripts/hub_server.py --port "${PORT}"
