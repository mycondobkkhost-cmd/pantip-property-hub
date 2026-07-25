#!/usr/bin/env python3
"""One-shot repair: move misplaced owner Facebook URLs into「เฟสเจ้าของ」.

On「ชีตสำหรับทำงาน」admins often put owner profiles in the blank column
immediately beside「ลิ้งค์ต้นโพสต์」(col R when Q=ลิ้งค์ต้นโพสต์, S=เฟสเจ้าของ)
instead of「เฟสเจ้าของ」.

This script:
  1. Reads the live sheet via Service Account
  2. Resolves owner links conservatively (see src.hub.owner_facebook)
  3. Writes「เฟสเจ้าของ」and clears adjacent/source only when we moved a profile
  4. Optionally refreshes local CSV + rebuilds properties + pushes overview

Usage:
  .venv/bin/python scripts/repair_owner_facebook_links.py
  .venv/bin/python scripts/repair_owner_facebook_links.py --dry-run
  .venv/bin/python scripts/repair_owner_facebook_links.py --no-rebuild --no-overview
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.hub.owner_facebook import (  # noqa: E402
    adjacent_column_index,
    owner_column_index,
    resolve_owner_facebook,
    source_column_index,
)
from src.hub.sheet_write import _gspread_client  # noqa: E402

DEFAULT_SHEET_ID = "1UUJFSj069k0XuPDWRJILYRes40amuQRxGpcGChITNjc"
DEFAULT_TAB = "ชีตสำหรับทำงาน"


def _col_letter(n: int) -> str:
    """1-based column index → A1 letter."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(row: list[str], i: int | None) -> str:
    if i is None or i >= len(row):
        return ""
    return (row[i] or "").strip()


def repair_sheet(
    *,
    sheet_id: str,
    tab: str,
    dry_run: bool = False,
) -> dict:
    client = _gspread_client()
    ws = client.open_by_key(sheet_id).worksheet(tab)
    rows = ws.get_all_values()
    if not rows:
        raise RuntimeError("Sheet is empty")

    headers = rows[0]
    src_i = source_column_index(headers)
    adj_i = adjacent_column_index(headers)
    own_i = owner_column_index(headers)
    if src_i is None or own_i is None:
        raise RuntimeError(
            f"Missing required headers — source={src_i} owner={own_i} headers={headers!r}"
        )

    stats: Counter = Counter()
    # Pending A1 updates: (a1_range, new_value)
    updates: list[tuple[str, str]] = []
    examples: dict[str, list] = {
        "from_adjacent": [],
        "from_adjacent_over_post": [],
        "from_source_profile": [],
        "already_owner": [],
    }

    src_letter = _col_letter(src_i + 1)
    adj_letter = _col_letter(adj_i + 1) if adj_i is not None else ""
    own_letter = _col_letter(own_i + 1)

    for row_num, row in enumerate(rows[1:], start=2):
        code = _cell(row, 0).upper().replace(" ", "")
        if not code.startswith("PTP"):
            stats["non_ptp"] += 1
            continue
        stats["ptp_rows"] += 1

        source = _cell(row, src_i)
        adjacent = _cell(row, adj_i)
        owner = _cell(row, own_i)
        result = resolve_owner_facebook(
            owner_raw=owner,
            adjacent_raw=adjacent,
            source_raw=source,
        )
        stats[result.action] += 1

        if result.action in examples and len(examples[result.action]) < 5:
            examples[result.action].append(
                {
                    "row": row_num,
                    "code": code,
                    "owner": (result.owner or "")[:100],
                    "was_adjacent": adjacent[:80] if adjacent else "",
                    "was_source": source[:80] if source else "",
                }
            )

        if result.action == "already_owner":
            continue
        if result.action == "empty":
            continue

        if result.action in {"from_adjacent", "from_adjacent_over_post"}:
            if not result.owner:
                continue
            updates.append((f"{own_letter}{row_num}", result.owner))
            if result.clear_adjacent and adj_letter:
                updates.append((f"{adj_letter}{row_num}", ""))
            stats["sheet_writes"] += 1
        elif result.action == "from_source_profile":
            if not result.owner:
                continue
            updates.append((f"{own_letter}{row_num}", result.owner))
            if result.clear_source:
                updates.append((f"{src_letter}{row_num}", ""))
            stats["sheet_writes"] += 1

    applied = 0
    if updates and not dry_run:
        # gspread batch_update — chunk to stay under request size limits
        chunk = 400
        for i in range(0, len(updates), chunk):
            part = updates[i : i + chunk]
            body = [
                {"range": a1, "values": [[val]]}
                for a1, val in part
            ]
            ws.batch_update(body, value_input_option="USER_ENTERED")
            applied += len(part)
    elif dry_run:
        applied = 0

    return {
        "ok": True,
        "dry_run": dry_run,
        "sheet_id": sheet_id,
        "tab": tab,
        "columns": {
            "source": f"{src_letter} ({src_i + 1}) ลิ้งค์ต้นโพสต์",
            "adjacent": (
                f"{adj_letter} ({adj_i + 1}) (blank beside source)"
                if adj_i is not None
                else None
            ),
            "owner": f"{own_letter} ({own_i + 1}) เฟสเจ้าของ",
        },
        "stats": dict(stats),
        "update_cells": len(updates),
        "applied_cells": applied,
        "examples": examples,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    ap.add_argument("--tab", default=DEFAULT_TAB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true", help="Skip CSV pull + rebuild")
    ap.add_argument("--no-overview", action="store_true", help="Skip overview sync")
    args = ap.parse_args()

    print("=== repair_owner_facebook_links ===")
    result = repair_sheet(
        sheet_id=args.sheet_id,
        tab=args.tab,
        dry_run=args.dry_run,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "examples"}, ensure_ascii=False, indent=2))
    print("--- examples ---")
    print(json.dumps(result.get("examples") or {}, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("Dry-run only — sheet unchanged.")
        return

    if not args.no_rebuild:
        print("\n=== refresh_main_sheet (pull + rebuild) ===")
        from src.hub.sheet_sync import refresh_main_sheet

        summary = refresh_main_sheet(rebuild=True)
        print(json.dumps(summary.get("stats") or summary, ensure_ascii=False, indent=2))

    if not args.no_overview:
        print("\n=== push overview「ทรัพย์รวม」===")
        from src.hub.sheet_write import push_hub_properties_to_sheet

        ov = push_hub_properties_to_sheet()
        print(
            json.dumps(
                {
                    "ok": ov.get("ok"),
                    "via": ov.get("via"),
                    "overview_rows": ov.get("overview_rows"),
                    "spreadsheet_url": ov.get("spreadsheet_url"),
                    "warnings": ov.get("warnings"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
