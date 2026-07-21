"""Push Hub-owned properties to the Google Sheet「ทรัพย์ Hub」tab."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from src.hub.codes import is_hub_owned

BASE_DIR = Path(__file__).resolve().parent.parent.parent
HUB_EXPORT_CSV = BASE_DIR / "data" / "hub_sheet_export.csv"
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


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _join_tags(tags) -> str:
    if isinstance(tags, list):
        return ", ".join(str(t) for t in tags if t)
    return str(tags or "").strip()


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

    # Orphan / no project — fall back to listing fields (still prefer location_ref)
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
            # Always overwrite — project details may have changed since last sync
            prop["location_ref"] = loc
            prop["transit_from_sheet"] = list(tags)
            if prop.get("project_name") != proj.get("canonical_name"):
                prop["project_name"] = proj.get("canonical_name") or prop.get("project_name")
            updated += 1
        hub_props.append(prop)

    if persist_disk and properties is None and all_props is not None and updated:
        # Mirror Hub field updates into the full properties list, then save
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
    owners = prop.get("owner_facebook") or []
    if isinstance(owners, list):
        owner_s = ", ".join(str(u) for u in owners if u)
    else:
        owner_s = str(owners or "")
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
        owner_s,
        "Hub",
        str(prop.get("linked_ptp_code") or ""),
        synced_at or datetime.now().strftime("%d/%m/%Y %H:%M"),
        str(prop.get("id") or ""),
    ]


def hub_properties_from_disk() -> list[dict]:
    if not PROPERTIES_JSON.exists():
        return []
    props = json.loads(PROPERTIES_JSON.read_text(encoding="utf-8"))
    return [p for p in props if is_hub_owned(p)]


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
            f"แล้วแชร์ชีทให้ email ของ service account เป็น Editor "
            f"(ตอนนี้ export ไว้ที่ {HUB_EXPORT_CSV.name} แทน)"
        )
    creds = Credentials.from_service_account_file(str(path), scopes=scopes)
    return gspread.authorize(creds)


def push_hub_properties_to_sheet(properties: list[dict] | None = None) -> dict:
    """
    Replace「ทรัพย์ Hub」tab contents with current Hub-owned rows.

    Every sync re-resolves ทำเล + สถานีรถไฟฟ้า from the project master used by the app
    (not stale sheet-only / listing-only values).

    Order: Apps Script webapp → gspread service account → local CSV only.
    """
    props, projects_by_id, loc_refreshed = refresh_hub_listing_locations(
        properties,
        persist_disk=properties is None,
    )

    export_path = write_hub_export_csv(props, projects_by_id=projects_by_id)
    synced = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows = [prop_to_hub_row(p, synced, projects_by_id=projects_by_id) for p in props]
    result: dict = {
        "ok": True,
        "hub_count": len(props),
        "location_refreshed": loc_refreshed,
        "export_csv": str(export_path.relative_to(BASE_DIR)),
        "pushed": False,
    }

    webapp = _env("HUB_SHEET_WEBAPP_URL") or _env("GOOGLE_SHEET_WEBAPP_URL")
    if webapp:
        try:
            import urllib.request

            payload = json.dumps(
                {"rows": rows, "headers": HUB_HEADERS},
                ensure_ascii=False,
            ).encode("utf-8")
            req = urllib.request.Request(
                webapp,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8", "replace") or "{}")
            if body.get("ok"):
                result["pushed"] = True
                result["via"] = "apps_script"
                result["sheet_title"] = body.get("sheet") or (_env("HUB_SHEET_NAME") or "ทรัพย์ Hub")
                return result
            result["push_warning"] = body.get("error") or "Apps Script ไม่สำเร็จ"
        except Exception as exc:  # noqa: BLE001
            result["push_warning"] = f"Apps Script: {exc}"

    sheet_id = _env("HUB_GOOGLE_SHEETS_ID") or _env("GOOGLE_SHEETS_ID")
    hub_name = _env("HUB_SHEET_NAME") or "ทรัพย์ Hub"
    hub_gid = _env("HUB_SHEET_GID")

    try:
        client = _gspread_client()
    except Exception as exc:  # noqa: BLE001
        result.setdefault("push_warning", str(exc))
        return result

    if not sheet_id or sheet_id.startswith("your_"):
        result["push_warning"] = (
            "ยังไม่ได้ตั้ง HUB_GOOGLE_SHEETS_ID / GOOGLE_SHEETS_ID (ชีททดลองสำหรับซิงค์กลับ)"
        )
        return result

    ss = client.open_by_key(sheet_id)
    ws = None
    try:
        if hub_gid:
            ws = ss.get_worksheet_by_id(int(hub_gid))
        if ws is None:
            ws = ss.worksheet(hub_name)
    except Exception:
        # try rename Sale
        try:
            ws = ss.worksheet("Sale")
            ws.update_title(hub_name)
            result["renamed_to"] = hub_name
        except Exception:
            ws = ss.add_worksheet(
                title=hub_name, rows=max(100, len(props) + 10), cols=len(HUB_HEADERS)
            )
            result["created_sheet"] = hub_name

    try:
        if ws and ws.title != hub_name:
            title_l = (ws.title or "").lower()
            if title_l == "sale" or not any((ws.col_values(1) or [""])[1:]):
                ws.update_title(hub_name)
                result["renamed_to"] = hub_name
    except Exception:
        pass

    values = [HUB_HEADERS] + rows
    ws.clear()
    ws.update(values, value_input_option="USER_ENTERED")
    result["pushed"] = True
    result["via"] = "gspread"
    result["sheet_title"] = ws.title
    result["spreadsheet_url"] = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid={ws.id}"
    )
    return result
