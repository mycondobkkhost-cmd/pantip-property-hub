#!/usr/bin/env python3
"""Measure project master + overview ทำเล/transit quality (before/after enrichment)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
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

DEFAULT_SHEET_ID = "1UUJFSj069k0XuPDWRJILYRes40amuQRxGpcGChITNjc"
INCOMPAT = [
    ("BTS อโศก", "MRT พระราม 9"),
    ("BTS อโศก", "ARL มักกะสัน"),
    ("BTS กรุงธนบุรี", "BTS ทองหล่อ"),
    ("BTS เจริญนคร", "BTS ทองหล่อ"),
    ("BTS เจริญนคร", "MRT พระราม 9"),
    ("BTS ตลาดพลู", "BTS ทองหล่อ"),
    ("MRT ศูนย์ประชุมแห่งชาติสิริกิติ์", "BTS ทองหล่อ"),
]


def _source_bucket(src: str) -> str:
    s = (src or "").strip()
    if not s:
        return "empty"
    if s == "livinginsider" or s.startswith("livinginsider+"):
        if "+curated" in s:
            return "livinginsider+curated"
        return "livinginsider"
    if s.startswith("corridor:"):
        return "corridor"
    if s.startswith("override:"):
        return "override"
    return s.split(":")[0]


def measure_projects() -> dict:
    projects = load_projects()
    props = load_properties()
    n = len(projects) or 1
    src = Counter(_source_bucket(p.get("location_source") or "") for p in projects)
    tv = sum(1 for p in projects if p.get("transit_verified"))
    zv = sum(1 for p in projects if p.get("zone_verified"))
    both = sum(1 for p in projects if p.get("transit_verified") and p.get("zone_verified"))
    living_url = sum(1 for p in projects if p.get("living_project_url"))
    ge5 = sum(1 for p in projects if len(p.get("transit_verified") or []) >= 5)
    ge4 = sum(1 for p in projects if len(p.get("transit_verified") or []) >= 4)
    empty_zone = sum(1 for p in projects if not (p.get("zone_verified") or []))
    empty_both = sum(
        1 for p in projects if not (p.get("zone_verified") or []) and not (p.get("transit_verified") or [])
    )

    cluster_hits: dict[str, int] = {}
    cluster_examples: dict[str, list] = defaultdict(list)
    for p in projects:
        tset = set(p.get("transit_verified") or [])
        for a, b in INCOMPAT:
            if a in tset and b in tset:
                key = f"{a} + {b}"
                cluster_hits[key] = cluster_hits.get(key, 0) + 1
                if len(cluster_examples[key]) < 5:
                    cluster_examples[key].append(p.get("canonical_name"))

    # Listing coverage: properties with clean location_ref matching master
    loc_empty = 0
    loc_dirty = 0
    for prop in props:
        loc = str(prop.get("location_ref") or "").strip()
        transit = prop.get("transit_from_sheet") or []
        if not loc:
            loc_empty += 1
        if any(x in loc.upper() for x in ("BTS ", "MRT ", "ARL ")):
            loc_dirty += 1
        if len(transit) >= 5:
            loc_dirty += 1

    gaps = []
    for p in sorted(projects, key=lambda x: -int(x.get("listing_count") or 0)):
        if p.get("transit_verified") or p.get("zone_verified"):
            continue
        if int(p.get("listing_count") or 0) < 1:
            continue
        gaps.append(
            {
                "name": p.get("canonical_name"),
                "listings": p.get("listing_count"),
                "source": p.get("location_source") or "",
                "has_living_url": bool(p.get("living_project_url")),
            }
        )

    return {
        "projects_total": len(projects),
        "properties_total": len(props),
        "pct_transit_verified": round(100 * tv / n, 1),
        "pct_zone_verified": round(100 * zv / n, 1),
        "pct_both_verified": round(100 * both / n, 1),
        "count_transit_verified": tv,
        "count_zone_verified": zv,
        "count_both_verified": both,
        "count_empty_zone": empty_zone,
        "count_empty_both": empty_both,
        "count_living_project_url": living_url,
        "count_stations_ge4": ge4,
        "count_stations_ge5": ge5,
        "source_counts": dict(src),
        "incompatible_clusters": cluster_hits,
        "incompatible_examples": dict(cluster_examples),
        "properties_empty_location_ref": loc_empty,
        "properties_dirty_location_signals": loc_dirty,
        "gaps_unverified_top": gaps[:40],
    }


def measure_overview_sheet() -> dict | None:
    sheet_id = (
        os.environ.get("SOURCE_GOOGLE_SHEETS_ID")
        or os.environ.get("GOOGLE_SHEETS_ID")
        or DEFAULT_SHEET_ID
    )
    try:
        from src.hub.sheet_write import _gspread_client
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    try:
        client = _gspread_client()
        ss = client.open_by_key(sheet_id)
        ws = ss.worksheet("ทรัพย์รวม")
        values = ws.get_all_values()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "sheet_id": sheet_id}

    if not values:
        return {"error": "empty", "sheet_id": sheet_id}
    headers = values[0]
    # Row 1–5 may be search chrome; find header row with ทำเล
    header_row = 0
    for i, row in enumerate(values[:8]):
        if "ทำเล" in row and ("สถานี" in "".join(row) or "โครงการ" in row):
            headers = row
            header_row = i
            break
    col_talea = headers.index("ทำเล") if "ทำเล" in headers else None
    if col_talea is None:
        return {"error": "no_talea_col", "headers": headers, "sheet_id": sheet_id}

    rows = values[header_row + 1 :]
    nonempty = [r for r in rows if any((c or "").strip() for c in r)]
    empty_talea = 0
    for r in nonempty:
        while len(r) <= col_talea:
            r.append("")
        if not (r[col_talea] or "").strip():
            empty_talea += 1
    return {
        "sheet_id": sheet_id,
        "tab": "ทรัพย์รวม",
        "data_rows": len(nonempty),
        "empty_talea": empty_talea,
        "pct_empty_talea": round(100 * empty_talea / max(len(nonempty), 1), 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", action="store_true", help="Also sample ทรัพย์รวม empty ทำเล")
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()
    out = {"projects": measure_projects()}
    if args.sheet:
        out["overview"] = measure_overview_sheet()
    text = json.dumps(out, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
