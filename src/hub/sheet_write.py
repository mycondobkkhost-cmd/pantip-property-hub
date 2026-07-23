"""Push Property Hub listings to the Google Sheet working tabs.

Primary sync target: overview tab「ทรัพย์รวม」(or「ทรัพย์รวม · แอป」) — all active
listings from the app, newest-first.

Secondary: Hub-owned (RXT/COA) rows →「ทรัพย์ Hub」for Apps Script dashboards.

Never writes the Focus tab.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from src.hub.codes import is_hub_owned

BASE_DIR = Path(__file__).resolve().parent.parent.parent
HUB_EXPORT_CSV = BASE_DIR / "data" / "hub_sheet_export.csv"
OVERVIEW_EXPORT_CSV = BASE_DIR / "data" / "hub_overview_export.csv"
PROPERTIES_JSON = BASE_DIR / "data" / "properties.json"

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass

HUB_HEADERS = [
    "รหัสทรัพย์",
    "วันที่รับเข้า",
    "วันที่ว่าง",
    "โครงการ",
    "ประเภท",
    "ห้องนอน/ห้องน้ำ",
    "ขนาด",
    "ชั้น",
    "ราคาเช่า",
    "ราคาขาย",
    "ทำเล",
    "สถานีรถไฟฟ้า",
    "Short-Term",
    "PETS",
    "ลิ้งค์โพส",
    "ลิ้งค์โพส Pages ",
    "หมายเหตุ",
    "ลิ้งค์ต้นโพสต์",
    "เฟสเจ้าของ",
    "แหล่ง",
    "รหัสคู่/อ้างอิง",
    "synced_at",
    "app_id",
]

# Matches「ทรัพย์รวม · แอป」/ ops working view columns
OVERVIEW_HEADERS = [
    "รหัส",
    "ที่มา",
    "วันที่",
    "โครงการ",
    "ประเภท",
    "ห้อง",
    "ตรม.",
    "ชั้น",
    "เช่า",
    "ขาย",
    "ทำเล",
    "สถานี",
    "ต้นทาง",
    "เจ้าของ",
    "ที่โพสต์",
    "เพจ",
]

_FORBIDDEN_TAB_NAMES = {
    "focus",
    "focus🚨",
    "_proj_loc",
}

_TYPE_TH = {
    "condo": "คอนโด",
    "house": "บ้าน",
    "townhouse": "ทาวน์เฮาส์",
    "town home": "ทาวน์เฮาส์",
    "land": "ที่ดิน",
    "ที่ดิน": "ที่ดิน",
    "commercial": "อาคารพาณิชย์",
    "office": "สำนักงาน",
}


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _join_tags(tags) -> str:
    if isinstance(tags, list):
        return ", ".join(str(t) for t in tags if t)
    return str(tags or "").strip()


def _listed_sort_key(prop: dict) -> tuple:
    raw = str(prop.get("last_listed_at") or "").strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if not m:
        return (0, 0, 0, str(prop.get("code") or ""))
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return (y, mo, d, str(prop.get("code") or ""))


def _type_display(raw: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return ""
    mapped = _TYPE_TH.get(s.lower())
    return mapped or s


def _owner_display(prop: dict) -> str:
    owners = prop.get("owner_facebook") or []
    if isinstance(owners, list):
        return ", ".join(str(u) for u in owners if u)
    return str(owners or "")


def _is_active_listing(prop: dict) -> bool:
    """Match Hub main list: active + needs_review + unset (exclude archived)."""
    status = (prop.get("import_status") or "").strip().lower()
    return status in ("", "active", "needs_review")


def resolve_prop_location_for_sheet(
    prop: dict,
    projects_by_id: dict[str, dict] | None = None,
) -> tuple[str, str]:
    """
    Fresh ทำเล + สถานี/BTS for sheet write — always from project master when available.

    Returns (zone_label, transit_label). Never reuse stale sheet-only values when a
    project master exists; project details can change between syncs.
    """
    from src.hub.project_store import (
        load_projects,
        project_transit_display,
        project_zone_display,
    )

    if projects_by_id is None:
        projects_by_id = {p["id"]: p for p in load_projects()}

    proj = projects_by_id.get(str(prop.get("project_id") or ""))
    if proj:
        zones = project_zone_display(proj)
        transit = project_transit_display(proj)
        return _join_tags(zones), _join_tags(transit)

    zones_s = ""
    transit_s = _join_tags(prop.get("transit_from_sheet") or [])
    loc = str(prop.get("location_ref") or "").strip()
    if loc and not transit_s:
        transit_s = loc
    return zones_s, transit_s


def refresh_hub_listing_locations(
    properties: list[dict] | None = None,
    *,
    persist_disk: bool = True,
) -> tuple[list[dict], dict[str, dict], int]:
    """
    Force-apply current project master ทำเล/BTS onto Hub-owned listings.

    Sheet rows always resolve from the master at write time; this keeps
    properties.json in sync for Hub rows after each push.
    """
    from src.hub.project_store import (
        load_projects,
        load_properties,
        persist,
        project_location_label,
        project_transit_display,
    )

    projects = load_projects()
    projects_by_id = {p["id"]: p for p in projects}

    if properties is None:
        all_props = load_properties()
        working = all_props
    else:
        working = [dict(p) for p in properties]
        all_props = None

    updated = 0
    hub_props: list[dict] = []
    for prop in working:
        if not is_hub_owned(prop):
            continue
        proj = projects_by_id.get(str(prop.get("project_id") or ""))
        if proj:
            tags = project_transit_display(proj)
            loc = project_location_label(proj)
            prop["location_ref"] = loc
            prop["transit_from_sheet"] = list(tags)
            if prop.get("project_name") != proj.get("canonical_name"):
                prop["project_name"] = proj.get("canonical_name") or prop.get("project_name")
            updated += 1
        hub_props.append(prop)

    if persist_disk and properties is None and all_props is not None and updated:
        by_id = {p.get("id"): p for p in hub_props if p.get("id")}
        for i, p in enumerate(all_props):
            pid = p.get("id")
            if pid and pid in by_id:
                all_props[i] = by_id[pid]
        persist(projects, all_props)

    return hub_props, projects_by_id, updated


def prop_to_hub_row(
    prop: dict,
    synced_at: str | None = None,
    *,
    projects_by_id: dict[str, dict] | None = None,
) -> list[str]:
    zone_s, transit_s = resolve_prop_location_for_sheet(prop, projects_by_id)
    return [
        str(prop.get("code") or ""),
        str(prop.get("last_listed_at") or ""),
        "",
        str(prop.get("project_name") or ""),
        str(prop.get("property_type") or ""),
        str(prop.get("bedrooms") or ""),
        str(prop.get("size_sqm") or ""),
        str(prop.get("floor") or ""),
        str(prop.get("rent_price") or ""),
        str(prop.get("sale_price") or ""),
        zone_s,
        transit_s,
        "",
        "",
        str(prop.get("post_url") or ""),
        str(prop.get("post_pages_url") or ""),
        str(prop.get("notes") or ""),
        str(prop.get("source_url") or ""),
        _owner_display(prop),
        "Hub",
        str(prop.get("linked_ptp_code") or ""),
        synced_at or datetime.now().strftime("%d/%m/%Y %H:%M"),
        str(prop.get("id") or ""),
    ]


def prop_to_overview_row(
    prop: dict,
    *,
    projects_by_id: dict[str, dict] | None = None,
) -> list[str]:
    zone_s, transit_s = resolve_prop_location_for_sheet(prop, projects_by_id)
    source = "Hub" if is_hub_owned(prop) else "ชีท"
    owners = _owner_display(prop)
    # Prefer a single clickable owner URL when present
    owner_link = owners.split(",")[0].strip() if owners else ""
    return [
        str(prop.get("code") or ""),
        source,
        str(prop.get("last_listed_at") or ""),
        str(prop.get("project_name") or ""),
        _type_display(str(prop.get("property_type") or "")),
        str(prop.get("bedrooms") or ""),
        str(prop.get("size_sqm") or ""),
        str(prop.get("floor") or ""),
        str(prop.get("rent_price") or ""),
        str(prop.get("sale_price") or ""),
        zone_s,
        transit_s,
        str(prop.get("source_url") or ""),
        owner_link,
        str(prop.get("post_url") or ""),
        str(prop.get("post_pages_url") or ""),
    ]


def hub_properties_from_disk() -> list[dict]:
    if not PROPERTIES_JSON.exists():
        return []
    props = json.loads(PROPERTIES_JSON.read_text(encoding="utf-8"))
    return [p for p in props if is_hub_owned(p)]


def active_properties_for_overview(
    properties: list[dict] | None = None,
) -> list[dict]:
    """Active listings only, newest-first (same mental model as Hub「ใหม่ล่าสุด」)."""
    if properties is None:
        if not PROPERTIES_JSON.exists():
            return []
        properties = json.loads(PROPERTIES_JSON.read_text(encoding="utf-8"))
    active = [p for p in properties if _is_active_listing(p)]
    active.sort(key=_listed_sort_key, reverse=True)
    return active


def write_hub_export_csv(
    properties: list[dict] | None = None,
    *,
    projects_by_id: dict[str, dict] | None = None,
) -> Path:
    import csv

    props = properties if properties is not None else hub_properties_from_disk()
    synced = datetime.now().strftime("%d/%m/%Y %H:%M")
    HUB_EXPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with HUB_EXPORT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HUB_HEADERS)
        for p in props:
            w.writerow(prop_to_hub_row(p, synced, projects_by_id=projects_by_id))
    return HUB_EXPORT_CSV


def write_overview_export_csv(
    properties: list[dict] | None = None,
    *,
    projects_by_id: dict[str, dict] | None = None,
) -> Path:
    import csv

    props = properties if properties is not None else active_properties_for_overview()
    OVERVIEW_EXPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OVERVIEW_EXPORT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(OVERVIEW_HEADERS)
        for p in props:
            w.writerow(prop_to_overview_row(p, projects_by_id=projects_by_id))
    return OVERVIEW_EXPORT_CSV


def _gspread_client():
    """Authorize via service account JSON path or inline env JSON."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    inline = _env("GOOGLE_SERVICE_ACCOUNT_JSON") or _env("HUB_GOOGLE_SERVICE_ACCOUNT_JSON")
    if inline:
        info = json.loads(inline)
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)

    path = Path(
        _env("GOOGLE_CREDENTIALS_PATH") or "credentials/service_account.json"
    )
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        raise FileNotFoundError(
            "ยังไม่มี Service Account สำหรับเขียนชีท — "
            "วางไฟล์ credentials/service_account.json หรือตั้ง GOOGLE_SERVICE_ACCOUNT_JSON "
            "แล้วแชร์ชีทให้ email ของ service account เป็น Editor "
            f"(ตอนนี้ export ไว้ที่ {OVERVIEW_EXPORT_CSV.name} แทน)"
        )
    creds = Credentials.from_service_account_file(str(path), scopes=scopes)
    return gspread.authorize(creds)


def _tab_forbidden(title: str) -> bool:
    t = (title or "").strip().lower()
    if t in _FORBIDDEN_TAB_NAMES:
        return True
    return t.startswith("focus")


def _overview_tab_candidates() -> list[str]:
    preferred = _env("HUB_OVERVIEW_SHEET_NAME") or _env("HUB_DASHBOARD_SHEET_NAME")
    names: list[str] = []
    if preferred:
        names.append(preferred)
    for n in ("ทรัพย์รวม", "ทรัพย์รวม · แอป"):
        if n not in names:
            names.append(n)
    return names


def _open_or_create_worksheet(ss, *, name: str, rows: int, cols: int):
    if _tab_forbidden(name):
        raise ValueError(f"ห้ามเขียนแท็บ「{name}」(Focus/_proj_loc ไม่ใช่เป้าซิงค์)")
    try:
        ws = ss.worksheet(name)
        if _tab_forbidden(ws.title):
            raise ValueError(f"ห้ามเขียนแท็บ「{ws.title}」")
        return ws, False
    except Exception:
        pass
    ws = ss.add_worksheet(title=name, rows=max(100, rows), cols=cols)
    return ws, True


def _resolve_overview_worksheet(ss, *, rows: int):
    """Pick ทรัพย์รวม / ทรัพย์รวม · แอป (never Focus)."""
    gid = _env("HUB_OVERVIEW_SHEET_GID") or _env("HUB_DASHBOARD_SHEET_GID")
    if gid:
        try:
            ws = ss.get_worksheet_by_id(int(gid))
            if ws and not _tab_forbidden(ws.title):
                return ws, False
        except Exception:
            pass

    last_err: Exception | None = None
    for name in _overview_tab_candidates():
        if _tab_forbidden(name):
            continue
        try:
            ws = ss.worksheet(name)
            if _tab_forbidden(ws.title):
                continue
            return ws, False
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue

    # Create primary overview tab
    primary = _overview_tab_candidates()[0]
    ws, created = _open_or_create_worksheet(
        ss, name=primary, rows=rows + 20, cols=len(OVERVIEW_HEADERS)
    )
    if created and last_err:
        pass
    return ws, created


def _worksheet_has_dashboard_chrome(ws) -> bool:
    """True when rows 1–5 look like the Apps Script dashboard chrome."""
    try:
        probe = ws.get("A1:P5")
    except Exception:
        return False
    if not probe or len(probe) < 5:
        return False
    a1 = str((probe[0] or [""])[0] or "")
    header = [str(c or "").strip() for c in (probe[4] if len(probe) > 4 else [])]
    if "Property Hub" in a1 or "ทรัพย์รวม" in a1:
        return True
    return bool(header) and header[:4] == OVERVIEW_HEADERS[:4]


def _col_a1(n: int) -> str:
    """1-based column index → A1 letter(s)."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s or "A"


def _update_values_chunked(ws, values: list[list], *, start_row: int = 1) -> None:
    """Write values in chunks to stay under Sheets API payload limits."""
    if not values:
        return
    cols = max(len(r) for r in values)
    end_col = _col_a1(cols)
    try:
        needed_rows = start_row + len(values) - 1
        if ws.row_count < needed_rows:
            ws.add_rows(needed_rows - ws.row_count + 10)
        if ws.col_count < cols:
            ws.add_cols(cols - ws.col_count + 2)
    except Exception:
        pass

    chunk = 2500
    for i in range(0, len(values), chunk):
        part = values[i : i + chunk]
        row0 = start_row + i
        row1 = row0 + len(part) - 1
        range_name = f"A{row0}:{end_col}{row1}"
        ws.update(range_name, part, value_input_option="USER_ENTERED")


def _write_overview_values(ws, values: list[list], *, synced_at: str) -> dict:
    """Replace overview data; preserve dashboard chrome when present."""
    meta: dict = {"sheet_title": ws.title, "data_start_row": 1}
    if _tab_forbidden(ws.title):
        raise ValueError(f"ห้ามเขียนแท็บ「{ws.title}」")

    if _worksheet_has_dashboard_chrome(ws):
        # Keep rows 1–5 (title/search/status/header); rewrite data from row 6
        data_rows = values[1:] if values and values[0] == OVERVIEW_HEADERS else values
        meta["data_start_row"] = 6
        meta["chrome_preserved"] = True
        try:
            last = max(ws.row_count, 6)
            if last >= 6:
                ws.batch_clear([f"A6:P{last}"])
        except Exception:
            try:
                ws.clear()
                meta["chrome_preserved"] = False
                meta["data_start_row"] = 1
                _update_values_chunked(ws, values, start_row=1)
                return meta
            except Exception:
                raise
        try:
            ws.update(
                "A4",
                [[
                    f"ซิงค์จากแอป · อัปเดต: {synced_at} · แสดง "
                    f"{len(data_rows):,} รายการ · เรียงใหม่→เก่า"
                ]],
                value_input_option="USER_ENTERED",
            )
        except Exception:
            pass
        if data_rows:
            _update_values_chunked(ws, data_rows, start_row=6)
        meta["rows_written"] = len(data_rows)
        return meta

    ws.clear()
    _update_values_chunked(ws, values, start_row=1)
    meta["rows_written"] = max(0, len(values) - 1)
    meta["chrome_preserved"] = False
    return meta


def _write_hub_tab(ss, hub_rows: list[list], *, hub_name: str, hub_gid: str) -> dict:
    """Replace「ทรัพย์ Hub」with Hub-owned rows (may be empty headers-only)."""
    if _tab_forbidden(hub_name):
        raise ValueError(f"ห้ามใช้ชื่อแท็บ「{hub_name}」สำหรับ Hub sync")

    ws = None
    created = False
    try:
        if hub_gid:
            ws = ss.get_worksheet_by_id(int(hub_gid))
            if ws and _tab_forbidden(ws.title):
                ws = None
        if ws is None:
            ws = ss.worksheet(hub_name)
            if _tab_forbidden(ws.title):
                raise ValueError(f"ห้ามเขียนแท็บ「{ws.title}」")
    except Exception:
        try:
            sale = ss.worksheet("Sale")
            if not _tab_forbidden(sale.title):
                sale.update_title(hub_name)
                ws = sale
        except Exception:
            ws = ss.add_worksheet(
                title=hub_name,
                rows=max(100, len(hub_rows) + 10),
                cols=len(HUB_HEADERS),
            )
            created = True

    values = [HUB_HEADERS] + hub_rows
    ws.clear()
    _update_values_chunked(ws, values, start_row=1)
    return {
        "sheet_title": ws.title,
        "rows_written": len(hub_rows),
        "created_sheet": hub_name if created else "",
        "gid": ws.id,
    }


def push_hub_properties_to_sheet(properties: list[dict] | None = None) -> dict:
    """
    Sync app listings to the Hub working Google Sheet.

    1) Overview tab「ทรัพย์รวม」(configurable) — all active props, newest-first
    2)「ทรัพย์ Hub」— Hub-owned (RXT/COA) only (secondary / Apps Script source)

    Order: gspread service account (preferred for large writes) → Apps Script webapp
    → local CSV export only (pushed=false).
    """
    from src.hub.project_store import load_properties

    # Refresh Hub listing locations (persist when reading from disk)
    hub_props, projects_by_id, loc_refreshed = refresh_hub_listing_locations(
        None if properties is None else list(properties),
        persist_disk=properties is None,
    )
    all_props = load_properties() if properties is None else list(properties)

    overview_props = active_properties_for_overview(all_props)
    export_overview = write_overview_export_csv(
        overview_props, projects_by_id=projects_by_id
    )
    export_hub = write_hub_export_csv(hub_props, projects_by_id=projects_by_id)

    synced = datetime.now().strftime("%d/%m/%Y %H:%M")
    overview_rows = [
        prop_to_overview_row(p, projects_by_id=projects_by_id) for p in overview_props
    ]
    hub_rows = [
        prop_to_hub_row(p, synced, projects_by_id=projects_by_id) for p in hub_props
    ]

    result: dict = {
        "ok": True,
        "hub_count": len(hub_props),
        "overview_count": len(overview_props),
        "written_count": 0,
        "location_refreshed": loc_refreshed,
        "export_csv": str(export_overview.relative_to(BASE_DIR)),
        "hub_export_csv": str(export_hub.relative_to(BASE_DIR)),
        "pushed": False,
        "synced_at": synced,
        "sort": "newest_first",
    }

    sheet_id = _env("HUB_GOOGLE_SHEETS_ID") or _env("GOOGLE_SHEETS_ID")
    hub_name = _env("HUB_SHEET_NAME") or "ทรัพย์ Hub"
    hub_gid = _env("HUB_SHEET_GID")
    warnings: list[str] = []

    # --- gspread path (handles 7k+ overview rows) ---
    try:
        client = _gspread_client()
    except Exception as exc:  # noqa: BLE001
        warnings.append(str(exc))
        client = None

    if client and sheet_id and not sheet_id.startswith("your_"):
        try:
            ss = client.open_by_key(sheet_id)
            overview_ws, created = _resolve_overview_worksheet(
                ss, rows=len(overview_rows) + 10
            )
            overview_values = [OVERVIEW_HEADERS] + overview_rows
            ov_meta = _write_overview_values(
                overview_ws, overview_values, synced_at=synced
            )
            result["pushed"] = True
            result["via"] = "gspread"
            result["sheet_title"] = ov_meta.get("sheet_title") or overview_ws.title
            result["written_count"] = int(
                ov_meta.get("rows_written") or len(overview_rows)
            )
            result["data_start_row"] = ov_meta.get("data_start_row", 1)
            result["chrome_preserved"] = bool(ov_meta.get("chrome_preserved"))
            if created:
                result["created_sheet"] = overview_ws.title
            result["spreadsheet_url"] = (
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={overview_ws.id}"
            )

            try:
                hub_meta = _write_hub_tab(
                    ss, hub_rows, hub_name=hub_name, hub_gid=hub_gid
                )
                result["hub_sheet_title"] = hub_meta.get("sheet_title")
                result["hub_rows_written"] = hub_meta.get("rows_written", 0)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"แท็บ「{hub_name}」: {exc}")

            if warnings:
                result["push_warning"] = " · ".join(warnings)
            return result
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"gspread: {exc}")
    elif client and (not sheet_id or sheet_id.startswith("your_")):
        warnings.append(
            "ยังไม่ได้ตั้ง HUB_GOOGLE_SHEETS_ID / GOOGLE_SHEETS_ID (ชีททดลองสำหรับซิงค์กลับ)"
        )

    # --- Apps Script fallback (smaller / hub-only payloads historically) ---
    webapp = _env("HUB_SHEET_WEBAPP_URL") or _env("GOOGLE_SHEET_WEBAPP_URL")
    if webapp:
        try:
            import urllib.request

            payload = json.dumps(
                {
                    "mode": "overview",
                    "rows": overview_rows,
                    "headers": OVERVIEW_HEADERS,
                    "hub_rows": hub_rows,
                    "hub_headers": HUB_HEADERS,
                    "overview_sheet": _overview_tab_candidates()[0],
                    "hub_sheet": hub_name,
                    "synced_at": synced,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            req = urllib.request.Request(
                webapp,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            if body.get("ok"):
                result["pushed"] = True
                result["via"] = "apps_script"
                result["sheet_title"] = (
                    body.get("sheet")
                    or body.get("overview_sheet")
                    or _overview_tab_candidates()[0]
                )
                result["written_count"] = int(
                    body.get("rows") or body.get("overview_rows") or len(overview_rows)
                )
                result["spreadsheet_url"] = body.get("spreadsheet_url") or (
                    f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
                    if sheet_id
                    else ""
                )
                if warnings:
                    result["push_warning"] = " · ".join(warnings)
                return result
            warnings.append(body.get("error") or "Apps Script ไม่สำเร็จ")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Apps Script: {exc}")

    result["push_warning"] = " · ".join(warnings) if warnings else (
        "ซิงค์ชีทไม่สำเร็จ — ตรวจ Service Account / HUB_GOOGLE_SHEETS_ID"
    )
    result["ok"] = False
    return result
