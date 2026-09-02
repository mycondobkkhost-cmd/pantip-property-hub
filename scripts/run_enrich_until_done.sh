#!/usr/bin/env bash
# Chunked watchdog: enrich 25 at a time until remaining=0, then sheet + Fly.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.fly/bin:${HOME}/bin:${PATH}"
PY="${ROOT}/.venv/bin/python"
LOG="${ROOT}/logs/project_sheet_enrich_20260727_full.log"
PROG_JSON="${ROOT}/logs/project_enrich_progress.json"
PROG_LOG="${ROOT}/logs/project_enrich_progress.log"
MAX_ROUNDS="${MAX_ROUNDS:-80}"
CHUNK="${CHUNK:-25}"
STALE_SEC="${STALE_SEC:-120}"
ROUND_TIMEOUT="${ROUND_TIMEOUT:-300}"

mkdir -p logs
echo "===== WATCHDOG CHUNKED $(date) =====" | tee -a "$LOG" | tee -a "$PROG_LOG"

remaining() {
  "$PY" - <<'PY'
import sys
sys.path.insert(0, ".")
from scripts.sync_merged_projects_sheet_enrich import select_targets, _priority_project_ids
from src.hub.project_store import load_projects
items = load_projects()
keep, _ = _priority_project_ids()
targets = select_targets(
    items,
    keep_ids=keep,
    max_projects=0,
    include_incomplete=True,
    include_rest=True,
    skip_complete=True,
    skip_attempted=True,
)
print(len(targets))
PY
}

kill_enrich() {
  pkill -9 -f 'scripts/sync_merged_projects_sheet_enrich.py' 2>/dev/null || true
}

for round in $(seq 1 "$MAX_ROUNDS"); do
  n="$(remaining)"
  echo "[watchdog] round=$round remaining=$n chunk=$CHUNK $(date)" | tee -a "$LOG" | tee -a "$PROG_LOG"
  if [[ "$n" -eq 0 ]]; then
    echo "[watchdog] targets=0 — enrich done" | tee -a "$LOG"
    break
  fi

  kill_enrich
  sleep 1

  # PropertyHub-only for long-tail (Living hangs caused stalls). Small chunk.
  "$PY" -u scripts/sync_merged_projects_sheet_enrich.py \
    --include-rest --skip-complete --skip-attempted \
    --max-projects "$CHUNK" --sleep 0.25 --checkpoint-every 5 \
    --skip-living --skip-sheet --skip-backup \
    >> "$LOG" 2>&1 &
  EPID=$!
  echo "[watchdog] started pid=$EPID max=$CHUNK" | tee -a "$LOG"

  start_ts=$(date +%s)
  last_prog_mtime=0
  [[ -f "$PROG_JSON" ]] && last_prog_mtime=$(stat -f %m "$PROG_JSON" 2>/dev/null || echo 0)

  while kill -0 "$EPID" 2>/dev/null; do
    now=$(date +%s)
    elapsed=$((now - start_ts))
    if [[ "$elapsed" -ge "$ROUND_TIMEOUT" ]]; then
      echo "[watchdog] ROUND_TIMEOUT — kill $EPID" | tee -a "$LOG"
      kill -9 "$EPID" 2>/dev/null || true
      kill_enrich
      break
    fi
    if [[ -f "$PROG_JSON" ]]; then
      mtime=$(stat -f %m "$PROG_JSON" 2>/dev/null || echo 0)
      if [[ "$mtime" -gt "$last_prog_mtime" ]]; then
        last_prog_mtime=$mtime
      elif [[ "$last_prog_mtime" -gt 0 && $((now - last_prog_mtime)) -ge "$STALE_SEC" ]]; then
        echo "[watchdog] STALE ${STALE_SEC}s — kill $EPID" | tee -a "$LOG"
        kill -9 "$EPID" 2>/dev/null || true
        kill_enrich
        break
      fi
    fi
    sleep 10
  done
  wait "$EPID" 2>/dev/null || true
  echo "[watchdog] round=$round ended remaining=$(remaining) $(date)" | tee -a "$LOG"
  sleep 1
done

n="$(remaining)"
echo "[watchdog] final remaining=$n" | tee -a "$LOG" | tee -a "$PROG_LOG"

echo "[watchdog] sheet + full persist" | tee -a "$LOG"
"$PY" -u scripts/sync_merged_projects_sheet_enrich.py --sheet-only --skip-backup 2>&1 | tee -a "$LOG"

echo "[watchdog] Fly volume sync" | tee -a "$LOG"
if command -v fly >/dev/null 2>&1; then
  printf '%s\n' \
    'cd /app/data' \
    "put ${ROOT}/data/projects.json projects.json" \
    "put ${ROOT}/data/properties.json properties.json" \
    "put ${ROOT}/data/zone_master.json zone_master.json" \
    "put ${ROOT}/data/transit_master.json transit_master.json" \
    "put ${ROOT}/data/preview-data.js preview-data.js" \
    "put ${ROOT}/data/preview-data.meta.json preview-data.meta.json" \
    'bye' \
    | fly ssh sftp shell -a property-hub 2>&1 | tee -a "$LOG" \
    || echo "[watchdog] fly sftp failed (non-fatal)" | tee -a "$LOG"
else
  echo "[watchdog] fly CLI missing" | tee -a "$LOG"
fi

"$PY" - <<'PY'
import sys
sys.path.insert(0, ".")
from scripts.sync_merged_projects_sheet_enrich import write_progress, _is_fully_enriched, _coverage_counts
from src.hub.project_store import load_projects
items = load_projects()
c = sum(1 for p in items if _is_fully_enriched(p))
write_progress(batch_done=0, batch_total=0, batch_start_complete=c, projects=items, remaining_hint=0)
print("FINAL", _coverage_counts(items))
PY

echo "[watchdog] ALL DONE $(date)" | tee -a "$LOG" | tee -a "$PROG_LOG"
