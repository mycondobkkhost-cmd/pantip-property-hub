"""Reorganize NEW「ชีตสำหรับทำงาน」from OLD using trust-column mapping.

Read-only OLD → write NEW only. Never edits OLD.

Rules:
  - ลิ้งค์โพส / ลิ้งค์โพส Pages → copy as-is (trust 100%)
  - ลิ้งค์ต้นโพสต์ Q: URL→ต้นทาง; non-URL text→หมายเหตุ (clear Q)
  - blank R: URL→เฟสเจ้าของ if empty; else notes; text→หมายเหตุ (clear R)
  - หมายเหตุ from OLD always merged with rescued Q/R/owner text
  - Delete row when post OR pages is Google Drive/Docs URL
  - Strip Drive from other fields without deleting when post/pages are real
  - Preserve NEW ทำเล (and enriched สถานี) by code when present
  - Rebuild Hub + sync「ทรัพย์รวม」(full stock, no archive cutoff)

Usage:
  .venv/bin/python scripts/reorg_sheet_from_old.py
  .venv/bin/python scripts/reorg_sheet_from_old.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.hub.env_load import load_hub_env  # noqa: E402

load_hub_env()

from src.hub.link_classify import is_google_helper_url  # noqa: E402
from src.hub.owner_facebook import adjacent_column_index, cell_has_value  # noqa: E402
from src.hub.sheet_links import (  # noqa: E402
    http_url_or_empty,
    link_col_indexes,
    merge_formula_and_formatted,
    unwrap_link_cell,
)
from src.hub.sheet_write import _gspread_client  # noqa: E402
from src.hub.trust_map import (  # noqa: E402
    TrustMappedRow,
    notes_column_index,
    trust_map_row,
)

OLD_SHEET_ID = "1MuP_bXKOZ0kBRZtBKyG79v7Z438i81LROEgKfDLMdiE"
NEW_SHEET_ID = "1UUJFSj069k0XuPDWRJILYRes40amuQRxGpcGChITNjc"
TAB = "ชีตสำหรับทำงาน"
TALAE_HEADER = "ทำเล"
STATION_HEADER = "สถานีรถไฟฟ้า"


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


def _norm_code(raw: str) -> str:
    return (raw or "").upper().replace(" ", "").strip()


def _is_drive(url: str) -> bool:
    return is_google_helper_url(url or "")


def _enrichment_by_code(new_rows: list[list[str]]) -> dict[str, dict[str, str]]:
    """Preserve NEW ทำเล / สถานี per code when already enriched."""
    if not new_rows:
        return {}
    headers = new_rows[0]
    talea_i = None
    station_i = None
    for i, h in enumerate(headers):
        hs = (h or "").strip()
        if hs == TALAE_HEADER:
            talea_i = i
        elif hs == STATION_HEADER:
            station_i = i
    if talea_i is None and station_i is None:
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in new_rows[1:]:
        code = _norm_code(row[0] if row else "")
        if not code.startswith("PTP"):
            continue
        talea = ""
        if talea_i is not None and talea_i < len(row):
            talea = str(row[talea_i] or "").strip()
        station = ""
        if station_i is not None and station_i < len(row):
            station = str(row[station_i] or "").strip()
        if talea or station:
            out[code] = {"ทำเล": talea, "สถานีรถไฟฟ้า": station}
    return out


def _ensure_header_structure(
    headers: list[str],
    *,
    want_talea: bool,
) -> list[str]:
    """OLD headers through เฟสเจ้าของ; optionally insert ทำเล before สถานี."""
    out = list(headers)
    own_i = None
    src_i = None
    for i, h in enumerate(out):
        hs = (h or "").strip()
        if hs == "เฟสเจ้าของ":
            own_i = i
        elif hs == "ลิ้งค์ต้นโพสต์":
            src_i = i
    if own_i is not None:
        out = out[: own_i + 1]
    if src_i is not None and own_i is not None:
        src_i = next(i for i, h in enumerate(out) if (h or "").strip() == "ลิ้งค์ต้นโพสต์")
        own_i = next(i for i, h in enumerate(out) if (h or "").strip() == "เฟสเจ้าของ")
        if own_i == src_i + 1:
            out.insert(src_i + 1, "")
        elif own_i > src_i + 1:
            mid = out[src_i + 1 : own_i]
            if not any((h or "").strip() for h in mid):
                out = out[: src_i + 1] + [""] + out[own_i:]
    if want_talea and TALAE_HEADER not in [(h or "").strip() for h in out]:
        if STATION_HEADER in [(h or "").strip() for h in out]:
            insert_at = next(
                i for i, h in enumerate(out) if (h or "").strip() == STATION_HEADER
            )
            out.insert(insert_at, TALAE_HEADER)
        else:
            out.append(TALAE_HEADER)
    return out


def _strip_drive_helpers(mapped: TrustMappedRow, stats: Counter) -> TrustMappedRow:
    """Drop Drive URLs from source/owner; leave post/pages for junk detection."""
    source = mapped.source
    owner = mapped.owner
    if source and _is_drive(source):
        source = ""
        stats["drive_stripped_source"] += 1
    if owner and _is_drive(owner):
        owner = ""
        stats["drive_stripped_owner"] += 1
    return TrustMappedRow(
        code=mapped.code,
        source=source,
        owner=owner,
        post=mapped.post,
        pages=mapped.pages,
        notes=mapped.notes,
        adjacent="",
        owner_action=mapped.owner_action if owner else "empty",
        clear_adjacent=True,
        clear_source_text=mapped.clear_source_text,
        text_to_notes=list(mapped.text_to_notes),
    )


def build_cleaned_rows(
    old_rows: list[list[str]],
    *,
    enrich_by_code: dict[str, dict[str, str]] | None = None,
    want_talea: bool = False,
) -> tuple[list[list[str]], dict[str, TrustMappedRow], Counter, list[str]]:
    if not old_rows:
        raise RuntimeError("OLD sheet empty")
    old_headers = list(old_rows[0])
    new_headers = _ensure_header_structure(old_headers, want_talea=want_talea)
    enrich_by_code = enrich_by_code or {}

    payload: list[list[str]] = [list(new_headers)]
    by_code: dict[str, TrustMappedRow] = {}
    stats: Counter = Counter()
    deleted_codes: list[str] = []

    old_name_to_i = {(h or "").strip(): i for i, h in enumerate(old_headers) if (h or "").strip()}
    new_name_to_i = {(h or "").strip(): i for i, h in enumerate(new_headers) if (h or "").strip()}

    for row in old_rows[1:]:
        mapped = trust_map_row(old_headers, row)
        code = mapped.code

        # Drive junk: post OR pages is Drive/Docs → drop entire row
        if _is_drive(mapped.post) or _is_drive(mapped.pages):
            stats["drive_deleted"] += 1
            if code.startswith("PTP"):
                deleted_codes.append(code)
                stats["drive_deleted_ptp"] += 1
            continue

        mapped = _strip_drive_helpers(mapped, stats)

        cleaned = [""] * len(new_headers)

        for name, new_i in new_name_to_i.items():
            if name in ("ลิ้งค์โพส", "ลิ้งค์โพส Pages", "ลิ้งค์ต้นโพสต์", "เฟสเจ้าของ", "หมายเหตุ"):
                continue
            old_i = old_name_to_i.get(name)
            if old_i is None:
                continue
            val = row[old_i] if old_i < len(row) else ""
            cleaned[new_i] = str(val or "")

        if new_headers and (new_headers[0] or "").strip() in ("", "รหัสทรัพย์"):
            cleaned[0] = row[0] if row else ""

        new_cols = link_col_indexes(new_headers)
        new_adj = adjacent_column_index(new_headers)
        new_notes = notes_column_index(new_headers)

        def _set(idx: int | None, val: str) -> None:
            if idx is None:
                return
            cleaned[idx] = val or ""

        _set(new_cols.get("post"), mapped.post)
        _set(new_cols.get("pages"), mapped.pages)
        _set(new_cols.get("source"), mapped.source)  # URL only; text cleared
        _set(new_cols.get("owner"), mapped.owner)
        _set(new_notes, mapped.notes)
        if new_adj is not None:
            cleaned[new_adj] = ""

        if code.startswith("PTP") and code in enrich_by_code:
            enr = enrich_by_code[code]
            if TALAE_HEADER in new_name_to_i and enr.get("ทำเล"):
                cleaned[new_name_to_i[TALAE_HEADER]] = enr["ทำเล"]
                stats["preserved_talea"] += 1
            if STATION_HEADER in new_name_to_i and enr.get("สถานีรถไฟฟ้า"):
                cleaned[new_name_to_i[STATION_HEADER]] = enr["สถานีรถไฟฟ้า"]
                stats["preserved_station"] += 1

        payload.append(cleaned)
        stats["rows_written"] += 1

        if mapped.text_to_notes:
            stats["text_to_notes_rows"] += 1
            stats["text_to_notes_fragments"] += len(mapped.text_to_notes)

        if code.startswith("PTP"):
            stats["ptp_rows"] += 1
            by_code[code] = mapped
            if mapped.owner_action == "already_owner":
                stats["owner_from_fase"] += 1
            elif mapped.owner_action == "from_adjacent":
                stats["owner_from_r"] += 1
            else:
                stats["owner_empty"] += 1
            if mapped.source:
                stats["has_source"] += 1
            if mapped.post:
                stats["has_post"] += 1
            if mapped.pages:
                stats["has_pages"] += 1
            if mapped.owner:
                stats["has_owner"] += 1
            if mapped.notes:
                stats["has_notes"] += 1
        else:
            stats["non_ptp"] += 1

    return payload, by_code, stats, deleted_codes


def write_new_sheet(
    *,
    sheet_id: str,
    payload: list[list[str]],
    dry_run: bool = False,
) -> dict:
    if dry_run:
        return {"ok": True, "dry_run": True, "rows": len(payload)}

    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    ws = ss.worksheet(TAB)

    width = max(len(r) for r in payload)
    padded = [list(r) + [""] * (width - len(r)) for r in payload]

    need_rows = len(padded) + 10
    need_cols = width + 2
    if ws.row_count < need_rows or ws.col_count < need_cols:
        ws.resize(
            rows=max(ws.row_count, need_rows),
            cols=max(ws.col_count, need_cols),
        )
        time.sleep(1.0)

    try:
        ss.batch_update(
            {
                "requests": [
                    {
                        "unmergeCells": {
                            "range": {
                                "sheetId": ws.id,
                                "startRowIndex": 0,
                                "endRowIndex": 1,
                                "startColumnIndex": 13,
                                "endColumnIndex": min(width + 1, 25),
                            }
                        }
                    }
                ]
            }
        )
        time.sleep(0.5)
    except Exception as exc:
        print(f"  unmerge header warn: {exc}", flush=True)

    print("  clearing NEW tab…", flush=True)
    ws.clear()
    time.sleep(1.0)

    chunk_rows = 500
    written = 0
    end_col = _col_letter(width)
    for i in range(0, len(padded), chunk_rows):
        part = padded[i : i + chunk_rows]
        start = i + 1
        end = i + len(part)
        rng = f"A{start}:{end_col}{end}"
        ws.update(values=part, range_name=rng, raw=True)
        written += len(part)
        print(f"  wrote rows {start}-{end} ({written}/{len(padded)})", flush=True)
        time.sleep(0.8)

    headers = padded[0]
    for idx, h in enumerate(headers):
        hs = (h or "").strip()
        if hs in ("เฟสเจ้าของ", "ลิ้งค์ต้นโพสต์", "ลิ้งค์โพส", "ลิ้งค์โพส Pages", "หมายเหตุ", TALAE_HEADER):
            a1 = f"{_col_letter(idx + 1)}1"
            ws.update(values=[[hs]], range_name=a1, raw=True)

    col_a = ws.col_values(1)
    ptp = [
        c
        for c in col_a[1:]
        if str(c).upper().replace(" ", "").startswith("PTP")
    ]
    return {
        "ok": True,
        "dry_run": False,
        "rows_written": written,
        "ptp_rows": len(ptp),
        "ptp_unique": len({c.upper().replace(" ", "") for c in ptp}),
        "headers": headers,
    }


def fill_rates(stats: Counter) -> dict:
    n = max(int(stats.get("ptp_rows", 0)), 1)

    def pct(key: str) -> dict:
        filled = int(stats.get(key, 0))
        return {
            "filled": filled,
            "total": int(stats.get("ptp_rows", 0)),
            "pct": round(100.0 * filled / n, 1),
        }

    return {
        "ptp_rows": int(stats.get("ptp_rows", 0)),
        "owner_from_fase": int(stats.get("owner_from_fase", 0)),
        "owner_from_r": int(stats.get("owner_from_r", 0)),
        "owner_empty": int(stats.get("owner_empty", 0)),
        "text_to_notes_rows": int(stats.get("text_to_notes_rows", 0)),
        "text_to_notes_fragments": int(stats.get("text_to_notes_fragments", 0)),
        "drive_deleted": int(stats.get("drive_deleted", 0)),
        "drive_deleted_ptp": int(stats.get("drive_deleted_ptp", 0)),
        "owner_fill": pct("has_owner"),
        "source_fill": pct("has_source"),
        "post_fill": pct("has_post"),
        "pages_fill": pct("has_pages"),
        "notes_fill": pct("has_notes"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--old-sheet-id", default=OLD_SHEET_ID)
    ap.add_argument("--new-sheet-id", default=NEW_SHEET_ID)
    ap.add_argument("--tab", default=TAB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-living", action="store_true")
    ap.add_argument("--skip-rebuild", action="store_true")
    ap.add_argument("--skip-overview", action="store_true")
    args = ap.parse_args()

    report: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}

    print("=== 1) Read OLD「ชีตสำหรับทำงาน」(read-only) ===", flush=True)
    old_rows = _pull_merged(args.old_sheet_id, args.tab)
    print(f"OLD rows (incl header): {len(old_rows)}", flush=True)
    if len(old_rows) < 2:
        raise RuntimeError("OLD sheet appears empty — aborting")

    print("=== 2) Snapshot NEW enrichments (ทำเล/สถานี) ===", flush=True)
    new_before = _pull_merged(args.new_sheet_id, args.tab)
    enrich = _enrichment_by_code(new_before)
    want_talea = bool(enrich) or any(
        (h or "").strip() == TALAE_HEADER for h in (new_before[0] if new_before else [])
    )
    print(
        json.dumps(
            {
                "new_rows": len(new_before),
                "codes_with_enrichment": len(enrich),
                "want_talea_col": want_talea,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    print("=== 3) Build cleaned rows (trust mapping + Drive delete) ===", flush=True)
    payload, by_code, stats, deleted_codes = build_cleaned_rows(
        old_rows,
        enrich_by_code=enrich,
        want_talea=want_talea,
    )
    rates = fill_rates(stats)
    print(json.dumps({"stats": dict(stats), "rates": rates}, ensure_ascii=False, indent=2), flush=True)
    report["mapping"] = {
        "stats": dict(stats),
        "rates": rates,
        "drive_deleted_sample": deleted_codes[:30],
        "drive_deleted_total": len(deleted_codes),
    }

    spot = {}
    for code in ("PTP8200", "PTP8201", "PTP8202"):
        m = by_code.get(code)
        if m:
            spot[code] = {
                "source": m.source,
                "owner": m.owner,
                "notes": m.notes,
                "text_to_notes": m.text_to_notes,
                "post": (m.post or "")[:60],
            }
    report["spot_check"] = spot
    print(json.dumps({"spot_check": spot}, ensure_ascii=False, indent=2), flush=True)

    print("=== 4) Write NEW「ชีตสำหรับทำงาน」===")
    write_result = write_new_sheet(
        sheet_id=args.new_sheet_id,
        payload=payload,
        dry_run=args.dry_run,
    )
    print(json.dumps(write_result, ensure_ascii=False, indent=2), flush=True)
    report["write"] = write_result

    report_path = BASE_DIR / "data" / "reorg_sheet_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        print("Dry-run only — NEW sheet / Hub unchanged.", flush=True)
        print(f"Wrote {report_path}", flush=True)
        return

    os.environ["SOURCE_GOOGLE_SHEETS_ID"] = args.new_sheet_id
    os.environ["MAIN_GOOGLE_SHEETS_ID"] = args.new_sheet_id
    os.environ["HUB_GOOGLE_SHEETS_ID"] = args.new_sheet_id
    os.environ["GOOGLE_SHEETS_ID"] = args.new_sheet_id

    if not args.skip_living:
        print("=== 5) Re-apply Living ทำเล/สถานี from projects.json ===", flush=True)
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "apply_living_locations_to_sheet",
            BASE_DIR / "scripts" / "apply_living_locations_to_sheet.py",
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        living = mod.apply_to_work_sheet(dry_run=False)
        report["living"] = {
            k: v
            for k, v in living.items()
            if k not in ("headers_before", "headers_after", "sample_talea", "sample_station")
        }
        print(json.dumps(report["living"], ensure_ascii=False, indent=2), flush=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.skip_rebuild:
        print("=== 6) Rebuild Hub from NEW sheet ===", flush=True)
        from src.hub.sheet_sync import refresh_main_sheet

        summary = refresh_main_sheet(rebuild=True)
        report["rebuild"] = summary.get("stats") or summary
        print(json.dumps(report["rebuild"], ensure_ascii=False, indent=2), flush=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.skip_overview:
        print("=== 7) Sync「ทรัพย์รวม」===")
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
            "overview_rows": ov.get("overview_rows")
            or ov.get("written_count")
            or ov.get("overview_count"),
            "active_for_overview": active_n,
            "spreadsheet_url": ov.get("spreadsheet_url"),
            "warnings": ov.get("warnings"),
        }
        print(json.dumps(report["overview"], ensure_ascii=False, indent=2), flush=True)

    print("=== 8) Final verify NEW sheet ===", flush=True)
    final_rows = _pull_merged(args.new_sheet_id, args.tab)
    headers = final_rows[0]
    cols = link_col_indexes(headers)
    adj_i = adjacent_column_index(headers)
    notes_i = notes_column_index(headers)
    verify = Counter()
    adj_still = 0
    source_text_left = 0
    spot_final = {}
    for row in final_rows[1:]:
        code = _norm_code(row[0] if row else "")
        if not code.startswith("PTP"):
            continue
        verify["ptp"] += 1
        src = unwrap_link_cell(
            row[cols["source"]] if cols.get("source") is not None and cols["source"] < len(row) else ""
        )
        own = unwrap_link_cell(
            row[cols["owner"]] if cols.get("owner") is not None and cols["owner"] < len(row) else ""
        )
        post = unwrap_link_cell(
            row[cols["post"]] if cols.get("post") is not None and cols["post"] < len(row) else ""
        )
        pages = unwrap_link_cell(
            row[cols["pages"]] if cols.get("pages") is not None and cols["pages"] < len(row) else ""
        )
        notes = ""
        if notes_i is not None and notes_i < len(row):
            notes = str(row[notes_i] or "").strip()
        if src:
            verify["source"] += 1
            if not http_url_or_empty(src):
                source_text_left += 1
        if own:
            verify["owner"] += 1
        if post:
            verify["post"] += 1
        if pages:
            verify["pages"] += 1
        if notes:
            verify["notes"] += 1
        if adj_i is not None and adj_i < len(row) and cell_has_value(row[adj_i]):
            adj_still += 1
        if code in ("PTP8200", "PTP8201", "PTP8202"):
            spot_final[code] = {"source": src, "owner": own, "notes": notes}
    n = max(verify["ptp"], 1)
    report["final_verify"] = {
        "ptp": verify["ptp"],
        "source_pct": round(100.0 * verify["source"] / n, 1),
        "owner_pct": round(100.0 * verify["owner"] / n, 1),
        "post_pct": round(100.0 * verify["post"] / n, 1),
        "pages_pct": round(100.0 * verify["pages"] / n, 1),
        "notes_pct": round(100.0 * verify["notes"] / n, 1),
        "notes_filled": verify["notes"],
        "adjacent_r_still_filled": adj_still,
        "source_non_url_left": source_text_left,
        "text_to_notes_rows": rates["text_to_notes_rows"],
        "text_to_notes_fragments": rates["text_to_notes_fragments"],
        "drive_deleted": rates["drive_deleted"],
        "spot_final": spot_final,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["final_verify"], ensure_ascii=False, indent=2), flush=True)
    print(f"Wrote {report_path}", flush=True)
    print("=== DONE ===", flush=True)


if __name__ == "__main__":
    main()
