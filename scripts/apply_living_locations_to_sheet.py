#!/usr/bin/env python3
"""Apply Living-verified ทำเล + สถานี onto「ชีตสำหรับทำงาน」and re-sync「ทรัพย์รวม」.

- Ensures a ทำเล column exists on the main work sheet (inserts before สถานีรถไฟฟ้า if missing)
- Updates ทำเล + สถานีรถไฟฟ้า from project master (verified Living preferred)
- Does not wipe unrelated columns
- Optionally pushes overview tab via sheet_write.push_hub_properties_to_sheet
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass

from src.hub.project_store import (  # noqa: E402
    load_projects,
    load_properties,
    project_location_label,
    project_transit_display,
)
from src.hub.sheet_write import (  # noqa: E402
    _gspread_client,
    push_hub_properties_to_sheet,
)

DEFAULT_SHEET_ID = "1UUJFSj069k0XuPDWRJILYRes40amuQRxGpcGChITNjc"
MAIN_SHEET_NAME = "ชีตสำหรับทำงาน"
TALAE_HEADER = "ทำเล"
STATION_HEADER = "สถานีรถไฟฟ้า"
PROJECT_HEADER = "โครงการ"


def _col_letter(idx0: int) -> str:
    n = idx0 + 1
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def apply_to_work_sheet(*, dry_run: bool = False) -> dict:
    sheet_id = (
        os.environ.get("SOURCE_GOOGLE_SHEETS_ID")
        or os.environ.get("GOOGLE_SHEETS_ID")
        or DEFAULT_SHEET_ID
    )
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    ws = ss.worksheet(MAIN_SHEET_NAME)

    values = ws.get_all_values()
    if not values:
        raise RuntimeError("work sheet empty")
    headers = list(values[0])
    stats: dict = {
        "sheet_id": sheet_id,
        "rows": len(values) - 1,
        "headers_before": list(headers),
        "inserted_talea": False,
        "updated_rows": 0,
        "cleared_station_seo": 0,
        "matched_projects": 0,
        "unmatched_projects": 0,
        "dry_run": dry_run,
    }

    # Ensure ทำเล column exists (insert immediately before สถานีรถไฟฟ้า)
    if TALAE_HEADER not in headers:
        if STATION_HEADER in headers:
            insert_at = headers.index(STATION_HEADER)
        else:
            insert_at = len(headers)
        if not dry_run:
            ws.insert_cols([[]], col=insert_at + 1)
            ws.update_cell(1, insert_at + 1, TALAE_HEADER)
        headers.insert(insert_at, TALAE_HEADER)
        # also patch in-memory rows
        for i in range(1, len(values)):
            row = values[i]
            while len(row) < insert_at:
                row.append("")
            row.insert(insert_at, "")
        stats["inserted_talea"] = True
        # re-fetch if we mutated sheet structure
        if not dry_run:
            values = ws.get_all_values()
            headers = list(values[0])

    stats["headers_after"] = list(headers)
    col_project = headers.index(PROJECT_HEADER) if PROJECT_HEADER in headers else None
    col_talea = headers.index(TALAE_HEADER) if TALAE_HEADER in headers else None
    col_station = headers.index(STATION_HEADER) if STATION_HEADER in headers else None
    if col_project is None or col_talea is None or col_station is None:
        raise RuntimeError(f"missing required columns: {headers}")

    projects = load_projects()
    # Map by soft-normalized project name / aliases
    from src.hub.project_identity import soft_norm

    by_name: dict[str, dict] = {}
    for proj in projects:
        for label in [proj.get("canonical_name") or ""] + list(proj.get("aliases") or []):
            k = soft_norm(label)
            if k and k not in by_name:
                by_name[k] = proj
        bucket = proj.get("bucket_key") or ""
        if bucket and bucket not in by_name:
            by_name[bucket] = proj

    # Also map via properties.project_id for exact sheet project strings
    props = load_properties()
    name_to_pid: dict[str, str] = {}
    for p in props:
        pn = soft_norm(p.get("project_name") or "")
        if pn and p.get("project_id"):
            name_to_pid.setdefault(pn, p["project_id"])
    projects_by_id = {p["id"]: p for p in projects}

    talea_updates: list[list] = []
    station_updates: list[list] = []
    for ridx, row in enumerate(values[1:], start=2):
        while len(row) <= max(col_project, col_talea, col_station):
            row.append("")
        pname = (row[col_project] or "").strip()
        if not pname:
            continue
        key = soft_norm(pname)
        proj = by_name.get(key)
        if not proj and key in name_to_pid:
            proj = projects_by_id.get(name_to_pid[key])
        if not proj:
            stats["unmatched_projects"] += 1
            continue
        stats["matched_projects"] += 1

        # Prefer Living/verified display; skip projects still pending with empty zone
        zone = project_location_label(proj)
        transit = ", ".join(project_transit_display(proj)[:3])
        if not zone and not transit:
            continue

        old_station = (row[col_station] or "").strip()
        old_zone = (row[col_talea] or "").strip()
        changed = False
        if zone and zone != old_zone:
            talea_updates.append({"row": ridx, "value": zone})
            changed = True
        if transit and transit != old_station:
            station_updates.append({"row": ridx, "value": transit})
            changed = True
            # count SEO cleanup when old was a long blob
            if old_station and ("," in old_station or "/" in old_station) and old_station.count(",") >= 2:
                stats["cleared_station_seo"] += 1
        if changed:
            stats["updated_rows"] += 1

    if dry_run:
        stats["sample_talea"] = talea_updates[:8]
        stats["sample_station"] = station_updates[:8]
        return stats

    # Batch write by column using USER_ENTERED
    def _batch_col(col_idx0: int, items: list[dict]) -> None:
        if not items:
            return
        # group contiguous ranges for fewer API calls — write cell-by-cell in chunks of 500
        letter = _col_letter(col_idx0)
        chunk_size = 400
        for i in range(0, len(items), chunk_size):
            chunk = items[i : i + chunk_size]
            data = [
                {
                    "range": f"'{MAIN_SHEET_NAME}'!{letter}{it['row']}",
                    "values": [[it["value"]]],
                }
                for it in chunk
            ]
            ws.spreadsheet.values_batch_update(
                {"valueInputOption": "USER_ENTERED", "data": data}
            )

    _batch_col(col_talea, talea_updates)
    _batch_col(col_station, station_updates)
    stats["talea_cells"] = len(talea_updates)
    stats["station_cells"] = len(station_updates)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-overview", action="store_true")
    ap.add_argument("--work-only", action="store_true", help="Only update ชีตสำหรับทำงาน")
    args = ap.parse_args()

    work = apply_to_work_sheet(dry_run=args.dry_run)
    out: dict = {"work_sheet": work}
    if not args.work_only and not args.skip_overview and not args.dry_run:
        out["overview"] = push_hub_properties_to_sheet()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
