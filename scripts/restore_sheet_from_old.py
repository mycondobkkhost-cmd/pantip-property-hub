#!/usr/bin/env python3
"""Emergency restore: copy ALL「ชีตสำหรับทำงาน」rows from OLD → NEW, then trust-map.

Does NOT edit OLD. Restores codes wiped by Drive false-positive deletion.
Owner: prefer「เฟสเจ้าของ」; else blank col R beside「ลิ้งค์ต้นโพสต์」.
Does NOT run aggressive URL reclassify.

Prefer ``scripts/reorg_sheet_from_old.py`` for the full agreed reorganization.

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
    "reorg_sheet_from_old",
    BASE_DIR / "scripts" / "reorg_sheet_from_old.py",
)
_reorg = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_reorg)

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

    enrich = _reorg._enrichment_by_code(
        [[str(c) for c in row] for row in new_before] if new_before else []
    )
    want_talea = bool(enrich) or any(
        (str(h) or "").strip() == "ทำเล" for h in (new_before[0] if new_before else [])
    )

    print("=== 3) Build trust-mapped payload from OLD ===", flush=True)
    payload, _by_code, map_stats = _reorg.build_cleaned_rows(
        old_rows,
        enrich_by_code=enrich,
        want_talea=want_talea,
    )
    rates = _reorg.fill_rates(map_stats)
    print(
        json.dumps({"stats": dict(map_stats), "rates": rates}, ensure_ascii=False, indent=2),
        flush=True,
    )

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "old": old_stats,
            "new_before": before_stats,
            "codes_to_restore": len(missing),
            "sample_missing": sorted(missing)[:20],
            "mapping_rates": rates,
        }

    write_result = _reorg.write_new_sheet(
        sheet_id=new_sheet_id,
        payload=payload,
        dry_run=False,
    )
    print("=== NEW after trust-map write ===", flush=True)
    print(json.dumps(write_result, ensure_ascii=False), flush=True)

    return {
        "ok": True,
        "dry_run": False,
        "old": old_stats,
        "new_before": before_stats,
        "new_after_copy": write_result,
        "codes_restored": len(missing),
        "sample_restored": sorted(missing)[:30],
        "mapping_stats": dict(map_stats),
        "mapping_rates": rates,
        "old_rows": old_rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old-sheet-id", default=OLD_SHEET_ID)
    ap.add_argument("--new-sheet-id", default=NEW_SHEET_ID)
    ap.add_argument("--tab", default=TAB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--skip-reclassify",
        action="store_true",
        help="(ignored — trust-map is inline)",
    )
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
    report["copy"] = {k: v for k, v in copy_result.items() if k != "old_rows"}
    print(json.dumps(report["copy"], ensure_ascii=False, indent=2), flush=True)

    if args.dry_run:
        print("Dry-run only — NEW sheet unchanged.", flush=True)
        return

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

    report["final"] = {
        "new_work_sheet": final_sheet,
        "overview": final_overview,
        "rebuild": report.get("rebuild"),
        "mapping_rates": copy_result.get("mapping_rates"),
    }
    out = BASE_DIR / "data" / "restore_sheet_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["final"], ensure_ascii=False, indent=2), flush=True)
    print(f"Wrote {out}", flush=True)
    print("=== DONE ===", flush=True)


if __name__ == "__main__":
    main()
