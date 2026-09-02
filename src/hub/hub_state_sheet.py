"""Google Sheet SoT for Hub Focus + customer follow-up + current tenants + location masters.

Tabs (on SOURCE / main spreadsheet — same as「รอโพสต์」):
  - Hubโฟกัส
  - Hubฟอโล่ว
  - Hubลูกค้าปัจจุบัน
  - Hubทำเล
  - HubBTS
  - Hubโครงการ

Never touches Focus🚨 / ลูกค้าหาเช่า / Follow (ops worksheets).
"""

from __future__ import annotations

from src.hub.sheet_write import _env, _gspread_client, _wait_post_spreadsheet_id


def _hub_state_spreadsheet_id() -> str:
    return (
        _env("HUB_STATE_GOOGLE_SHEETS_ID")
        or _wait_post_spreadsheet_id()
    )


def focus_sheet_name() -> str:
    return (_env("HUB_FOCUS_SHEET_NAME") or "Hubโฟกัส").strip() or "Hubโฟกัส"


def customers_sheet_name() -> str:
    return (_env("HUB_CUSTOMERS_SHEET_NAME") or "Hubฟอโล่ว").strip() or "Hubฟอโล่ว"


def tenants_sheet_name() -> str:
    return (
        _env("HUB_TENANTS_SHEET_NAME") or "Hubลูกค้าปัจจุบัน"
    ).strip() or "Hubลูกค้าปัจจุบัน"


def zones_sheet_name() -> str:
    return (_env("HUB_ZONES_SHEET_NAME") or "Hubทำเล").strip() or "Hubทำเล"


def transits_sheet_name() -> str:
    return (_env("HUB_TRANSITS_SHEET_NAME") or "HubBTS").strip() or "HubBTS"


def projects_sheet_name() -> str:
    return (_env("HUB_PROJECTS_SHEET_NAME") or "Hubโครงการ").strip() or "Hubโครงการ"


def _open_or_create(ss, name: str, *, cols: int):
    try:
        return ss.worksheet(name), False
    except Exception:
        ws = ss.add_worksheet(title=name, rows=200, cols=max(cols, 10))
        return ws, True


FOCUS_HEADERS = ["id", "code", "pinned_at"]


def push_focus_to_sheet(items: list[dict]) -> dict:
    sheet_id = _hub_state_spreadsheet_id()
    if not sheet_id:
        raise ValueError("ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับ Hubโฟกัส")
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    ws, created = _open_or_create(ss, focus_sheet_name(), cols=len(FOCUS_HEADERS))
    rows = [FOCUS_HEADERS]
    for it in items or []:
        rows.append(
            [
                str(it.get("id") or "").strip(),
                str(it.get("code") or "").strip(),
                str(it.get("pinned_at") or "").strip(),
            ]
        )
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    return {
        "ok": True,
        "pushed": True,
        "created_tab": created,
        "count": len(rows) - 1,
        "sheet_title": ws.title,
        "spreadsheet_id": sheet_id,
    }


def pull_focus_from_sheet() -> list[dict]:
    sheet_id = _hub_state_spreadsheet_id()
    if not sheet_id:
        raise ValueError("ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับ Hubโฟกัส")
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    try:
        ws = ss.worksheet(focus_sheet_name())
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"ไม่พบแท็บ「{focus_sheet_name()}」") from exc
    values = ws.get_all_values()
    if not values:
        return []
    header = [c.strip().lower() for c in values[0]]
    # Support headerless legacy: first cell looks like id
    start = 1
    if "id" not in header and "code" not in header:
        start = 0
        header = FOCUS_HEADERS

    def col(*names: str) -> int | None:
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_id = col("id", "property_id")
    i_code = col("code", "รหัส", "รหัสทรัพย์")
    i_pin = col("pinned_at", "pinned", "วันที่")
    out: list[dict] = []
    seen: set[str] = set()
    for row in values[start:]:
        if not any((c or "").strip() for c in row):
            continue
        pid = (row[i_id] if i_id is not None and i_id < len(row) else "").strip()
        code = (row[i_code] if i_code is not None and i_code < len(row) else "").strip()
        pinned = (row[i_pin] if i_pin is not None and i_pin < len(row) else "").strip()
        if not pid and code:
            # code-only rows: store code as temporary id until resolved in Hub
            pid = f"code:{code.upper().replace(' ', '')}"
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append({"id": pid, "code": code.upper().replace(" ", ""), "pinned_at": pinned})
    return out


# Customer sheet: id + Thai headers from customer_store.SHEET_HEADERS
def _customer_headers() -> list[str]:
    from src.hub.customer_store import SHEET_HEADERS

    return ["id", *SHEET_HEADERS]


def push_customers_to_sheet(items: list[dict]) -> dict:
    from src.hub.customer_store import case_to_sheet_row

    sheet_id = _hub_state_spreadsheet_id()
    if not sheet_id:
        raise ValueError("ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับ Hubฟอโล่ว")
    headers = _customer_headers()
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    ws, created = _open_or_create(ss, customers_sheet_name(), cols=len(headers))
    rows = [headers]
    for it in items or []:
        rows.append([str(it.get("id") or "").strip(), *case_to_sheet_row(it)])
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    return {
        "ok": True,
        "pushed": True,
        "created_tab": created,
        "count": len(rows) - 1,
        "sheet_title": ws.title,
        "spreadsheet_id": sheet_id,
    }


_STATUS_FROM_LABEL = {
    "ใหม่": "new",
    "ติดต่อแล้ว": "contacted",
    "รอข้อมูล": "waiting_info",
    "เสนอแล้ว": "offered",
    "นัดดู": "viewing",
    "นัดชม": "viewing",
    "รอตัดสินใจ": "deciding",
    "มัดจำแล้ว": "deposit",
    "มัดจำ": "deposit",
    "จองแล้ว": "reserved",
    "จอง": "reserved",
    "จอง/มัดจำ": "reserved",
    "รอทำสัญญา": "contract_pending",
    "เริ่มสัญญา": "contract_started",
    "สำเร็จ": "closed_won",
    "ปิดได้": "closed_won",
    "ยกเลิก": "closed_lost",
    "หลุด": "closed_lost",
    "พัก": "paused",
}
_KIND_FROM_LABEL = {
    "ลูกค้าตรง": "direct",
    "โคเอเจนต์": "co_agent",
    "โคเอเจ้นท์": "co_agent",
}
_DEAL_FROM_LABEL = {
    "เช่า": "rent",
    "ซื้อ": "sale",
    "เช่า+ซื้อ": "both",
}
_PRI_FROM_LABEL = {
    "สูง": "high",
    "กลาง": "normal",
    "ต่ำ": "low",
}


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def _sheet_row_to_case(header: list[str], row: list[str]) -> dict | None:
    from src.hub.customer_store import SHEET_HEADERS

    hmap = {h: i for i, h in enumerate(header)}

    def g(*names: str) -> str:
        for n in names:
            if n in hmap:
                return _cell(row, hmap[n])
        return ""

    cid = g("id")
    case_code = g("รหัสเคส")
    if not cid and not case_code and not g("ชื่อในแชท", "เบอร์"):
        return None

    status_raw = g("สถานะ")
    status = _STATUS_FROM_LABEL.get(status_raw, status_raw or "new")
    kind_raw = g("ประเภทลูกค้า")
    kind = _KIND_FROM_LABEL.get(kind_raw, kind_raw or "direct")
    deal_raw = g("ประเภทดีล")
    deal = _DEAL_FROM_LABEL.get(deal_raw, deal_raw or "rent")
    pri_raw = g("ลำดับความสำคัญ")
    priority = _PRI_FROM_LABEL.get(pri_raw, pri_raw or "normal")

    def split_codes(s: str) -> list[str]:
        if not s:
            return []
        import re

        parts = re.split(r"[,，|/\s]+", s)
        out = []
        seen = set()
        for p in parts:
            c = p.strip().upper()
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def split_list(s: str) -> list[str]:
        if not s:
            return []
        import re

        parts = re.split(r"[,，|/]+", s)
        out = []
        seen = set()
        for p in parts:
            t = p.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def as_int(s: str) -> int:
        try:
            return int(str(s).replace(",", "").replace(" ", "")) if s else 0
        except ValueError:
            return 0

    item = {
        "id": cid or "",
        "case_code": case_code,
        "channel": g("ช่องทาง") or "LINE OA",
        "customer_kind": kind,
        "chat_name": g("ชื่อในแชท"),
        "phone": g("เบอร์"),
        "line_id": g("LINE ID"),
        "owner": g("ผู้รับผิดชอบ"),
        "deal_type": deal,
        "inquiry_codes": split_codes(g("รหัสห้องที่ทักมา")),
        "first_contact_at": g("วันติดต่อครั้งแรก"),
        "last_contact_at": g("วันคุยล่าสุด"),
        "followup_in_days": as_int(g("ทักซ้ำในอีกกี่วัน")) or 3,
        "next_followup_at": g("วันฟอโล่วถัดไป"),
        "status": status,
        "status_date": g("วันที่สถานะ"),
        "lost_reason": g("เหตุผลหลุด"),
        "property_types": split_list(g("ประเภททรัพย์")),
        "locations": g("ทำเลที่ต้องการ"),
        "transits": split_list(g("BTS/MRT")),
        "budget_min": as_int(g("งบต่ำ")),
        "budget_max": as_int(g("งบสูง")),
        "bedrooms": split_list(g("ห้องนอน")),
        "move_in": g("เข้าอยู่ได้เมื่อ"),
        "constraints": g("สัตว์เลี้ยง/ที่จอด/อื่น"),
        "brief": g("โจทย์สั้นๆ"),
        "offered_codes": split_codes(g("รหัสที่เสนอแล้ว")),
        "offered_at": g("วันเสนอล่าสุด"),
        "offer_feedback": g("ผลตอบจากที่เสนอ"),
        "viewing_codes": split_codes(g("รหัสที่นัดดู")),
        "viewing_at": g("วันนัดชม"),
        "viewing_feedback": g("ผลหลังชม"),
        "reserved_codes": split_codes(g("รหัสจอง/มัดจำ")),
        "co_agent": g("ชื่อโคเอเจนต์"),
        "priority": priority,
        "tags": split_list(g("แท็ก")),
        "last_note": g("โน้ตฟอโล่วล่าสุด"),
        "chat_link": g("ลิงก์แชท"),
    }
    # Ensure we only keep known sheet fields (+ id)
    _ = SHEET_HEADERS
    return item


def pull_customers_from_sheet() -> list[dict]:
    sheet_id = _hub_state_spreadsheet_id()
    if not sheet_id:
        raise ValueError("ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับ Hubฟอโล่ว")
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    try:
        ws = ss.worksheet(customers_sheet_name())
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"ไม่พบแท็บ「{customers_sheet_name()}」") from exc
    values = ws.get_all_values()
    if not values:
        return []
    header = [(c or "").strip() for c in values[0]]
    out: list[dict] = []
    for row in values[1:]:
        item = _sheet_row_to_case(header, row)
        if item:
            out.append(item)
    return out


# ── Current tenants (Hubลูกค้าปัจจุบัน) ──────────────────────────────────────

def _tenant_headers() -> list[str]:
    from src.hub.tenant_store import SHEET_HEADERS

    return ["id", *SHEET_HEADERS]


_TENANT_STATUS_FROM_LABEL = {
    "กำลังเช่า": "active",
    "ใกล้หมดสัญญา": "ending_soon",
    "กำลังต่อสัญญา": "renewing",
    "ย้ายออกแล้ว": "moved_out",
    "active": "active",
    "ending_soon": "ending_soon",
    "renewing": "renewing",
    "moved_out": "moved_out",
}


def push_tenants_to_sheet(items: list[dict]) -> dict:
    from src.hub.tenant_store import tenant_to_sheet_row

    sheet_id = _hub_state_spreadsheet_id()
    if not sheet_id:
        raise ValueError("ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับ Hubลูกค้าปัจจุบัน")
    headers = _tenant_headers()
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    ws, created = _open_or_create(ss, tenants_sheet_name(), cols=len(headers))
    rows = [headers]
    for it in items or []:
        rows.append([str(it.get("id") or "").strip(), *tenant_to_sheet_row(it)])
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    return {
        "ok": True,
        "pushed": True,
        "created_tab": created,
        "count": len(rows) - 1,
        "sheet_title": ws.title,
        "spreadsheet_id": sheet_id,
    }


def _sheet_row_to_tenant(header: list[str], row: list[str]) -> dict | None:
    hmap = {h: i for i, h in enumerate(header)}

    def g(*names: str) -> str:
        for n in names:
            if n in hmap:
                return _cell(row, hmap[n])
        return ""

    tid = g("id")
    name = g("ชื่อผู้เช่า", "name")
    code = g("รหัสผู้เช่า", "tenant_code")
    if not tid and not name and not code and not g("รหัสทรัพย์"):
        return None

    status_raw = g("สถานะ")
    status = _TENANT_STATUS_FROM_LABEL.get(status_raw, status_raw or "active")

    def as_int(s: str) -> int:
        try:
            return int(str(s).replace(",", "").replace(" ", "")) if s else 0
        except ValueError:
            return 0

    return {
        "id": tid or "",
        "tenant_code": code,
        "name": name,
        "phone": g("เบอร์"),
        "line_id": g("LINE ID"),
        "property_code": g("รหัสทรัพย์"),
        "project_name": g("ชื่อโครงการ/ทรัพย์", "โครงการ"),
        "property_name": g("ชื่อโครงการ/ทรัพย์", "โครงการ"),
        "contract_start": g("วันเริ่มสัญญา"),
        "contract_end": g("วันสิ้นสุดสัญญา"),
        "rent_day": as_int(g("วันชำระค่าเช่า (ของเดือน)", "วันชำระค่าเช่า")),
        "rent_remind_day": as_int(g("วันแจ้งเตือนค่าเช่า")),
        "contract_warn_days": as_int(g("เตือนก่อนหมดสัญญา (วัน)")) or 30,
        "rent_amount": as_int(g("ค่าเช่า")),
        "deposit_amount": as_int(g("เงินมัดจำ")),
        "contract_link": g("ลิงก์สัญญา"),
        "status": status,
        "next_followup_at": g("วันฟอโล่วถัดไป"),
        "notes": g("หมายเหตุ"),
        "owner": g("ผู้รับผิดชอบ"),
    }


def pull_tenants_from_sheet() -> list[dict]:
    sheet_id = _hub_state_spreadsheet_id()
    if not sheet_id:
        raise ValueError("ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับ Hubลูกค้าปัจจุบัน")
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    try:
        ws = ss.worksheet(tenants_sheet_name())
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"ไม่พบแท็บ「{tenants_sheet_name()}」") from exc
    values = ws.get_all_values()
    if not values:
        return []
    header = [(c or "").strip() for c in values[0]]
    out: list[dict] = []
    for row in values[1:]:
        item = _sheet_row_to_tenant(header, row)
        if item:
            out.append(item)
    return out


# ── Location masters (Hubทำเล / HubBTS) ───────────────────────────────────────

LOCATION_MASTER_HEADERS = ["id", "label", "aliases", "created_at", "updated_at"]


def _push_location_master(sheet_title: str, items: list[dict], *, kind_label: str) -> dict:
    sheet_id = _hub_state_spreadsheet_id()
    if not sheet_id:
        raise ValueError(f"ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับ {kind_label}")
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    ws, created = _open_or_create(ss, sheet_title, cols=len(LOCATION_MASTER_HEADERS))
    rows = [LOCATION_MASTER_HEADERS]
    for it in items or []:
        aliases = it.get("aliases") or []
        if isinstance(aliases, list):
            aliases_s = ", ".join(str(a).strip() for a in aliases if str(a).strip())
        else:
            aliases_s = str(aliases or "").strip()
        rows.append(
            [
                str(it.get("id") or "").strip(),
                str(it.get("label") or "").strip(),
                aliases_s,
                str(it.get("created_at") or "").strip(),
                str(it.get("updated_at") or "").strip(),
            ]
        )
    ws.clear()
    ws.update(rows, value_input_option="USER_ENTERED")
    return {
        "ok": True,
        "pushed": True,
        "created_tab": created,
        "count": len(rows) - 1,
        "sheet_title": ws.title,
        "spreadsheet_id": sheet_id,
    }


def _pull_location_master(sheet_title: str, *, kind_label: str) -> list[dict]:
    sheet_id = _hub_state_spreadsheet_id()
    if not sheet_id:
        raise ValueError(f"ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับ {kind_label}")
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    try:
        ws = ss.worksheet(sheet_title)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"ไม่พบแท็บ「{sheet_title}」") from exc
    values = ws.get_all_values()
    if not values:
        return []
    header = [(c or "").strip().lower() for c in values[0]]
    start = 1
    if "label" not in header and "ชื่อ" not in header and "id" not in header:
        # headerless: treat col0=label or col0=id,col1=label
        start = 0
        header = LOCATION_MASTER_HEADERS

    def col(*names: str) -> int | None:
        for n in names:
            if n in header:
                return header.index(n)
        return None

    i_id = col("id")
    i_label = col("label", "ชื่อ", "name", "ทำเล", "สถานี", "bts", "mrt")
    i_aliases = col("aliases", "ชื่ออื่น")
    i_created = col("created_at", "created")
    i_updated = col("updated_at", "updated")
    out: list[dict] = []
    seen: set[str] = set()
    for row in values[start:]:
        if not any((c or "").strip() for c in row):
            continue
        label = (row[i_label] if i_label is not None and i_label < len(row) else "").strip()
        if not label and i_id is None and row:
            label = (row[0] or "").strip()
        if not label:
            continue
        key = label.lower().replace(" ", "")
        if key in seen:
            continue
        seen.add(key)
        aliases_raw = (
            row[i_aliases] if i_aliases is not None and i_aliases < len(row) else ""
        ).strip()
        aliases = [a.strip() for a in aliases_raw.replace("，", ",").split(",") if a.strip()]
        out.append(
            {
                "id": (row[i_id] if i_id is not None and i_id < len(row) else "").strip(),
                "label": label,
                "aliases": aliases,
                "created_at": (
                    row[i_created] if i_created is not None and i_created < len(row) else ""
                ).strip(),
                "updated_at": (
                    row[i_updated] if i_updated is not None and i_updated < len(row) else ""
                ).strip(),
            }
        )
    return out


def push_zones_to_sheet(items: list[dict]) -> dict:
    return _push_location_master(zones_sheet_name(), items, kind_label="Hubทำเล")


def pull_zones_from_sheet() -> list[dict]:
    return _pull_location_master(zones_sheet_name(), kind_label="Hubทำเล")


def push_transits_to_sheet(items: list[dict]) -> dict:
    return _push_location_master(transits_sheet_name(), items, kind_label="HubBTS")


def pull_transits_from_sheet() -> list[dict]:
    return _pull_location_master(transits_sheet_name(), kind_label="HubBTS")


# ── Project master (Hubโครงการ) ───────────────────────────────────────────────

PROJECT_MASTER_HEADERS = [
    "id",
    "canonical_name",
    "aliases",
    "ทำเล",
    "รถไฟฟ้า",
    "สถานที่ใกล้เคียง",
    "location_source",
    "location_status",
    "propertyhub_url",
    "living_project_url",
    "listing_count",
    "bucket_key",
]


def _join_list(values) -> str:
    if isinstance(values, str):
        return values.strip()
    if not values:
        return ""
    return ", ".join(str(v).strip() for v in values if str(v).strip())


def push_projects_to_sheet(items: list[dict] | None = None) -> dict:
    """Replace「Hubโครงการ」with current project master rows."""
    from src.hub.project_store import (
        load_projects,
        project_transit_display,
        project_zone_display,
    )

    sheet_id = _hub_state_spreadsheet_id()
    if not sheet_id:
        raise ValueError("ยังไม่ได้ตั้ง SOURCE_GOOGLE_SHEETS_ID สำหรับ Hubโครงการ")
    projects = items if items is not None else load_projects()
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    ws, created = _open_or_create(
        ss, projects_sheet_name(), cols=len(PROJECT_MASTER_HEADERS)
    )
    rows = [PROJECT_MASTER_HEADERS]
    for proj in projects or []:
        aliases = proj.get("aliases") or []
        if isinstance(aliases, list):
            aliases_s = " | ".join(str(a).strip() for a in aliases if str(a).strip())
        else:
            aliases_s = str(aliases or "").strip()
        rows.append(
            [
                str(proj.get("id") or "").strip(),
                str(proj.get("canonical_name") or "").strip(),
                aliases_s,
                _join_list(project_zone_display(proj)),
                _join_list(project_transit_display(proj)[:3]),
                _join_list(proj.get("nearby_places") or []),
                str(proj.get("location_source") or "").strip(),
                str(proj.get("location_status") or "").strip(),
                str(proj.get("propertyhub_url") or "").strip(),
                str(proj.get("living_project_url") or "").strip(),
                str(proj.get("listing_count") or 0),
                str(proj.get("bucket_key") or "").strip(),
            ]
        )
    need_rows = max(len(rows) + 5, 100)
    need_cols = max(len(PROJECT_MASTER_HEADERS), 12)
    try:
        if ws.row_count < need_rows or ws.col_count < need_cols:
            ws.resize(rows=need_rows, cols=need_cols)
    except Exception:  # noqa: BLE001
        pass
    # Batch clear + update (gspread handles large sheets; chunk if needed)
    ws.clear()
    # Sheets API soft limit — write in chunks of 400 rows after header
    ws.update([rows[0]], value_input_option="USER_ENTERED")
    body = rows[1:]
    chunk = 400
    start_row = 2
    for i in range(0, len(body), chunk):
        part = body[i : i + chunk]
        end_row = start_row + len(part) - 1
        # Ensure grid can hold this chunk
        if ws.row_count < end_row:
            try:
                ws.resize(rows=end_row + 10, cols=need_cols)
            except Exception:  # noqa: BLE001
                pass
        rng = f"A{start_row}:L{end_row}"
        ws.update(part, range_name=rng, value_input_option="USER_ENTERED")
        start_row = end_row + 1
    return {
        "ok": True,
        "pushed": True,
        "created_tab": created,
        "count": len(rows) - 1,
        "sheet_title": ws.title,
        "spreadsheet_id": sheet_id,
    }
