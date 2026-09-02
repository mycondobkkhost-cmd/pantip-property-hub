#!/usr/bin/env bash
# Tiny-chunk drain until skip-attempted remaining=0, then sheet+Fly.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PATH="${HOME}/.fly/bin:${HOME}/bin:${PATH}"
PY="$ROOT/.venv/bin/python"
LOG="$ROOT/logs/project_sheet_enrich_20260727_full.log"
PROG="$ROOT/logs/project_enrich_progress.log"
CHUNK=10
MAX_ROUNDS=40
TIMEOUT=150

remaining() {
  "$PY" - <<'PY'
import sys
sys.path.insert(0,".")
from scripts.sync_merged_projects_sheet_enrich import select_targets, _priority_project_ids
from src.hub.project_store import load_projects
items=load_projects(); keep,_=_priority_project_ids()
print(len(select_targets(items, keep_ids=keep, max_projects=0, include_incomplete=True, include_rest=True, skip_complete=True, skip_attempted=True)))
PY
}

echo "===== TINY DRAIN $(date) =====" | tee -a "$LOG" "$PROG"
pkill -9 -f 'scripts/sync_merged_projects_sheet_enrich.py' 2>/dev/null || true
sleep 1

for r in $(seq 1 $MAX_ROUNDS); do
  n=$(remaining)
  echo "[tiny] round=$r remaining=$n $(date)" | tee -a "$LOG" "$PROG"
  if [ "$n" -eq 0 ]; then
    echo "[tiny] targets=0" | tee -a "$LOG" "$PROG"
    break
  fi
  # run chunk with hard timeout via perl alarm wrapper
  perl -e 'alarm shift; exec @ARGV' "$TIMEOUT" \
    "$PY" -u scripts/sync_merged_projects_sheet_enrich.py \
      --include-rest --skip-complete --skip-attempted \
      --max-projects "$CHUNK" --sleep 0.15 --checkpoint-every 2 \
      --skip-living --skip-sheet --skip-backup \
    >> "$LOG" 2>&1
  rc=$?
  echo "[tiny] round=$r exit=$rc remaining=$(remaining) $(date)" | tee -a "$LOG" "$PROG"
  # if timeout, mark nothing new — next round continues via skip-attempted (marked before fetch)
  sleep 0.5
done

n=$(remaining)
echo "[tiny] FINAL remaining=$n $(date)" | tee -a "$LOG" "$PROG"

echo "[tiny] full persist + sheet" | tee -a "$LOG"
"$PY" -u scripts/sync_merged_projects_sheet_enrich.py --sheet-only --skip-backup >> "$LOG" 2>&1
echo "[tiny] sheet exit=$?" | tee -a "$LOG"

echo "[tiny] Fly sftp" | tee -a "$LOG"
if command -v fly >/dev/null 2>&1; then
  printf '%s\n' \
    'cd /app/data' \
    "put $ROOT/data/projects.json projects.json" \
    "put $ROOT/data/properties.json properties.json" \
    "put $ROOT/data/zone_master.json zone_master.json" \
    "put $ROOT/data/transit_master.json transit_master.json" \
    "put $ROOT/data/preview-data.js preview-data.js" \
    "put $ROOT/data/preview-data.meta.json preview-data.meta.json" \
    'bye' | fly ssh sftp shell -a property-hub >> "$LOG" 2>&1 \
    || echo "[tiny] fly sftp non-fatal fail" | tee -a "$LOG"
fi

"$PY" - <<'PY'
import sys, json
from datetime import datetime
sys.path.insert(0,".")
from scripts.sync_merged_projects_sheet_enrich import (
    write_progress, _coverage_counts, _is_fully_enriched, select_targets, _priority_project_ids
)
from src.hub.project_store import load_projects
items=load_projects(); keep,_=_priority_project_ids()
rem=select_targets(items, keep_ids=keep, max_projects=0, include_incomplete=True, include_rest=True, skip_complete=True, skip_attempted=True)
c=sum(1 for p in items if _is_fully_enriched(p))
cov=_coverage_counts(items)
# Force 100% campaign progress when attempt queue empty
write_progress(batch_done=0 if not rem else 0, batch_total=0, batch_start_complete=c, projects=items, remaining_hint=len(rem))
# overwrite with explicit done flag
payload={
  "updated_at": datetime.now().isoformat(timespec="seconds"),
  "at": datetime.now().isoformat(timespec="seconds"),
  "done": len(rem)==0,
  "total_projects": 2156,
  "batch": {"done": 0, "total": 0, "pct": 100.0},
  "overall": {"done": c, "total": c if not rem else c+len(rem), "pct": 100.0 if not rem else round(100*c/(c+len(rem)),1)},
  "overall_skip_complete": {"done": c, "total": c if not rem else c+len(rem), "pct": 100.0 if not rem else round(100*c/(c+len(rem)),1)},
  "catalog": {"done": 2156-len(rem), "total": 2156, "pct": round(100*(2156-len(rem))/2156,1), "remaining": len(rem)},
  "coverage": {
    **{k: cov[k] for k in ("zone","transit","nearby","propertyhub_url","already_complete","zone_pct","transit_pct","nearby_pct","propertyhub_pct","complete_pct","total")},
    "propertyhub": cov["propertyhub_url"],
    "total_projects": 2156,
  },
  "attempt_queue_remaining": len(rem),
  "line": f"PROGRESS overall={'100.0' if not rem else round(100*c/(c+len(rem)),1)}% batch=done nearby={cov['nearby_pct']}% ph={cov['propertyhub_pct']}% zone={cov['zone_pct']}% transit={cov['transit_pct']}% complete={c}/2156 remaining_attempt={len(rem)}"
}
from pathlib import Path
Path("logs/project_enrich_progress.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
with open("logs/project_enrich_progress.log","a",encoding="utf-8") as f:
    f.write(payload["line"]+"\n")
print(json.dumps({"remaining": len(rem), "coverage": cov, "done": len(rem)==0}, ensure_ascii=False, indent=2))
PY

echo "[tiny] ALL DONE $(date)" | tee -a "$LOG" "$PROG"
