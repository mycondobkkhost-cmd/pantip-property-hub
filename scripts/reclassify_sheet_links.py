#!/usr/bin/env python3
"""Full horizontal reclassify of property links: OLD sheet → NEW sheet + Hub.

1. Read ALL rows from OLD「ชีตสำหรับทำงาน」(source of truth for links)
2. Classify every URL in each row into ต้นทาง / เจ้าของ / ที่โพสต์ / เพจ
3. Drive/Docs/Sheets → delete code + row from NEW sheet (+ Hub on rebuild)
4. Write cleaned link cols + notes onto NEW「ชีตสำหรับทำงาน」
5. Rebuild master / preview from NEW
6. Sync「ทรัพย์รวม」

Usage:
  .venv/bin/python scripts/reclassify_sheet_links.py
  .venv/bin/python scripts/reclassify_sheet_links.py --dry-run
  .venv/bin/python scripts/reclassify_sheet_links.py --no-overview --no-rebuild
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.hub.env_load import load_hub_env  # noqa: E402

load_hub_env()

from src.hub.link_classify import (  # noqa: E402
    ClassifiedRow,
    adjacent_dump_indexes,
    classify_row,
    is_living_url,
    notes_column_index,
)
from src.hub.sheet_links import link_col_indexes, merge_formula_and_formatted  # noqa: E402
from src.hub.sheet_write import _gspread_client  # noqa: E402

OLD_SHEET_ID = "1MuP_bXKOZ0kBRZtBKyG79v7Z438i81LROEgKfDLMdiE"
NEW_SHEET_ID = "1UUJFSj069k0XuPDWRJILYRes40amuQRxGpcGChITNjc"
TAB = "ชีตสำหรับทำงาน"


def _col_letter(n: int) -> str:
    """1-based column index → A1 letter."""
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _pull_merged(sheet_id: str, tab: str) -> list[list[str]]:
    client = _gspread_client()
    ws = client.open_by_key(sheet_id).worksheet(tab)
    try:
        formula = ws.get_all_values(value_render_option="FORMULA")
        formatted = ws.get_all_values(value_render_option="FORMATTED_VALUE")
        return merge_formula_and_formatted(formula, formatted)
    except TypeError:
        return ws.get_all_values()


def _classify_all(rows: list[list[str]]) -> tuple[dict[str, ClassifiedRow], Counter]:
    headers = rows[0]
    by_code: dict[str, ClassifiedRow] = {}
    stats: Counter = Counter()
    for row in rows[1:]:
        code = (row[0] if row else "").upper().replace(" ", "").strip()
        if not code.startswith("PTP"):
            stats["non_ptp"] += 1
            continue
        stats["scanned"] += 1
        classified = classify_row(headers, row)
        # First occurrence wins (sheet may have rare dup codes)
        if code not in by_code:
            by_code[code] = classified
        if classified.delete:
            stats["delete_drive"] += 1
        else:
            stats["keep"] += 1
            if classified.source:
                stats["keep_with_source"] += 1
                if is_living_url(classified.source):
                    stats["keep_source_living"] += 1
                else:
                    stats["keep_source_fb"] += 1
            if classified.owner:
                stats["keep_with_owner"] += 1
            if classified.post:
                stats["keep_with_post"] += 1
            if classified.pages:
                stats["keep_with_pages"] += 1
            for field, role in classified.moved_from.items():
                stats[f"moved_{field}_from_{role}"] += 1
    return by_code, stats


def _fill_rates(by_code: dict[str, ClassifiedRow]) -> dict:
    kept = [c for c in by_code.values() if not c.delete]
    fb_rows = [
        c
        for c in kept
        if c.source and not is_living_url(c.source)
    ]
    living_rows = [c for c in kept if c.source and is_living_url(c.source)]
    n = max(len(kept), 1)
    n_fb = max(len(fb_rows), 1)
    n_liv = max(len(living_rows), 1)

    def rate(rows: list[ClassifiedRow], attr: str) -> dict:
        filled = sum(1 for r in rows if getattr(r, attr))
        return {
            "filled": filled,
            "total": len(rows),
            "pct": round(100.0 * filled / max(len(rows), 1), 1),
        }

    return {
        "kept_rows": len(kept),
        "owner_all_kept": rate(kept, "owner"),
        "owner_fb_sourced": rate(fb_rows, "owner"),
        "owner_living_sourced": rate(living_rows, "owner"),
        "source_all_kept": rate(kept, "source"),
        "post_all_kept": rate(kept, "post"),
        "pages_all_kept": rate(kept, "pages"),
        "fb_sourced_rows": len(fb_rows),
        "living_sourced_rows": len(living_rows),
        "_n": n,
        "_n_fb": n_fb,
        "_n_liv": n_liv,
    }


def apply_to_new_sheet(
    *,
    sheet_id: str,
    by_code: dict[str, ClassifiedRow],
    dry_run: bool = False,
) -> dict:
    client = _gspread_client()
    ws = client.open_by_key(sheet_id).worksheet(TAB)
    try:
        formula = ws.get_all_values(value_render_option="FORMULA")
        formatted = ws.get_all_values(value_render_option="FORMATTED_VALUE")
        rows = merge_formula_and_formatted(formula, formatted)
    except TypeError:
        rows = ws.get_all_values()

    if not rows:
        raise RuntimeError("NEW sheet empty")

    headers = rows[0]
    cols = link_col_indexes(headers)
    notes_i = notes_column_index(headers)
    dump_idxs = adjacent_dump_indexes(headers)

    required = ("post", "pages", "source", "owner")
    missing = [k for k in required if cols.get(k) is None]
    if missing:
        raise RuntimeError(f"NEW sheet missing columns: {missing} headers={headers!r}")

    updates: list[tuple[str, str]] = []
    delete_row_nums: list[int] = []
    stats: Counter = Counter()
    samples = {
        "reclassified": [],
        "deleted": [],
        "owner_filled": [],
    }

    for row_num, row in enumerate(rows[1:], start=2):
        code = (row[0] if row else "").upper().replace(" ", "").strip()
        if not code.startswith("PTP"):
            stats["new_non_ptp"] += 1
            continue
        stats["new_ptp"] += 1
        classified = by_code.get(code)
        if classified is None:
            # Reclassify from NEW itself if OLD lacked the code
            classified = classify_row(headers, row)
            stats["classified_from_new"] += 1

        if classified.delete:
            delete_row_nums.append(row_num)
            stats["to_delete"] += 1
            if len(samples["deleted"]) < 8:
                samples["deleted"].append(code)
            continue

        stats["to_update"] += 1
        mapping = {
            cols["source"]: classified.source,
            cols["owner"]: classified.owner,
            cols["post"]: classified.post,
            cols["pages"]: classified.pages,
        }
        if notes_i is not None:
            mapping[notes_i] = classified.notes

        changed = False
        for col_i, new_val in mapping.items():
            old_val = (row[col_i] if col_i < len(row) else "") or ""
            # Compare unwrapped-ish plain text
            if old_val.strip() != (new_val or "").strip():
                a1 = f"{_col_letter(col_i + 1)}{row_num}"
                updates.append((a1, new_val or ""))
                changed = True

        # Clear dump/adjacent columns (misplaced URLs moved into proper cols)
        for col_i in dump_idxs:
            old_val = (row[col_i] if col_i < len(row) else "") or ""
            if old_val.strip():
                a1 = f"{_col_letter(col_i + 1)}{row_num}"
                updates.append((a1, ""))
                changed = True
                stats["cleared_dump_cells"] += 1

        if changed:
            stats["rows_changed"] += 1
            if classified.moved_from and len(samples["reclassified"]) < 8:
                samples["reclassified"].append(
                    {
                        "code": code,
                        "source": (classified.source or "")[:80],
                        "owner": (classified.owner or "")[:80],
                        "post": (classified.post or "")[:80],
                        "pages": (classified.pages or "")[:80],
                        "moved": classified.moved_from,
                    }
                )
            if classified.owner and len(samples["owner_filled"]) < 8:
                if classified.moved_from.get("owner"):
                    samples["owner_filled"].append(
                        {
                            "code": code,
                            "owner": classified.owner[:100],
                            "from": classified.moved_from.get("owner"),
                        }
                    )

    applied = 0
    deleted = 0
    if not dry_run:
        # 1) Write link/notes updates in chunks
        chunk = 400
        for i in range(0, len(updates), chunk):
            part = updates[i : i + chunk]
            body = [{"range": a1, "values": [[val]]} for a1, val in part]
            ws.batch_update(body, value_input_option="USER_ENTERED")
            applied += len(part)
            time.sleep(0.4)

        # 2) Delete drive rows bottom → top (preserve indices)
        # Merge contiguous ranges for fewer API calls
        if delete_row_nums:
            delete_row_nums = sorted(set(delete_row_nums))
            ranges: list[tuple[int, int]] = []
            start = end = delete_row_nums[0]
            for n in delete_row_nums[1:]:
                if n == end + 1:
                    end = n
                else:
                    ranges.append((start, end))
                    start = end = n
            ranges.append((start, end))

            for start, end in sorted(ranges, key=lambda x: -x[0]):
                # gspread delete_rows is inclusive start..end
                ws.delete_rows(start, end)
                deleted += end - start + 1
                time.sleep(0.8)

    return {
        "ok": True,
        "dry_run": dry_run,
        "update_cells": len(updates),
        "applied_cells": applied,
        "delete_rows_planned": len(delete_row_nums),
        "deleted_rows": deleted,
        "stats": dict(stats),
        "samples": samples,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old-sheet-id", default=OLD_SHEET_ID)
    ap.add_argument("--new-sheet-id", default=NEW_SHEET_ID)
    ap.add_argument("--tab", default=TAB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true")
    ap.add_argument("--no-overview", action="store_true")
    args = ap.parse_args()

    print("=== 1) Read OLD sheet ===")
    old_rows = _pull_merged(args.old_sheet_id, args.tab)
    print(f"OLD rows (incl header): {len(old_rows)}")

    print("=== 2) Classify ===")
    by_code, class_stats = _classify_all(old_rows)
    rates = _fill_rates(by_code)
    print(json.dumps({"classify": dict(class_stats), "rates": rates}, ensure_ascii=False, indent=2))

    report_path = BASE_DIR / "data" / "link_reclassify_report.json"
    report = {
        "classify_stats": dict(class_stats),
        "fill_rates": rates,
        "delete_codes": sorted(c for c, r in by_code.items() if r.delete),
        "samples_keep": [],
    }
    for c in by_code.values():
        if c.delete:
            continue
        if c.moved_from and len(report["samples_keep"]) < 15:
            report["samples_keep"].append(
                {
                    "code": c.code,
                    "source": c.source,
                    "owner": c.owner,
                    "post": c.post,
                    "pages": c.pages,
                    "moved": c.moved_from,
                    "notes": (c.notes or "")[:120],
                }
            )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {report_path}")

    print("=== 3) Write NEW sheet ===")
    write_result = apply_to_new_sheet(
        sheet_id=args.new_sheet_id,
        by_code=by_code,
        dry_run=args.dry_run,
    )
    print(
        json.dumps(
            {k: v for k, v in write_result.items() if k != "samples"},
            ensure_ascii=False,
            indent=2,
        )
    )
    print("--- samples ---")
    print(json.dumps(write_result.get("samples") or {}, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("Dry-run only — NEW sheet / Hub unchanged.")
        return

    # Point env at NEW sheet for rebuild/overview
    import os

    os.environ["SOURCE_GOOGLE_SHEETS_ID"] = args.new_sheet_id
    os.environ["MAIN_GOOGLE_SHEETS_ID"] = args.new_sheet_id
    os.environ["HUB_GOOGLE_SHEETS_ID"] = args.new_sheet_id
    os.environ["GOOGLE_SHEETS_ID"] = args.new_sheet_id

    if not args.no_rebuild:
        print("=== 4) Rebuild Hub from NEW sheet ===")
        from src.hub.sheet_sync import refresh_main_sheet

        summary = refresh_main_sheet(rebuild=True)
        print(json.dumps(summary.get("stats") or summary, ensure_ascii=False, indent=2))
        report["rebuild"] = summary.get("stats") or summary
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.no_overview:
        print("=== 5) Sync「ทรัพย์รวม」===")
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
        report["overview"] = {
            "ok": ov.get("ok"),
            "overview_rows": ov.get("overview_rows"),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== DONE ===")
    print(
        json.dumps(
            {
                "scanned": class_stats["scanned"],
                "deleted_drive": class_stats["delete_drive"],
                "kept": class_stats["keep"],
                "owner_fill_fb_sourced_pct": rates["owner_fb_sourced"]["pct"],
                "owner_fill_all_kept_pct": rates["owner_all_kept"]["pct"],
                "source_pct": rates["source_all_kept"]["pct"],
                "post_pct": rates["post_all_kept"]["pct"],
                "pages_pct": rates["pages_all_kept"]["pct"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
