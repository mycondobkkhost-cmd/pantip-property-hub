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
    from src.hub.env_load import load_hub_env

    load_hub_env()
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
    "หมายเหตุ",
]

_FORBIDDEN_TAB_NAMES = {
    "focus",
    "focus🚨",
    "_proj_loc",
    "_overview_src",
}

# Hidden backing tab for「ทรัพย์รวม」FILTER search (sync writes here; chrome stays on overview).
OVERVIEW_SRC_SHEET = "_overview_src"
OVERVIEW_HEADER_ROW = 5
OVERVIEW_DATA_START = 6

# Match「ชีตสำหรับทำงาน」visual language (inspected via Sheets API).
CLR_TITLE_BG = "#fff8e1"
CLR_TITLE_FG = "#5d4037"
CLR_HEADER_BG = "#fbbc04"  # banded header / gold
CLR_HEADER_FG = "#202124"
CLR_LINK_HEADER_BG = "#ffff00"  # link columns on work sheet
CLR_SEARCH_BG = "#fff9c4"
CLR_SEARCH_BORDER = "#f9ab00"
CLR_ROW_BG = "#fffdf5"
CLR_STATUS_BG = "#faf6e9"
CLR_MUTED = "#80868b"
CLR_BAND_FIRST = "#ffffff"
CLR_BAND_SECOND = "#ffe6dd"  # peach alternating rows

# Column widths aligned to「ชีตสำหรับทำงาน」analogs (รหัส/วันที่/โครงการ/…).
OVERVIEW_COL_WIDTHS = [
    80,  # รหัส (~71 on work sheet)
    56,  # ที่มา
    104,  # วันที่
    272,  # โครงการ
    102,  # ประเภท
    99,  # ห้อง
    72,  # ตรม.
    48,  # ชั้น (~37; slightly wider)
    106,  # เช่า
    88,  # ขาย
    120,  # ทำเล
    215,  # สถานี
    72,  # ต้นทาง (short HYPERLINK label)
    72,  # เจ้าของ
    72,  # ที่โพสต์
    72,  # เพจ
    160,  # หมายเหตุ
]
# Link-like columns (O–P / indices 12–15) — yellow header + CLIP like work sheet.
OVERVIEW_LINK_COL_INDEXES = (12, 13, 14, 15)
OVERVIEW_NUMBER_COL_INDEXES = (8, 9)  # เช่า / ขาย → #,##0
OVERVIEW_NOTES_COL_INDEX = 16  # Q · หมายเหตุ
# A1 letter of last overview column (must match len(OVERVIEW_HEADERS)).
OVERVIEW_END_COL = "Q"

# Search chrome: C2 = รหัส/โครงการ/หมายเหตุ · C3 = ทำเล/สถานี · empty = all · both = AND
# (Must use IF(q="",1,…) — SEARCH("", "") on blank ทำเล/สถานี is #VALUE! and drops rows.)
#
# FILTER returns *values* only — HYPERLINK formulas inside a multi-column FILTER/BYROW
# spill are NOT clickable. Store raw URLs in `_overview_src` M–P; FILTER A:L into A6;
# rebuild short clickable links with per-column ARRAYFORMULA(HYPERLINK(VLOOKUP(...))).
# หมายเหตุ (Q) is plain text via ARRAYFORMULA(VLOOKUP) like the link cols.
_OVERVIEW_FILTER_COND = (
    "('_overview_src'!A2:A<>\"\")*"
    "IF(TRIM($C$2)=\"\",1,"
    "((ISNUMBER(SEARCH($C$2,'_overview_src'!A2:A)))+"
    "(ISNUMBER(SEARCH($C$2,'_overview_src'!D2:D)))+"
    "(ISNUMBER(SEARCH($C$2,'_overview_src'!Q2:Q)))+"
    "IF(REGEXMATCH(LOWER(TRIM($C$2)),\"thru|ทรู\"),"
    "IF(REGEXMATCH(LOWER('_overview_src'!D2:D),\"thru|ทรู\"),1,0),0)>0))*"
    "IF(TRIM($C$3)=\"\",1,"
    "((ISNUMBER(SEARCH($C$3,'_overview_src'!K2:K)))+"
    "(ISNUMBER(SEARCH($C$3,'_overview_src'!L2:L)))>0))"
)
OVERVIEW_FILTER_FORMULA = (
    "=IFERROR("
    "FILTER('_overview_src'!A2:L," + _OVERVIEW_FILTER_COND + "),"
    "IF(AND(TRIM($C$2)=\"\",TRIM($C$3)=\"\"),\"ยังไม่มีข้อมูล\",\"ไม่พบรายการที่ตรงคำค้น\"))"
)
# Link-column formulas (written at M6/N6/O6/P6). Open-ended A6:A follows FILTER spill.
# Guard empty VLOOKUP results — HYPERLINK("","โพสต์") still paints a label and looks
# like a real link while ทำเล/สถานี/หมายเหตุ stay blank.
OVERVIEW_LINK_FORMULAS = {
    "M6": (
        '=ARRAYFORMULA(IF(A6:A="",,IFERROR('
        "IF(VLOOKUP(A6:A,'_overview_src'!$A$2:$M,13,FALSE)=\"\",\"\","
        "IF(REGEXMATCH(VLOOKUP(A6:A,'_overview_src'!$A$2:$M,13,FALSE)&\"\","
        '"(?i)^https?://"),'
        "HYPERLINK(VLOOKUP(A6:A,'_overview_src'!$A$2:$M,13,FALSE),\"ต้นทาง\"),"
        "VLOOKUP(A6:A,'_overview_src'!$A$2:$M,13,FALSE))),)))"
    ),
    "N6": (
        '=ARRAYFORMULA(IF(A6:A="",,IFERROR('
        "IF(VLOOKUP(A6:A,'_overview_src'!$A$2:$N,14,FALSE)=\"\",\"\","
        "IF(REGEXMATCH(VLOOKUP(A6:A,'_overview_src'!$A$2:$N,14,FALSE)&\"\","
        '"(?i)^https?://"),'
        "HYPERLINK(VLOOKUP(A6:A,'_overview_src'!$A$2:$N,14,FALSE),\"เจ้าของ\"),"
        "VLOOKUP(A6:A,'_overview_src'!$A$2:$N,14,FALSE))),)))"
    ),
    "O6": (
        '=ARRAYFORMULA(IF(A6:A="",,IFERROR('
        "IF(VLOOKUP(A6:A,'_overview_src'!$A$2:$O,15,FALSE)=\"\",\"\","
        "IF(REGEXMATCH(VLOOKUP(A6:A,'_overview_src'!$A$2:$O,15,FALSE)&\"\","
        '"(?i)^https?://"),'
        "HYPERLINK(VLOOKUP(A6:A,'_overview_src'!$A$2:$O,15,FALSE),\"โพสต์\"),"
        "VLOOKUP(A6:A,'_overview_src'!$A$2:$O,15,FALSE))),)))"
    ),
    "P6": (
        '=ARRAYFORMULA(IF(A6:A="",,IFERROR('
        "IF(VLOOKUP(A6:A,'_overview_src'!$A$2:$P,16,FALSE)=\"\",\"\","
        "IF(REGEXMATCH(VLOOKUP(A6:A,'_overview_src'!$A$2:$P,16,FALSE)&\"\","
        '"(?i)^https?://"),'
        "HYPERLINK(VLOOKUP(A6:A,'_overview_src'!$A$2:$P,16,FALSE),\"เพจ\"),"
        "VLOOKUP(A6:A,'_overview_src'!$A$2:$P,16,FALSE))),)))"
    ),
}
# Notes column (Q6) — plain text from `_overview_src` col 17.
OVERVIEW_NOTES_FORMULA = (
    '=ARRAYFORMULA(IF(A6:A="",,IFERROR('
    "IF(VLOOKUP(A6:A,'_overview_src'!$A$2:$Q,17,FALSE)=\"\",\"\","
    "VLOOKUP(A6:A,'_overview_src'!$A$2:$Q,17,FALSE)),)))"
)

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


def _notes_for_sheet(raw) -> str:
    """Normalize property notes for sheet cells (treat placeholder dashes as empty)."""
    s = str(raw or "").strip()
    if s in {"-", "—", "–"}:
        return ""
    return s


def _norm_prop_code(raw) -> str:
    return str(raw or "").upper().replace(" ", "").strip()


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


def _owner_entries(prop: dict) -> list[str]:
    """Normalize owner_facebook (and legacy single-string) into non-empty entries."""
    owners = prop.get("owner_facebook")
    if owners is None or owners == "":
        # Legacy / queue fields sometimes hold the profile link
        for key in ("owner_fb", "owner_contact", "owner_profile"):
            alt = prop.get(key)
            if alt:
                owners = alt
                break
    if isinstance(owners, str):
        owners = [owners]
    if not isinstance(owners, list):
        return []
    out: list[str] = []
    for u in owners:
        s = str(u or "").strip()
        if not s or s in {".", "-", "—"}:
            continue
        out.append(s)
    return out


def _owner_url_and_name(prop: dict) -> tuple[str, str]:
    """Prefer a profile/contact URL; keep a short display name when present."""
    urls: list[str] = []
    names: list[str] = []
    for s in _owner_entries(prop):
        if _is_http_url(s):
            urls.append(s)
        else:
            names.append(s)
    return (urls[0] if urls else "", names[0] if names else "")


def _owner_display(prop: dict) -> str:
    """Value for sheet「เจ้าของ」/「เฟสเจ้าของ」: prefer URL (→ short HYPERLINK), else name."""
    url, name = _owner_url_and_name(prop)
    if url:
        return url
    return name


def _owner_hyperlink_label(prop: dict) -> str:
    """Short clickable label: owner name when short, else「เจ้าของ」."""
    _url, name = _owner_url_and_name(prop)
    if name and len(name) <= 24 and "\n" not in name:
        return name
    return "เจ้าของ"


def _is_http_url(value: str) -> bool:
    s = str(value or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://")


def _hyperlink_cell(url: str, label: str) -> str:
    """Sheet cell: short clickable label, or empty when no URL."""
    raw = str(url or "").strip()
    if not raw or not _is_http_url(raw):
        return ""
    # Escape double-quotes for Sheets formula literals
    safe_url = raw.replace('"', '""')
    safe_label = str(label or "เปิด").replace('"', '""')
    return f'=HYPERLINK("{safe_url}","{safe_label}")'


def _maybe_hyperlink(url: str, label: str, *, enabled: bool) -> str:
    raw = str(url or "").strip()
    if not enabled:
        return raw
    if not raw:
        return ""
    if not _is_http_url(raw):
        # Non-URL text (e.g. owner name) — keep as-is for display columns
        return raw
    return _hyperlink_cell(raw, label)


def _overview_data_with_hyperlinks(data_rows: list[list]) -> list[list]:
    """Convert raw URL cells in cols M–P to short HYPERLINK formulas (direct writes)."""
    n = len(OVERVIEW_HEADERS)
    out: list[list] = []
    for row in data_rows:
        r = list(row) + [""] * max(0, n - len(row))
        r = r[:n]
        r[12] = _hyperlink_cell(str(r[12] or ""), "ต้นทาง")
        r[13] = _maybe_hyperlink(str(r[13] or ""), "เจ้าของ", enabled=True)
        r[14] = _hyperlink_cell(str(r[14] or ""), "โพสต์")
        r[15] = _hyperlink_cell(str(r[15] or ""), "เพจ")
        out.append(r)
    return out


def _overview_values_with_hyperlinks(values: list[list]) -> list[list]:
    """Like `_overview_data_with_hyperlinks` but preserves a header row when present."""
    if not values:
        return values
    head = list(values[0]) if values[0] else []
    if head[:4] == list(OVERVIEW_HEADERS)[:4]:
        return [list(values[0])] + _overview_data_with_hyperlinks(values[1:])
    return _overview_data_with_hyperlinks(values)


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

    zones_fallback = str(prop.get("location_ref") or "").strip()
    transit_fallback = _join_tags(prop.get("transit_from_sheet") or [])

    proj = projects_by_id.get(str(prop.get("project_id") or ""))
    if proj:
        zones_s = _join_tags(project_zone_display(proj))
        transit_s = _join_tags(project_transit_display(proj))
        # Project row exists but Living verification still pending → do not wipe
        # listing ทำเล/สถานี that were already filled on the property.
        if not zones_s:
            zones_s = zones_fallback
        if not transit_s:
            transit_s = transit_fallback
        return zones_s, transit_s

    return zones_fallback, transit_fallback


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
    link_as_hyperlink: bool = False,
) -> list[str]:
    from src.hub.sheet_links import http_url_or_empty

    zone_s, transit_s = resolve_prop_location_for_sheet(prop, projects_by_id)
    # Main-sheet mapping: ลิ้งค์โพส / ลิ้งค์โพส Pages / ลิ้งค์ต้นโพสต์ / เฟสเจ้าของ
    post_url = http_url_or_empty(str(prop.get("post_url") or ""))
    pages_url = http_url_or_empty(str(prop.get("post_pages_url") or ""))
    source_url = http_url_or_empty(str(prop.get("source_url") or ""))
    owner_url, owner_name = _owner_url_and_name(prop)
    notes = _notes_for_sheet(prop.get("notes"))
    # Non-URL owner names belong in หมายเหตุ, not HYPERLINK columns.
    if owner_name and not owner_url:
        notes = " | ".join(p for p in (notes, owner_name) if p)
        owner_display = ""
    else:
        owner_display = owner_url
    if link_as_hyperlink:
        post_url = _hyperlink_cell(post_url, "โพสต์")
        pages_url = _hyperlink_cell(pages_url, "เพจ")
        source_url = _hyperlink_cell(source_url, "ต้นทาง")
        owner_display = _hyperlink_cell(owner_url, _owner_hyperlink_label(prop)) if owner_url else ""
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
        post_url,
        pages_url,
        notes,
        source_url,
        owner_display,
        "Hub",
        str(prop.get("linked_ptp_code") or ""),
        synced_at or datetime.now().strftime("%d/%m/%Y %H:%M"),
        str(prop.get("id") or ""),
    ]


def prop_to_overview_row(
    prop: dict,
    *,
    projects_by_id: dict[str, dict] | None = None,
    link_as_hyperlink: bool = False,
) -> list[str]:
    from src.hub.sheet_links import http_url_or_empty

    zone_s, transit_s = resolve_prop_location_for_sheet(prop, projects_by_id)
    source = "Hub" if is_hub_owned(prop) else "ชีท"
    # ต้นทาง / เจ้าของ: URLs only — non-URL text belongs in หมายเหตุ
    owner_url, owner_name = _owner_url_and_name(prop)
    owner_link = owner_url
    source_url = http_url_or_empty(str(prop.get("source_url") or ""))
    post_url = http_url_or_empty(str(prop.get("post_url") or ""))
    pages_url = http_url_or_empty(str(prop.get("post_pages_url") or ""))
    notes = _notes_for_sheet(prop.get("notes"))
    if owner_name and not owner_url:
        notes = " | ".join(p for p in (notes, owner_name) if p)
    if link_as_hyperlink:
        source_url = _hyperlink_cell(source_url, "ต้นทาง")
        owner_link = _hyperlink_cell(owner_url, _owner_hyperlink_label(prop)) if owner_url else ""
        post_url = _hyperlink_cell(post_url, "โพสต์")
        pages_url = _hyperlink_cell(pages_url, "เพจ")
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
        source_url,
        owner_link,
        post_url,
        pages_url,
        notes,
    ]


def hub_properties_from_disk() -> list[dict]:
    if not PROPERTIES_JSON.exists():
        return []
    props = json.loads(PROPERTIES_JSON.read_text(encoding="utf-8"))
    return [p for p in props if is_hub_owned(p)]


def _load_properties_for_export() -> list[dict]:
    """Load properties.json safely (empty/partial file during startup sync → [])."""
    if not PROPERTIES_JSON.exists():
        return []
    try:
        raw = PROPERTIES_JSON.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def active_properties_for_overview(
    properties: list[dict] | None = None,
) -> list[dict]:
    """Active listings only, newest-first (same mental model as Hub「ใหม่ล่าสุด」)."""
    if properties is None:
        properties = _load_properties_for_export()
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


# Thai checklist shown when sync cannot write Sheets (no SA / bad env).
SERVICE_ACCOUNT_SETUP_STEPS_TH = [
    "เปิด https://console.cloud.google.com แล้วสร้าง/เลือกโปรเจกต์",
    "APIs & Services → Enable API → เปิด「Google Sheets API」และ「Google Drive API」",
    "IAM & Admin → Service Accounts → Create service account → สร้างคีย์ประเภท JSON แล้วดาวน์โหลด",
    "เปิดไฟล์ JSON → คัดลอกทั้งก้อน (มี client_email + private_key) → วางใน Render → Environment เป็นตัวแปร GOOGLE_SERVICE_ACCOUNT_JSON (ค่าเป็น JSON ทั้งก้อน บรรทัดเดียว)",
    "เปิดชีทเป้าหมาย → Share → ใส่ email จากฟิลด์ client_email ใน JSON เป็น Editor",
    "Save env แล้วรอ service restart (หรือ Manual Deploy) → กด「ซิงค์ไปชีท Hub」อีกครั้ง",
]

OVERVIEW_EXPORT_DOWNLOAD_PATH = "/api/properties/overview-export.csv"


def service_account_setup_payload(*, warning: str = "") -> dict:
    """Extra fields for API/UI when sheet write needs a Service Account."""
    return {
        "need_service_account": True,
        "download_url": OVERVIEW_EXPORT_DOWNLOAD_PATH,
        "setup_steps": list(SERVICE_ACCOUNT_SETUP_STEPS_TH),
        "setup_hint": (
            "ยังเขียนชีทอัตโนมัติไม่ได้ — ต้องมี Service Account บน Render "
            "ชั่วคราวดาวน์โหลด CSV แล้ววางในแท็บ「ทรัพย์รวม」เองได้"
        ),
        "push_warning": warning
        or (
            "ยังไม่มี Service Account สำหรับเขียนชีท — "
            "ตั้ง GOOGLE_SERVICE_ACCOUNT_JSON บน Render แล้วแชร์ชีทให้ "
            "client_email เป็น Editor "
            f"(ชั่วคราวดาวน์โหลดได้ที่ {OVERVIEW_EXPORT_DOWNLOAD_PATH})"
        ),
    }


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
        try:
            info = json.loads(inline)
        except json.JSONDecodeError:
            # fly secrets import of bare JSON can store {\"k\":\"v\"} instead of {"k":"v"}
            if '\\"' in inline:
                info = json.loads(inline.replace('\\"', '"'))
            else:
                raise
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
            "ตั้ง GOOGLE_SERVICE_ACCOUNT_JSON บน Render (หรือวางไฟล์ "
            "credentials/service_account.json) แล้วแชร์ชีทให้ client_email เป็น Editor "
            f"— ชั่วคราวดาวน์โหลด CSV ได้ที่ {OVERVIEW_EXPORT_DOWNLOAD_PATH}"
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


def _hex_rgb(hex_color: str) -> dict:
    h = hex_color.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255.0,
        "green": int(h[2:4], 16) / 255.0,
        "blue": int(h[4:6], 16) / 255.0,
    }


def _solid_medium_borders() -> dict:
    edge = {"style": "SOLID_MEDIUM"}
    return {"top": edge, "bottom": edge, "left": edge, "right": edge}


def _delete_banded_range_requests(ss, sheet_id: int) -> list[dict]:
    """Build deleteBanding requests for existing banded ranges on a sheet."""
    reqs: list[dict] = []
    try:
        meta = ss.fetch_sheet_metadata(
            {
                "fields": "sheets(properties(sheetId),bandedRanges)",
            }
        )
    except Exception:
        try:
            meta = ss.fetch_sheet_metadata()
        except Exception:
            return reqs
    for sh in meta.get("sheets") or []:
        props = sh.get("properties") or {}
        if props.get("sheetId") != sheet_id:
            continue
        for br in sh.get("bandedRanges") or []:
            bid = br.get("bandedRangeId")
            if bid is not None:
                reqs.append({"deleteBanding": {"bandedRangeId": bid}})
    return reqs


def _col_width_requests(sheet_id: int, widths: list[int]) -> list[dict]:
    out: list[dict] = []
    for i, w in enumerate(widths):
        out.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": i,
                        "endIndex": i + 1,
                    },
                    "properties": {"pixelSize": int(w)},
                    "fields": "pixelSize",
                }
            }
        )
    return out


def _worksheet_has_dashboard_chrome(ws) -> bool:
    """True when rows 1–5 look like the overview search chrome."""
    try:
        probe = ws.get(f"A1:{OVERVIEW_END_COL}5")
    except Exception:
        return False
    if not probe or len(probe) < 5:
        return False
    a1 = str((probe[0] or [""])[0] or "")
    a2 = str((probe[1] or [""])[0] or "") if len(probe) > 1 else ""
    header = [str(c or "").strip() for c in (probe[4] if len(probe) > 4 else [])]
    if "Property Hub" in a1:
        return True
    if "ค้นหาทั่วไป" in a2 or "ค้นหา" in a2:
        return True
    if bool(header) and header[: len(OVERVIEW_HEADERS)] == OVERVIEW_HEADERS:
        # Row 5 is the overview header strip (chrome), not a data header at row 1
        row1 = [str(c or "").strip() for c in (probe[0] or [])]
        if row1[:4] != OVERVIEW_HEADERS[:4]:
            return True
    return False


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


def _open_or_create_src_sheet(ss, *, rows: int):
    """Open/create hidden `_overview_src` (internal; not a sync target)."""
    try:
        src = ss.worksheet(OVERVIEW_SRC_SHEET)
    except Exception:
        src = ss.add_worksheet(
            title=OVERVIEW_SRC_SHEET,
            rows=max(100, rows + 20),
            cols=len(OVERVIEW_HEADERS),
        )
    try:
        if hasattr(src, "hide"):
            src.hide()
        else:
            ss.batch_update(
                {
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": src.id,
                                    "hidden": True,
                                },
                                "fields": "hidden",
                            }
                        }
                    ]
                }
            )
    except Exception:
        pass
    return src


def _format_overview_table_body(
    sid: int,
    *,
    header_row: int,
    data_end_row: int,
    cols: int,
) -> list[dict]:
    """Shared body formatting matching「ชีตสำหรับทำงาน」(banding, header, #,##0, CLIP links)."""
    end_row = max(data_end_row, header_row + 2)
    header_rng = {
        "sheetId": sid,
        "startRowIndex": header_row,
        "endRowIndex": header_row + 1,
        "startColumnIndex": 0,
        "endColumnIndex": cols,
    }
    data_rng = {
        "sheetId": sid,
        "startRowIndex": header_row + 1,
        "endRowIndex": end_row,
        "startColumnIndex": 0,
        "endColumnIndex": cols,
    }
    requests: list[dict] = [
        {
            "addBanding": {
                "bandedRange": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": header_row,
                        "endRowIndex": end_row,
                        "startColumnIndex": 0,
                        "endColumnIndex": cols,
                    },
                    "rowProperties": {
                        "headerColor": _hex_rgb(CLR_HEADER_BG),
                        "firstBandColor": _hex_rgb(CLR_BAND_FIRST),
                        "secondBandColor": _hex_rgb(CLR_BAND_SECOND),
                    },
                }
            }
        },
        {
            "repeatCell": {
                "range": header_rng,
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": _hex_rgb(CLR_HEADER_BG),
                        "textFormat": {
                            "foregroundColor": _hex_rgb(CLR_HEADER_FG),
                            "bold": True,
                            "fontSize": 10,
                            "fontFamily": "Arial",
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "BOTTOM",
                        "wrapStrategy": "OVERFLOW_CELL",
                        "borders": _solid_medium_borders(),
                    }
                },
                "fields": (
                    "userEnteredFormat(backgroundColor,textFormat,"
                    "horizontalAlignment,verticalAlignment,wrapStrategy,borders)"
                ),
            }
        },
        {
            # Default data body: Arial 10, center like work sheet.
            "repeatCell": {
                "range": data_rng,
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"fontSize": 10, "fontFamily": "Arial"},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "BOTTOM",
                        "wrapStrategy": "OVERFLOW_CELL",
                    }
                },
                "fields": (
                    "userEnteredFormat(textFormat,horizontalAlignment,"
                    "verticalAlignment,wrapStrategy)"
                ),
            }
        },
    ]

    # LEFT-align long text columns: โครงการ / ทำเล / สถานี
    for c0, c1 in ((3, 4), (10, 12)):
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": header_row + 1,
                        "endRowIndex": end_row,
                        "startColumnIndex": c0,
                        "endColumnIndex": c1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "horizontalAlignment": "LEFT",
                        }
                    },
                    "fields": "userEnteredFormat.horizontalAlignment",
                }
            }
        )

    # Rent / sale number format #,##0 (header + data columns)
    for ci in OVERVIEW_NUMBER_COL_INDEXES:
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": header_row,
                        "endRowIndex": end_row,
                        "startColumnIndex": ci,
                        "endColumnIndex": ci + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "numberFormat": {
                                "type": "NUMBER",
                                "pattern": "#,##0",
                            },
                            "horizontalAlignment": "CENTER",
                        }
                    },
                    "fields": (
                        "userEnteredFormat(numberFormat,horizontalAlignment)"
                    ),
                }
            }
        )

    # Link columns: yellow header + CLIP wrap + LEFT (short HYPERLINK labels)
    for ci in OVERVIEW_LINK_COL_INDEXES:
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": header_row,
                        "endRowIndex": header_row + 1,
                        "startColumnIndex": ci,
                        "endColumnIndex": ci + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": _hex_rgb(CLR_LINK_HEADER_BG),
                            "textFormat": {
                                "foregroundColor": _hex_rgb(CLR_HEADER_FG),
                                "bold": True,
                                "fontSize": 10,
                                "fontFamily": "Arial",
                            },
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "BOTTOM",
                            "wrapStrategy": "CLIP",
                            "borders": _solid_medium_borders(),
                        }
                    },
                    "fields": (
                        "userEnteredFormat(backgroundColor,textFormat,"
                        "horizontalAlignment,verticalAlignment,"
                        "wrapStrategy,borders)"
                    ),
                }
            }
        )
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": header_row + 1,
                        "endRowIndex": end_row,
                        "startColumnIndex": ci,
                        "endColumnIndex": ci + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "horizontalAlignment": "LEFT",
                            "wrapStrategy": "CLIP",
                        }
                    },
                    "fields": (
                        "userEnteredFormat(horizontalAlignment,wrapStrategy)"
                    ),
                }
            }
        )

    # Notes column: CLIP so long หมายเหตุ doesn't blow row height
    ci = OVERVIEW_NOTES_COL_INDEX
    requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": header_row + 1,
                    "endRowIndex": end_row,
                    "startColumnIndex": ci,
                    "endColumnIndex": ci + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "LEFT",
                        "wrapStrategy": "CLIP",
                    }
                },
                "fields": (
                    "userEnteredFormat(horizontalAlignment,wrapStrategy)"
                ),
            }
        }
    )

    return requests


def _format_overview_chrome(ss, ws) -> None:
    """Apply ชีตสำหรับทำงาน-style decoration on「ทรัพย์รวม」(chrome + table)."""
    sid = ws.id
    cols = len(OVERVIEW_HEADERS)
    try:
        data_end = max(int(ws.row_count or 0), OVERVIEW_DATA_START + 50)
    except Exception:
        data_end = 3000

    def rng(r0: int, r1: int, c0: int = 0, c1: int | None = None):
        return {
            "sheetId": sid,
            "startRowIndex": r0,
            "endRowIndex": r1,
            "startColumnIndex": c0,
            "endColumnIndex": cols if c1 is None else c1,
        }

    requests: list[dict] = []
    requests.extend(_delete_banded_range_requests(ss, sid))
    requests.extend(
        [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": sid,
                        "gridProperties": {
                            # Freeze search chrome rows. (Col-A freeze is incompatible
                            # with A1:P / A4:P merges used by the chrome title/status.)
                            "frozenRowCount": OVERVIEW_HEADER_ROW,
                            "frozenColumnCount": 0,
                            "hideGridlines": False,
                        },
                    },
                    "fields": (
                        "gridProperties.frozenRowCount,"
                        "gridProperties.frozenColumnCount,"
                        "gridProperties.hideGridlines"
                    ),
                }
            },
            # Unmerge before re-merge (idempotent re-apply on sync).
            {"unmergeCells": {"range": rng(0, 1)}},
            {"unmergeCells": {"range": rng(1, 2, 3, cols)}},
            {"unmergeCells": {"range": rng(2, 3, 3, cols)}},
            {"unmergeCells": {"range": rng(3, 4)}},
            {
                "mergeCells": {
                    "range": rng(0, 1),
                    "mergeType": "MERGE_ALL",
                }
            },
            {
                "mergeCells": {
                    "range": rng(1, 2, 3, cols),
                    "mergeType": "MERGE_ALL",
                }
            },
            {
                "mergeCells": {
                    "range": rng(2, 3, 3, cols),
                    "mergeType": "MERGE_ALL",
                }
            },
            {
                "mergeCells": {
                    "range": rng(3, 4),
                    "mergeType": "MERGE_ALL",
                }
            },
            {
                "repeatCell": {
                    "range": rng(0, 1),
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": _hex_rgb(CLR_TITLE_BG),
                            "textFormat": {
                                "foregroundColor": _hex_rgb(CLR_TITLE_FG),
                                "fontSize": 14,
                                "bold": True,
                                "fontFamily": "Arial",
                            },
                            "verticalAlignment": "MIDDLE",
                        }
                    },
                    "fields": (
                        "userEnteredFormat(backgroundColor,textFormat,"
                        "verticalAlignment)"
                    ),
                }
            },
            {
                "repeatCell": {
                    "range": rng(1, 3),
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": _hex_rgb(CLR_ROW_BG),
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            },
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sid,
                        "startRowIndex": 1,
                        "endRowIndex": 3,
                        "startColumnIndex": 2,
                        "endColumnIndex": 3,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": _hex_rgb(CLR_SEARCH_BG),
                            "textFormat": {
                                "fontSize": 12,
                                "bold": True,
                                "fontFamily": "Arial",
                            },
                            "borders": {
                                "top": {
                                    "style": "SOLID_MEDIUM",
                                    "color": _hex_rgb(CLR_SEARCH_BORDER),
                                },
                                "bottom": {
                                    "style": "SOLID_MEDIUM",
                                    "color": _hex_rgb(CLR_SEARCH_BORDER),
                                },
                                "left": {
                                    "style": "SOLID_MEDIUM",
                                    "color": _hex_rgb(CLR_SEARCH_BORDER),
                                },
                                "right": {
                                    "style": "SOLID_MEDIUM",
                                    "color": _hex_rgb(CLR_SEARCH_BORDER),
                                },
                            },
                        }
                    },
                    "fields": (
                        "userEnteredFormat(backgroundColor,textFormat,borders)"
                    ),
                }
            },
            {
                "repeatCell": {
                    "range": rng(3, 4),
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": _hex_rgb(CLR_STATUS_BG),
                            "textFormat": {
                                "foregroundColor": _hex_rgb(CLR_MUTED),
                                "fontSize": 10,
                                "fontFamily": "Arial",
                            },
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat)",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sid,
                        "dimension": "ROWS",
                        "startIndex": 0,
                        "endIndex": 1,
                    },
                    "properties": {"pixelSize": 38},
                    "fields": "pixelSize",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sid,
                        "dimension": "ROWS",
                        "startIndex": 1,
                        "endIndex": 3,
                    },
                    "properties": {"pixelSize": 34},
                    "fields": "pixelSize",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sid,
                        "dimension": "ROWS",
                        "startIndex": 3,
                        "endIndex": 4,
                    },
                    "properties": {"pixelSize": 22},
                    "fields": "pixelSize",
                }
            },
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sid,
                        "dimension": "ROWS",
                        "startIndex": 4,
                        "endIndex": 5,
                    },
                    "properties": {"pixelSize": 21},
                    "fields": "pixelSize",
                }
            },
        ]
    )
    requests.extend(
        _format_overview_table_body(
            sid,
            header_row=OVERVIEW_HEADER_ROW - 1,  # 0-based row 4 = sheet row 5
            data_end_row=data_end,
            cols=cols,
        )
    )
    requests.extend(_col_width_requests(sid, OVERVIEW_COL_WIDTHS))

    try:
        ss.batch_update({"requests": requests})
    except Exception as exc:  # noqa: BLE001
        # Formatting is best-effort; values/formula still work.
        try:
            import os as _os

            if _os.environ.get("HUB_SHEET_FORMAT_DEBUG"):
                print(f"_format_overview_chrome warn: {exc}", flush=True)
        except Exception:
            pass


def _format_overview_src(ss, src) -> None:
    """Style hidden `_overview_src` like work-sheet table (for consistency when synced)."""
    sid = src.id
    cols = len(OVERVIEW_HEADERS)
    try:
        data_end = max(int(src.row_count or 0), 50)
    except Exception:
        data_end = 3000

    requests: list[dict] = []
    requests.extend(_delete_banded_range_requests(ss, sid))
    requests.append(
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sid,
                    "hidden": True,
                    "gridProperties": {
                        "frozenRowCount": 1,
                        "frozenColumnCount": 1,
                        "hideGridlines": False,
                    },
                },
                "fields": (
                    "hidden,gridProperties.frozenRowCount,"
                    "gridProperties.frozenColumnCount,"
                    "gridProperties.hideGridlines"
                ),
            }
        }
    )
    requests.extend(
        _format_overview_table_body(
            sid,
            header_row=0,
            data_end_row=data_end,
            cols=cols,
        )
    )
    requests.extend(_col_width_requests(sid, OVERVIEW_COL_WIDTHS))
    try:
        ss.batch_update({"requests": requests})
    except Exception:
        pass


def ensure_overview_search_chrome(
    ss,
    ws,
    *,
    synced_at: str = "",
    row_count: int | None = None,
) -> dict:
    """
    Install/restore rows 1–5 search chrome + FILTER formula on overview tab.

    Matches「ชีตสำหรับทำงาน」decoration (gold header, peach banding, freeze col A,
    yellow link headers, #,##0). Data lives on hidden `_overview_src`.
    """
    cols = len(OVERVIEW_HEADERS)
    status = (
        f"ว่างทั้ง C2+C3 = ทั้งหมด · กรอกทั้งคู่ = AND · ซิงค์จากแอป"
        + (f" · อัปเดต: {synced_at}" if synced_at else "")
        + (f" · {row_count:,} รายการ" if row_count is not None else "")
        + " · เรียงใหม่→เก่า"
    )
    chrome_rows = [
        [
            "Property Hub · ทรัพย์รวม (PTP + RXT) — เรียงใหม่→เก่า · ค้นหาด้านบน"
        ]
        + [""] * (cols - 1),
        [
            "ค้นหาทั่วไป",
            "→",
            "",
            "เช่น PTP8088 · Life Asoke · Thru / หมายเหตุ (ไม่บังคับ)",
        ]
        + [""] * (cols - 4),
        [
            "ค้นหาทำเล/BTS",
            "→",
            "",
            "เช่น ทองหล่อ · อโศก · BTS อ่อนนุช (ไม่บังคับ)",
        ]
        + [""] * (cols - 4),
        [status] + [""] * (cols - 1),
        list(OVERVIEW_HEADERS),
    ]

    # Preserve existing search terms when re-applying chrome
    try:
        prev = ws.get("C2:C3")
        c2 = str((prev[0] or [""])[0] or "") if prev else ""
        c3 = str((prev[1] or [""])[0] or "") if prev and len(prev) > 1 else ""
    except Exception:
        c2, c3 = "", ""

    try:
        last = max(ws.row_count, OVERVIEW_DATA_START)
        if last >= OVERVIEW_DATA_START:
            ws.batch_clear([f"A{OVERVIEW_DATA_START}:{OVERVIEW_END_COL}{last}"])
    except Exception:
        pass

    ws.update(f"A1:{OVERVIEW_END_COL}5", chrome_rows, value_input_option="RAW")
    if c2 or c3:
        ws.update("C2:C3", [[c2], [c3]], value_input_option="USER_ENTERED")

    _install_overview_data_formulas(ws)
    _format_overview_chrome(ss, ws)
    return {"chrome_installed": True, "filter_cell": "A6"}


def _install_overview_data_formulas(ws) -> None:
    """Install A6 FILTER (A:L) + M6:P6 HYPERLINKs + Q6 หมายเหตุ."""
    try:
        last = max(int(getattr(ws, "row_count", 0) or 0), OVERVIEW_DATA_START)
        if last >= OVERVIEW_DATA_START:
            # Clear prior multi-col FILTER spill / stale link + notes formulas.
            ws.batch_clear([f"A{OVERVIEW_DATA_START}:{OVERVIEW_END_COL}{last}"])
    except Exception:
        pass
    ws.update(
        "A6",
        [[OVERVIEW_FILTER_FORMULA]],
        value_input_option="USER_ENTERED",
    )
    link_rows = [[
        OVERVIEW_LINK_FORMULAS["M6"],
        OVERVIEW_LINK_FORMULAS["N6"],
        OVERVIEW_LINK_FORMULAS["O6"],
        OVERVIEW_LINK_FORMULAS["P6"],
        OVERVIEW_NOTES_FORMULA,
    ]]
    ws.update(f"M6:{OVERVIEW_END_COL}6", link_rows, value_input_option="USER_ENTERED")


def _write_overview_src(
    ss, values: list[list], *, format_sheet: bool = True
) -> dict:
    """Replace hidden `_overview_src` table (headers + data).

    Writes first, then clears only leftover rows below — never clear-all-then-write,
    which left FILTER showing blank ทำเล/สถานี when a sync timed out mid-update.
    """
    n = len(OVERVIEW_HEADERS)
    data_rows = values[1:] if values and list(values[0])[:n] == OVERVIEW_HEADERS else values
    # Pad/truncate every row so FILTER/VLOOKUP column indexes stay aligned
    # after header upgrades (e.g. หมายเหตุ added as col Q).
    normalized: list[list] = []
    for row in data_rows:
        r = list(row or []) + [""] * max(0, n - len(row or []))
        normalized.append(r[:n])
    full = [list(OVERVIEW_HEADERS)] + normalized
    src = _open_or_create_src_sheet(ss, rows=len(full) + 10)
    _update_values_chunked(src, full, start_row=1)
    try:
        last = max(int(src.row_count or 0), len(full))
        if last > len(full):
            src.batch_clear([f"A{len(full) + 1}:{OVERVIEW_END_COL}{last}"])
    except Exception:
        pass
    if format_sheet:
        _format_overview_src(ss, src)
    return {
        "sheet_title": src.title,
        "rows_written": len(normalized),
        "gid": src.id,
        "columns": n,
    }


def _write_overview_values(ws, values: list[list], *, synced_at: str, ss=None) -> dict:
    """Replace overview data; preserve search chrome + FILTER when present."""
    meta: dict = {"sheet_title": ws.title, "data_start_row": 1}
    if _tab_forbidden(ws.title):
        raise ValueError(f"ห้ามเขียนแท็บ「{ws.title}」")

    data_rows = values[1:] if values and values[0] == OVERVIEW_HEADERS else values
    spreadsheet = ss or getattr(ws, "spreadsheet", None)

    # Prefer chrome + FILTER path whenever we can access the parent spreadsheet.
    if spreadsheet is not None:
        try:
            if not _worksheet_has_dashboard_chrome(ws):
                # Install chrome first (includes FILTER); then fill backing data.
                ensure_overview_search_chrome(
                    spreadsheet,
                    ws,
                    synced_at=synced_at,
                    row_count=len(data_rows),
                )
                src_meta = _write_overview_src(
                    spreadsheet, values, format_sheet=False
                )
            else:
                # Write backing data FIRST so a timeout cannot leave FILTER over
                # an empty `_overview_src` after formula reinstall clears A6:Q.
                src_meta = _write_overview_src(
                    spreadsheet, values, format_sheet=False
                )
                # Refresh status + keep FILTER / link / notes formulas current
                try:
                    ws.update(
                        "A4",
                        [[
                            f"ว่างทั้ง C2+C3 = ทั้งหมด · กรอกทั้งคู่ = AND · "
                            f"ซิงค์จากแอป · อัปเดต: {synced_at} · "
                            f"{len(data_rows):,} รายการ · เรียงใหม่→เก่า"
                        ]],
                        value_input_option="RAW",
                    )
                except Exception:
                    pass
                # Keep header strip in sync when columns are added (e.g. หมายเหตุ).
                try:
                    ws.update(
                        f"A{OVERVIEW_HEADER_ROW}:{OVERVIEW_END_COL}{OVERVIEW_HEADER_ROW}",
                        [list(OVERVIEW_HEADERS)],
                        value_input_option="RAW",
                    )
                except Exception:
                    pass
                # Re-apply formulas so upgrades (clickable HYPERLINKs + หมายเหตุ) deploy.
                # Skip heavy decoration on routine syncs (Render ~30s limit).
                _install_overview_data_formulas(ws)

            meta["data_start_row"] = OVERVIEW_DATA_START
            meta["chrome_preserved"] = True
            meta["filter_mode"] = True
            meta["src_sheet"] = src_meta.get("sheet_title")
            meta["rows_written"] = int(src_meta.get("rows_written") or 0)
            meta["overview_columns"] = int(
                src_meta.get("columns") or len(OVERVIEW_HEADERS)
            )
            return meta
        except Exception as exc:  # noqa: BLE001
            meta["chrome_error"] = str(exc)

    # Fallback: legacy flat write (no search chrome)
    if _worksheet_has_dashboard_chrome(ws):
        meta["data_start_row"] = OVERVIEW_DATA_START
        meta["chrome_preserved"] = True
        try:
            last = max(ws.row_count, OVERVIEW_DATA_START)
            if last >= OVERVIEW_DATA_START:
                ws.batch_clear([f"A{OVERVIEW_DATA_START}:{OVERVIEW_END_COL}{last}"])
        except Exception:
            try:
                ws.clear()
                meta["chrome_preserved"] = False
                meta["data_start_row"] = 1
                _update_values_chunked(
                    ws, _overview_values_with_hyperlinks(values), start_row=1
                )
                meta["rows_written"] = max(0, len(values) - 1)
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
                value_input_option="RAW",
            )
        except Exception:
            pass
        if data_rows:
            _update_values_chunked(
                ws,
                _overview_data_with_hyperlinks(data_rows),
                start_row=OVERVIEW_DATA_START,
            )
        meta["rows_written"] = len(data_rows)
        return meta

    ws.clear()
    _update_values_chunked(
        ws, _overview_values_with_hyperlinks(values), start_row=1
    )
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

    # New-sheet clones often keep hub gid but title「Sale」— rename to app name.
    if ws is not None and (ws.title or "").strip() != hub_name:
        if (ws.title or "").strip().lower() == "sale":
            try:
                ws.update_title(hub_name)
            except Exception:
                pass

    values = [HUB_HEADERS] + hub_rows
    # Header row sometimes has P1:Q1 merged (Pages + หมายเหตุ) which blanks หมายเหตุ.
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
                                "startColumnIndex": 15,
                                "endColumnIndex": 17,
                            }
                        }
                    }
                ]
            }
        )
    except Exception:
        pass
    ws.clear()
    _update_values_chunked(ws, values, start_row=1)
    return {
        "sheet_title": ws.title,
        "rows_written": len(hub_rows),
        "created_sheet": hub_name if created else "",
        "gid": ws.id,
    }


def sync_notes_to_main_sheet(
    ss,
    properties: list[dict],
    *,
    sheet_name: str | None = None,
) -> dict:
    """Write Hub `notes` back onto「ชีตสำหรับทำงาน」หมายเหตุ by matching รหัสทรัพย์.

    Only updates cells that differ. Does not insert/delete rows.
    """
    tab = (
        sheet_name
        or _env("MAIN_SHEET_NAME")
        or _env("HUB_MAIN_SHEET_NAME")
        or "ชีตสำหรับทำงาน"
    ).strip()
    if _tab_forbidden(tab):
        raise ValueError(f"ห้ามเขียนแท็บ「{tab}」")
    ws = ss.worksheet(tab)
    headers = ws.row_values(1)
    if "รหัสทรัพย์" not in headers:
        raise ValueError(f"「{tab}」ไม่มีคอลัมน์รหัสทรัพย์")
    if "หมายเหตุ" not in headers:
        # Insert before ลิ้งค์ต้นโพสต์ when present, else append.
        if "ลิ้งค์ต้นโพสต์" in headers:
            insert_at = headers.index("ลิ้งค์ต้นโพสต์")
        else:
            insert_at = len(headers)
        ws.insert_cols([[]], col=insert_at + 1)
        ws.update_cell(1, insert_at + 1, "หมายเหตุ")
        headers = ws.row_values(1)

    code_i = headers.index("รหัสทรัพย์")
    notes_i = headers.index("หมายเหตุ")
    code_letter = _col_a1(code_i + 1)
    notes_letter = _col_a1(notes_i + 1)

    codes = ws.col_values(code_i + 1)
    current = ws.col_values(notes_i + 1)
    by_code: dict[str, str] = {}
    for p in properties:
        code = _norm_prop_code(p.get("code"))
        if not code:
            continue
        by_code[code] = _notes_for_sheet(p.get("notes"))

    updates: list[dict] = []
    checked = 0
    for row_idx in range(2, len(codes) + 1):
        code = _norm_prop_code(codes[row_idx - 1] if row_idx - 1 < len(codes) else "")
        if not code or code not in by_code:
            continue
        checked += 1
        new_note = by_code[code]
        old = ""
        if row_idx - 1 < len(current):
            old = str(current[row_idx - 1] or "").strip()
        if _notes_for_sheet(old) == new_note:
            continue
        updates.append(
            {
                "range": f"{notes_letter}{row_idx}",
                "values": [[new_note]],
            }
        )

    # Batch in chunks (Sheets API ~100 ranges / request is comfortable).
    written = 0
    chunk = 200
    for i in range(0, len(updates), chunk):
        part = updates[i : i + chunk]
        ws.batch_update(part, value_input_option="USER_ENTERED")
        written += len(part)

    return {
        "sheet_title": ws.title,
        "notes_col": notes_letter,
        "code_col": code_letter,
        "matched": checked,
        "updated": written,
    }


def _wait_post_spreadsheet_id() -> str:
    """Spreadsheet that owns the「รอโพสต์」tab (source / main sheet)."""
    return (
        _env("SOURCE_GOOGLE_SHEETS_ID")
        or _env("MAIN_GOOGLE_SHEETS_ID")
        or _env("HUB_SOURCE_GOOGLE_SHEETS_ID")
        or _env("HUB_GOOGLE_SHEETS_ID")
        or _env("GOOGLE_SHEETS_ID")
    )


def _wait_post_sheet_name() -> str:
    return (
        _env("WAIT_POST_SHEET_NAME")
        or _env("HUB_WAIT_SHEET_NAME")
        or "รอโพสต์"
    ).strip() or "รอโพสต์"


def append_wait_post_job(
    source_url: str,
    owner_contact: str = "",
    note: str = "",
    project: str = "",
    price: str = "",
    queued_at: str = "",
) -> dict:
    """Append one queue row to Google Sheet「รอโพสต์」(shared SoT for Fly).

    Live sheet layout (observed): blank A | note | source | owner | project | price | date.
    Writing 6 values from A made Sheets append into the B-start table and shift
    project into the note column — always write 7 cols with leading blank + table_range.
    """
    source_url = (source_url or "").strip()
    if not source_url:
        raise ValueError("ต้องมีลิงก์ต้นทาง")
    sheet_id = _wait_post_spreadsheet_id()
    if not sheet_id:
        raise ValueError(
            "ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับเขียนแท็บรอโพสต์"
        )
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    tab = _wait_post_sheet_name()
    if _tab_forbidden(tab):
        raise ValueError(f"ห้ามเขียนแท็บ「{tab}」")
    try:
        ws = ss.worksheet(tab)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"ไม่พบแท็บ「{tab}」ในชีท") from exc

    # Source URL lives in column C on the live sheet (B is note).
    for col_idx in (3, 2):
        for cell in ws.col_values(col_idx):
            if (cell or "").strip() == source_url:
                return {
                    "ok": True,
                    "appended": False,
                    "duplicate": True,
                    "sheet_title": ws.title,
                    "spreadsheet_id": sheet_id,
                }

    # Leading blank keeps Hub writes aligned with existing sheet rows.
    row = [
        "",
        (note or "").strip(),
        source_url,
        (owner_contact or "").strip(),
        (project or "").strip(),
        (price or "").strip(),
        (queued_at or "").strip(),
    ]
    ws.append_row(
        row,
        value_input_option="USER_ENTERED",
        table_range="A:G",
    )
    return {
        "ok": True,
        "appended": True,
        "duplicate": False,
        "sheet_title": ws.title,
        "spreadsheet_id": sheet_id,
        "row": row,
    }


def update_wait_post_job(
    source_url: str,
    *,
    owner_contact: str = "",
    note: str = "",
    project: str = "",
    price: str = "",
    queued_at: str = "",
    old_source_url: str = "",
) -> dict:
    """Update the sheet row matching source_url (or old_source_url when URL changed)."""
    source_url = (source_url or "").strip()
    find_url = (old_source_url or source_url).strip()
    if not find_url:
        raise ValueError("ต้องมีลิงก์ต้นทาง")
    sheet_id = _wait_post_spreadsheet_id()
    if not sheet_id:
        raise ValueError(
            "ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับเขียนแท็บรอโพสต์"
        )
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    tab = _wait_post_sheet_name()
    ws = ss.worksheet(tab)
    rows = ws.get_all_values()
    new_row = [
        "",
        (note or "").strip(),
        source_url,
        (owner_contact or "").strip(),
        (project or "").strip(),
        (price or "").strip(),
        (queued_at or "").strip(),
    ]
    updated = 0
    for idx, row in enumerate(rows, start=1):
        if any((cell or "").strip() == find_url for cell in row) or any(
            find_url in (cell or "") for cell in row
        ):
            ws.update(f"A{idx}:G{idx}", [new_row], value_input_option="USER_ENTERED")
            updated += 1
            break
    if not updated:
        ws.append_row(
            new_row,
            value_input_option="USER_ENTERED",
            table_range="A:G",
        )
        return {
            "ok": True,
            "updated": False,
            "appended": True,
            "sheet_title": ws.title,
            "spreadsheet_id": sheet_id,
        }
    return {
        "ok": True,
        "updated": True,
        "appended": False,
        "sheet_title": ws.title,
        "spreadsheet_id": sheet_id,
    }


def delete_wait_post_job(source_url: str) -> dict:
    """Remove rows from「รอโพสต์」that contain the source URL in any cell."""
    source_url = (source_url or "").strip()
    if not source_url:
        raise ValueError("ต้องมีลิงก์ต้นทาง")
    sheet_id = _wait_post_spreadsheet_id()
    if not sheet_id:
        raise ValueError(
            "ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับเขียนแท็บรอโพสต์"
        )
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    tab = _wait_post_sheet_name()
    ws = ss.worksheet(tab)
    rows = ws.get_all_values()
    # Delete from bottom so indices stay valid
    removed = 0
    for idx in range(len(rows), 0, -1):
        row = rows[idx - 1]
        if any((cell or "").strip() == source_url for cell in row):
            ws.delete_rows(idx)
            removed += 1
            continue
        # Also match when URL is embedded in a longer cell / HYPERLINK label
        if any(source_url in (cell or "") for cell in row):
            ws.delete_rows(idx)
            removed += 1
    return {
        "ok": True,
        "removed": removed,
        "sheet_title": ws.title,
        "spreadsheet_id": sheet_id,
    }


def pull_wait_post_sheet_via_gspread() -> dict:
    """Download「รอโพสต์」via service account into wait_post_sheet.csv.

    Prefer this over public CSV export URLs (often HTTP 401 on locked sheets).
    """
    import csv

    sheet_id = _wait_post_spreadsheet_id()
    if not sheet_id:
        raise ValueError(
            "ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับดึงแท็บรอโพสต์"
        )
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    tab = _wait_post_sheet_name()
    ws = ss.worksheet(tab)
    rows = ws.get_all_values()
    wait_csv = BASE_DIR / "data" / "wait_post_sheet.csv"
    wait_csv.parent.mkdir(parents=True, exist_ok=True)
    with wait_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        for row in rows:
            # Keep trailing empties trimmed like export, but preserve note/url cols
            while row and not (row[-1] or "").strip():
                row = row[:-1]
            if any((c or "").strip() for c in row):
                writer.writerow(row)
    return {
        "ok": True,
        "downloaded": True,
        "source": "gspread",
        "rows": len(rows),
        "sheet_title": ws.title,
        "spreadsheet_id": sheet_id,
        "path": str(wait_csv),
    }


def _cell_http_url(raw: str) -> str:
    """Extract http(s) URL from a plain cell or =HYPERLINK(\"url\",\"label\")."""
    s = str(raw or "").strip()
    if not s:
        return ""
    if _is_http_url(s):
        return s
    m = re.search(r'HYPERLINK\s*\(\s*"([^"]+)"', s, flags=re.I)
    if m and _is_http_url(m.group(1)):
        return m.group(1).strip()
    return ""


_LINK_JUNK = {
    "ต้นทาง",
    "เจ้าของ",
    "ที่โพสต์",
    "เพจ",
    "โพสต์",
    "หมายเหตุ",
    "ลิ้งค์โพส",
    "ลิงก์",
}


def _fill_blank_prop_links(prop: dict, *, source: str, owner: str, post: str, page: str) -> bool:
    """Fill blank Hub link fields from a backup row. Never clobber non-empty Hub URLs."""
    changed = False
    src = _cell_http_url(source)
    own = _cell_http_url(owner)
    pst = _cell_http_url(post)
    pg = _cell_http_url(page)
    if src in _LINK_JUNK:
        src = ""
    if own in _LINK_JUNK:
        own = ""
    if pst in _LINK_JUNK:
        pst = ""
    if pg in _LINK_JUNK:
        pg = ""

    if src and not _is_http_url(str(prop.get("source_url") or "")):
        prop["source_url"] = src
        changed = True
    if pst and not _is_http_url(str(prop.get("post_url") or "")):
        prop["post_url"] = pst
        prop["media_status"] = "has_link"
        changed = True
    if pg and not _is_http_url(str(prop.get("post_pages_url") or "")):
        prop["post_pages_url"] = pg
        changed = True
    if own:
        cur = prop.get("owner_facebook") or []
        if isinstance(cur, str):
            cur = [cur] if cur.strip() else []
        if not any(_is_http_url(str(x)) for x in cur):
            prop["owner_facebook"] = [own]
            changed = True
    return changed


def _fill_blank_links_from_csv_backup(properties: list[dict]) -> int:
    """Use last local overview export so a blank Hub field does not wipe sheet URLs."""
    import csv

    path = OVERVIEW_EXPORT_CSV
    if not path.is_file():
        return 0
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return 0
    by_code = {
        (r.get("รหัส") or "").strip().upper(): r
        for r in rows
        if (r.get("รหัส") or "").strip()
    }
    filled = 0
    for p in properties:
        code = (p.get("code") or "").strip().upper()
        row = by_code.get(code)
        if not row:
            continue
        if _fill_blank_prop_links(
            p,
            source=row.get("ต้นทาง") or "",
            owner=row.get("เจ้าของ") or "",
            post=row.get("ที่โพสต์") or "",
            page=row.get("เพจ") or "",
        ):
            filled += 1
    return filled


def _fill_blank_links_from_overview_src(ss, properties: list[dict]) -> int:
    """Read `_overview_src` before overwrite; keep existing sheet URLs when Hub is blank."""
    try:
        ws = ss.worksheet(OVERVIEW_SRC_SHEET)
        vals = ws.get_all_values()
    except Exception:
        return 0
    if not vals:
        return 0
    hdr = vals[0]
    idx = {h: i for i, h in enumerate(hdr)}
    if "รหัส" not in idx:
        return 0
    by_code: dict[str, list] = {}
    for r in vals[1:]:
        if not r:
            continue
        code = (r[idx["รหัส"]] if idx["รหัส"] < len(r) else "").strip().upper()
        if code:
            by_code[code] = r

    def cell(row: list, name: str) -> str:
        i = idx.get(name)
        if i is None or i >= len(row):
            return ""
        return str(row[i] or "")

    filled = 0
    for p in properties:
        code = (p.get("code") or "").strip().upper()
        row = by_code.get(code)
        if not row:
            continue
        if _fill_blank_prop_links(
            p,
            source=cell(row, "ต้นทาง"),
            owner=cell(row, "เจ้าของ"),
            post=cell(row, "ที่โพสต์"),
            page=cell(row, "เพจ"),
        ):
            filled += 1
    return filled


def push_hub_properties_to_sheet(properties: list[dict] | None = None) -> dict:
    """
    Sync app listings to the Hub working Google Sheet (one-way Hub → Sheet).

    1) Overview tab「ทรัพย์รวม」(configurable) — all active props, newest-first
    2)「ทรัพย์ Hub」— Hub-owned (RXT/COA) only (secondary / Apps Script source)

    Order: gspread service account (preferred for large writes) → Apps Script webapp
    → local CSV export only (pushed=false).

    Never blanks sheet link columns when Hub is empty but the previous sheet/CSV
    still has a URL.
    """
    from src.hub.project_store import load_projects, load_properties, persist

    # Working copy so blank-link fill does not mutate caller lists unexpectedly.
    all_props = (
        load_properties() if properties is None else [dict(p) for p in properties]
    )
    links_filled = _fill_blank_links_from_csv_backup(all_props)

    sheet_id = _env("HUB_GOOGLE_SHEETS_ID") or _env("GOOGLE_SHEETS_ID")
    client = None
    ss = None
    warnings: list[str] = []
    try:
        client = _gspread_client()
    except Exception as exc:  # noqa: BLE001
        warnings.append(str(exc))
        client = None

    if client and sheet_id and not sheet_id.startswith("your_"):
        try:
            ss = client.open_by_key(sheet_id)
            links_filled += _fill_blank_links_from_overview_src(ss, all_props)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"overview_src link merge: {exc}")
            ss = None

    if links_filled and properties is None:
        try:
            persist(load_projects(), all_props)
        except Exception as persist_exc:  # noqa: BLE001
            warnings.append(f"persist filled links: {persist_exc}")

    # Refresh Hub listing locations (persist when reading from disk)
    hub_props, projects_by_id, loc_refreshed = refresh_hub_listing_locations(
        list(all_props),
        persist_disk=properties is None,
    )
    if properties is None:
        all_props = load_properties()

    overview_props = active_properties_for_overview(all_props)
    export_overview = write_overview_export_csv(
        overview_props, projects_by_id=projects_by_id
    )
    export_hub = write_hub_export_csv(hub_props, projects_by_id=projects_by_id)

    synced = datetime.now().strftime("%d/%m/%Y %H:%M")
    # `_overview_src` keeps raw URLs; visible FILTER rebuilds short HYPERLINKs.
    # CSV export above also keeps raw URLs.
    overview_rows = [
        prop_to_overview_row(
            p, projects_by_id=projects_by_id, link_as_hyperlink=False
        )
        for p in overview_props
    ]
    hub_rows = [
        prop_to_hub_row(
            p, synced, projects_by_id=projects_by_id, link_as_hyperlink=True
        )
        for p in hub_props
    ]

    result: dict = {
        "ok": True,
        "hub_count": len(hub_props),
        "overview_count": len(overview_props),
        "written_count": 0,
        "location_refreshed": loc_refreshed,
        "links_filled_from_backup": links_filled,
        "export_csv": str(export_overview.relative_to(BASE_DIR)),
        "hub_export_csv": str(export_hub.relative_to(BASE_DIR)),
        "pushed": False,
        "synced_at": synced,
        "sort": "newest_first",
    }

    hub_name = _env("HUB_SHEET_NAME") or "ทรัพย์ Hub"
    hub_gid = _env("HUB_SHEET_GID")

    # --- gspread path (handles 7k+ overview rows) ---
    if client and sheet_id and not sheet_id.startswith("your_"):
        try:
            if ss is None:
                ss = client.open_by_key(sheet_id)
            overview_ws, created = _resolve_overview_worksheet(
                ss, rows=len(overview_rows) + 10
            )
            overview_values = [OVERVIEW_HEADERS] + overview_rows
            ov_meta = _write_overview_values(
                overview_ws, overview_values, synced_at=synced, ss=ss
            )
            result["pushed"] = True
            result["via"] = "gspread"
            result["spreadsheet_id"] = sheet_id
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
            source_id = (
                _env("SOURCE_GOOGLE_SHEETS_ID")
                or _env("MAIN_GOOGLE_SHEETS_ID")
                or _env("HUB_SOURCE_GOOGLE_SHEETS_ID")
            )
            if source_id and source_id != sheet_id:
                warnings.append(
                    f"ซิงค์ไปชีท {sheet_id[:8]}… แต่ SOURCE ดึงจาก {source_id[:8]}… "
                    "— ตรวจ HUB_GOOGLE_SHEETS_ID / SOURCE_GOOGLE_SHEETS_ID ใน .env"
                )

            try:
                hub_meta = _write_hub_tab(
                    ss, hub_rows, hub_name=hub_name, hub_gid=hub_gid
                )
                result["hub_sheet_title"] = hub_meta.get("sheet_title")
                result["hub_rows_written"] = hub_meta.get("rows_written", 0)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"แท็บ「{hub_name}」: {exc}")

            try:
                notes_meta = sync_notes_to_main_sheet(ss, all_props)
                result["main_notes_updated"] = notes_meta.get("updated", 0)
                result["main_notes_matched"] = notes_meta.get("matched", 0)
                result["main_sheet_title"] = notes_meta.get("sheet_title")
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"หมายเหตุ→ชีตสำหรับทำงาน: {exc}")

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

    warn = " · ".join(warnings) if warnings else (
        "ซิงค์ชีทไม่สำเร็จ — ตรวจ Service Account / HUB_GOOGLE_SHEETS_ID"
    )
    result["push_warning"] = warn
    result["ok"] = False
    need_sa = any(
        "Service Account" in w
        or "GOOGLE_SERVICE_ACCOUNT_JSON" in w
        or "credentials/service_account" in w
        for w in warnings
    ) or "Service Account" in warn
    if need_sa:
        result.update(service_account_setup_payload(warning=warn))
    else:
        result["download_url"] = OVERVIEW_EXPORT_DOWNLOAD_PATH
    return result
