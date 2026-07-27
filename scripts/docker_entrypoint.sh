#!/bin/sh
# Seed Fly volume at /app/data from image copy without overwriting existing files.
set -e
SEED="${DATA_SEED_DIR:-/app/data_seed}"
DATA="${DATA_DIR:-/app/data}"
mkdir -p "$DATA"
if [ -d "$SEED" ]; then
  # -n: do not overwrite existing volume files
  cp -an "$SEED"/. "$DATA"/ 2>/dev/null || true
fi
exec python3 scripts/hub_server.py
