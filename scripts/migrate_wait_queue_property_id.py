#!/usr/bin/env python3
"""Z13.8 — dry-run / apply wait_post_queue property_id backfill.

Usage:
  python3 scripts/migrate_wait_queue_property_id.py --dry-run
  python3 scripts/migrate_wait_queue_property_id.py --apply

Never prints private notes/contacts. Never touches properties.json.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.hub.queue_store import backfill_queue_property_ids, queue_path  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill wait_post_queue.property_id safely")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    path = queue_path()
    if not path.is_file():
        print(json.dumps({"ok": False, "error": f"missing {path}"}, ensure_ascii=False))
        return 2

    backup = ""
    if args.apply:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = str(path.with_name(path.name + f".bak_z13_8_{ts}"))
        shutil.copy2(path, backup)

    summary = backfill_queue_property_ids(dry_run=bool(args.dry_run))
    summary["ok"] = True
    summary["queue_path"] = str(path)
    if backup:
        summary["backup"] = backup
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
