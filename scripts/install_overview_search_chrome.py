#!/usr/bin/env python3
"""Install search chrome + FILTER on「ทรัพย์รวม」via Sheets API (no Apps Script).

Uses gold header styling from「ชีตสำหรับทำงาน」(#fbbc04).
Sync data lands on hidden `_overview_src`; A6 FILTER reads C2/C3.

Usage:
  .venv/bin/python scripts/install_overview_search_chrome.py
  .venv/bin/python scripts/install_overview_search_chrome.py --sheet-id ID
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

try:
    from dotenv import load_dotenv

    load_dotenv(BASE / ".env")
except Exception:
    pass

from src.hub.sheet_write import (  # noqa: E402
    OVERVIEW_HEADERS,
    _gspread_client,
    _write_overview_values,
    ensure_overview_search_chrome,
)


DEFAULT_SHEET_ID = "1UUJFSj069k0XuPDWRJILYRes40amuQRxGpcGChITNjc"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--sheet-id",
        default=os.environ.get("HUB_GOOGLE_SHEETS_ID")
        or os.environ.get("GOOGLE_SHEETS_ID")
        or DEFAULT_SHEET_ID,
    )
    ap.add_argument(
        "--tab",
        default=os.environ.get("HUB_OVERVIEW_SHEET_NAME") or "ทรัพย์รวม",
    )
    ap.add_argument(
        "--resync",
        action="store_true",
        help="Also push current app overview rows into _overview_src",
    )
    args = ap.parse_args()

    client = _gspread_client()
    ss = client.open_by_key(args.sheet_id)
    ws = ss.worksheet(args.tab)

    from datetime import datetime

    from src.hub.sheet_write import _worksheet_has_dashboard_chrome

    probe = ws.get("A1:P1") or [[]]
    row1 = [str(c or "").strip() for c in (probe[0] or [])]
    flat_data = row1[:4] == OVERVIEW_HEADERS[:4]
    has_chrome = _worksheet_has_dashboard_chrome(ws)

    existing_rows: list[list] = []
    if flat_data and not has_chrome:
        print("Migrating flat overview data → chrome + _overview_src …", flush=True)
        all_vals = ws.get_all_values()
        if all_vals and all_vals[0][:4] == OVERVIEW_HEADERS[:4]:
            existing_rows = all_vals
        ws.clear()

    synced = datetime.now().strftime("%d/%m/%Y %H:%M")
    ensure_overview_search_chrome(
        ss,
        ws,
        synced_at=synced,
        row_count=max(0, len(existing_rows) - 1) if existing_rows else None,
    )

    if existing_rows:
        meta = _write_overview_values(ws, existing_rows, synced_at=synced, ss=ss)
        print("migrated:", meta, flush=True)
    elif args.resync:
        # Prefer env sheet id for push
        os.environ.setdefault("HUB_GOOGLE_SHEETS_ID", args.sheet_id)
        os.environ.setdefault("HUB_OVERVIEW_SHEET_NAME", args.tab)
        from src.hub.sheet_write import push_hub_properties_to_sheet

        result = push_hub_properties_to_sheet()
        print("resync:", {k: result.get(k) for k in (
            "ok", "pushed", "written_count", "chrome_preserved",
            "data_start_row", "spreadsheet_url",
        )}, flush=True)
    else:
        print(
            "Chrome installed. Existing _overview_src left as-is "
            "(use --resync to refill from app).",
            flush=True,
        )

    print(
        f"Done. Open: https://docs.google.com/spreadsheets/d/{args.sheet_id}/edit#gid={ws.id}",
        flush=True,
    )
    print("Search: C2 = รหัส/โครงการ · C3 = ทำเล/BTS · leave both empty = all", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
