#!/usr/bin/env python3
"""Emergency restore: copy ALL「ชีตสำหรับทำงาน」rows from OLD → NEW, then careful reclassify.

Does NOT edit OLD. Restores codes wiped by Drive false-positive deletion.
Drive helper URLs are stripped from link fields; rows are deleted ONLY when
Drive-only junk (Drive URL and no Facebook/Living listing links).

Usage:
  .venv/bin/python scripts/restore_sheet_from_old.py
  .venv/bin/python scripts/restore_sheet_from_old.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.hub.env_load import load_hub_env  # noqa: E402

load_hub_env()

import importlib.util  # noqa: E402

from src.hub.sheet_links import merge_formula_and_formatted  # noqa: E402
from src.hub.sheet_write import _gspread_client  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "reclassify_sheet_links",
    BASE_DIR / "scripts" / "reclassify_sheet_links.py",
)
_reclass = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_reclass)
_classify_all = _reclass._classify_all
_fill_rates = _reclass._fill_rates
apply_to_new_sheet = _reclass.apply_to_new_sheet
_col_letter = _reclass._col_letter

OLD_SHEET_ID = "1MuP_bXKOZ0kBRZtBKyG79v7Z438i81LROEgKfDLMdiE"
NEW_SHEET_ID = "1UUJFSj069k0XuPDWRJILYRes40amuQRxGpcGChITNjc"
TAB = "ชีตสำหรับทำงาน"


def _pull_formula_preferred(sheet_id: str, tab: str) -> list[list[str]]:
    """Prefer FORMULA cells so HYPERLINK(...) survives the copy."""
    client = _gspread_client()
    ws = client.open_by_key(sheet_id).worksheet(tab)
    try:
        formula = ws.get_all_values(value_render_option="FORMULA")
        formatted = ws.get_all_values(value_render_option="FORMATTED_VALUE")
        return merge_formula_and_formatted(formula, formatted)
    except TypeError:
        return ws.get_all_values()


def _ptp_stats(rows: list[list[str]]) -> dict:
    codes = []
    for row in rows[1:]:
        code = (row[0] if row else "").upper().replace(" ", "").strip()
        if code.startswith("PTP"):
            codes.append(code)
    return {
        "rows_incl_header": len(rows),
        "ptp_rows": len(codes),
        "ptp_unique": len(set(codes)),
    }


def restore_all_rows(
    *,
    old_sheet_id: str,
    new_sheet_id: str,
    tab: str,
    dry_run: bool = False,
) -> dict:
    print("=== 1) Read OLD「ชีตสำหรับทำงาน」(source of truth) ===", flush=True)
    old_rows = _pull_formula_preferred(old_sheet_id, tab)
    old_stats = _ptp_stats(old_rows)
    print(json.dumps(old_stats, ensure_ascii=False), flush=True)
    if len(old_rows) < 2:
        raise RuntimeError("OLD sheet appears empty — aborting")

    print("=== 2) Snapshot NEW before restore ===", flush=True)
    client = _gspread_client()
    new_ws = client.open_by_key(new_sheet_id).worksheet(tab)
    try:
        new_before = new_ws.get_all_values(value_render_option="FORMULA")
    except TypeError:
        new_before = new_ws.get_all_values()
    before_stats = _ptp_stats(new_before)
    print(json.dumps(before_stats, ensure_ascii=False), flush=True)

    missing = set()
    old_codes = {
        (r[0] if r else "").upper().replace(" ", "").strip()
        for r in old_rows[1:]
        if (r[0] if r else "").upper().replace(" ", "").strip().startswith("PTP")
    }
    new_codes = {
        (r[0] if r else "").upper().replace(" ", "").strip()
        for r in new_before[1:]
        if (r[0] if r else "").upper().replace(" ", "").strip().startswith("PTP")
    }
    missing = old_codes - new_codes
    print(f"Codes in OLD missing from NEW: {len(missing)}", flush=True)

    # Pad rows to uniform width for batch update
    width = max(len(r) for r in old_rows)
    payload = [list(r) + [""] * (width - len(r)) for r in old_rows]

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "old": old_stats,
            "new_before": before_stats,
            "codes_to_restore": len(missing),
            "sample_missing": sorted(missing)[:20],
        }

    print("=== 3) Replace NEW tab with full OLD values ===", flush=True)
    # Ensure grid is large enough
    need_rows = len(payload) + 10
    need_cols = width + 2
    if new_ws.row_count < need_rows or new_ws.col_count < need_cols:
        new_ws.resize(
            rows=max(new_ws.row_count, need_rows),
            cols=max(new_ws.col_count, need_cols),
        )
        time.sleep(1.0)

    # Unmerge header link-dump cells (R1:S1 etc.) so「เฟสเจ้าของ」can be written.
    ss = client.open_by_key(new_sheet_id)
    try:
        ss.batch_update(
            {
                "requests": [
                    {
                        "unmergeCells": {
                            "range": {
                                "sheetId": new_ws.id,
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 16,
                                "endColumnIndex": 21,
                            }
                        }
                    }
                ]
            }
        )
        time.sleep(0.5)
    except Exception as exc:
        print(f"  unmerge header warn: {exc}", flush=True)

    # Clear existing content then write in chunks (Sheets API limits)
    new_ws.clear()
    time.sleep(1.0)

    chunk_rows = 500
    written = 0
    end_col = _col_letter(width)
    for i in range(0, len(payload), chunk_rows):
        part = payload[i : i + chunk_rows]
        start = i + 1
        end = i + len(part)
        rng = f"A{start}:{end_col}{end}"
        # raw=True preserves plain URLs / headers (avoids merge + USER_ENTERED quirks)
        new_ws.update(values=part, range_name=rng, raw=True)
        written += len(part)
        print(f"  wrote rows {start}-{end} ({written}/{len(payload)})", flush=True)
        time.sleep(0.8)

    # Ensure owner header exists even if trailing empties were dropped mid-copy
    headers = payload[0]
    for idx, h in enumerate(headers):
        if (h or "").strip() == "เฟสเจ้าของ":
            a1 = f"{_col_letter(idx + 1)}1"
            new_ws.update(values=[[h]], range_name=a1, raw=True)
            break

    # Verify
    col_a = new_ws.col_values(1)
    after_ptp = [
        c
        for c in col_a[1:]
        if str(c).upper().replace(" ", "").startswith("PTP")
    ]
    after_unique = len({c.upper().replace(" ", "") for c in after_ptp})
    after_stats = {
        "ptp_rows": len(after_ptp),
        "ptp_unique": after_unique,
        "a_cells": len(col_a),
    }
    print("=== NEW after copy ===", flush=True)
    print(json.dumps(after_stats, ensure_ascii=False), flush=True)

    return {
        "ok": True,
        "dry_run": False,
        "old": old_stats,
        "new_before": before_stats,
        "new_after_copy": after_stats,
        "codes_restored": len(missing),
        "sample_restored": sorted(missing)[:30],
        "old_rows": old_rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old-sheet-id", default=OLD_SHEET_ID)
    ap.add_argument("--new-sheet-id", default=NEW_SHEET_ID)
    ap.add_argument("--tab", default=TAB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-reclassify", action="store_true")
    ap.add_argument("--skip-rebuild", action="store_true")
    ap.add_argument("--skip-overview", action="store_true")
    args = ap.parse_args()

    report: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    copy_result = restore_all_rows(
        old_sheet_id=args.old_sheet_id,
        new_sheet_id=args.new_sheet_id,
        tab=args.tab,
        dry_run=args.dry_run,
    )
    report["copy"] = {
        k: v for k, v in copy_result.items() if k != "old_rows"
    }
    print(json.dumps(report["copy"], ensure_ascii=False, indent=2), flush=True)

    if args.dry_run:
        print("Dry-run only — NEW sheet unchanged.", flush=True)
        return

    old_rows = copy_result["old_rows"]

    if not args.skip_reclassify:
        print("=== 4) Careful reclassify (strip Drive, no false deletes) ===", flush=True)
        by_code, class_stats = _classify_all(old_rows)
        rates = _fill_rates(by_code)
        delete_codes = sorted(c for c, r in by_code.items() if r.delete)
        print(
            json.dumps(
                {
                    "classify": dict(class_stats),
                    "rates": rates,
                    "delete_drive_only_junk": len(delete_codes),
                    "sample_delete": delete_codes[:20],
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        write_result = apply_to_new_sheet(
            sheet_id=args.new_sheet_id,
            by_code=by_code,
            dry_run=False,
        )
        report["reclassify"] = {
            "classify_stats": dict(class_stats),
            "fill_rates": rates,
            "delete_codes": delete_codes,
            "write": {k: v for k, v in write_result.items() if k != "samples"},
            "samples": write_result.get("samples"),
        }
        print(
            json.dumps(report["reclassify"]["write"], ensure_ascii=False, indent=2),
            flush=True,
        )
    else:
        by_code, class_stats = _classify_all(old_rows)
        report["reclassify"] = {"skipped": True, "classify_stats": dict(class_stats)}

    # Point env at NEW for rebuild/overview
    os.environ["SOURCE_GOOGLE_SHEETS_ID"] = args.new_sheet_id
    os.environ["MAIN_GOOGLE_SHEETS_ID"] = args.new_sheet_id
    os.environ["HUB_GOOGLE_SHEETS_ID"] = args.new_sheet_id
    os.environ["GOOGLE_SHEETS_ID"] = args.new_sheet_id

    if not args.skip_rebuild:
        print("=== 5) Rebuild Hub from restored NEW sheet ===", flush=True)
        from src.hub.sheet_sync import refresh_main_sheet

        summary = refresh_main_sheet(rebuild=True)
        report["rebuild"] = summary.get("stats") or summary
        print(json.dumps(report["rebuild"], ensure_ascii=False, indent=2), flush=True)

    if not args.skip_overview:
        print("=== 6) Sync「ทรัพย์รวม」===")
        from src.hub.sheet_write import (
            active_properties_for_overview,
            push_hub_properties_to_sheet,
        )

        active_n = len(active_properties_for_overview())
        print(f"active_for_overview (pre-push): {active_n}", flush=True)
        ov = push_hub_properties_to_sheet()
        report["overview"] = {
            "ok": ov.get("ok"),
            "via": ov.get("via"),
            "overview_rows": ov.get("overview_rows"),
            "active_for_overview": active_n,
            "spreadsheet_url": ov.get("spreadsheet_url"),
            "warnings": ov.get("warnings"),
        }
        print(json.dumps(report["overview"], ensure_ascii=False, indent=2), flush=True)

    # Final verify counts
    print("=== 7) Final verify ===", flush=True)
    client = _gspread_client()
    new_ws = client.open_by_key(args.new_sheet_id).worksheet(args.tab)
    col_a = new_ws.col_values(1)
    ptp = [
        c
        for c in col_a[1:]
        if str(c).upper().replace(" ", "").startswith("PTP")
    ]
    final_sheet = {
        "ptp_rows": len(ptp),
        "ptp_unique": len({c.upper().replace(" ", "") for c in ptp}),
    }
    try:
        ov_ws = client.open_by_key(args.new_sheet_id).worksheet("ทรัพย์รวม")
        ov_a = ov_ws.col_values(1)
        ov_ptp = [
            c
            for c in ov_a
            if str(c).upper().replace(" ", "").startswith("PTP")
        ]
        final_overview = {"ptp": len(ov_ptp)}
    except Exception as exc:
        final_overview = {"error": str(exc)}

    try:
        src = client.open_by_key(args.new_sheet_id).worksheet("_overview_src")
        src_a = src.col_values(1)
        src_ptp = [
            c
            for c in src_a[1:]
            if str(c).upper().replace(" ", "").startswith("PTP")
        ]
        final_src = {"ptp": len(src_ptp)}
    except Exception as exc:
        final_src = {"error": str(exc)}

    report["final"] = {
        "new_work_sheet": final_sheet,
        "overview": final_overview,
        "overview_src": final_src,
        "rebuild": report.get("rebuild"),
    }
    out = BASE_DIR / "data" / "restore_sheet_report.json"
    # Drop huge samples if needed — already small
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["final"], ensure_ascii=False, indent=2), flush=True)
    print(f"Wrote {out}", flush=True)
    print("=== DONE ===", flush=True)


if __name__ == "__main__":
    main()
