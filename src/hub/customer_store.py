"""Customer follow-up cases — Hub CRM for rent/sale leads.

One row = one customer case. Room codes live in offered/viewing lists.
"""

from __future__ import annotations

import csv
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CASES_PATH = BASE_DIR / "data" / "customer_cases.json"
EXPORT_CSV = BASE_DIR / "data" / "customer_followup_export.csv"

STATUSES = [
    "new",
    "waiting_info",
    "offered",
    "viewing",
    "deciding",
    "reserved",
    "closed_won",
    "closed_lost",
    "paused",
]

STATUS_LABELS = {
    "new": "ใหม่",
    "waiting_info": "รอข้อมูล",
    "offered": "เสนอแล้ว",
    "viewing": "นัดดู",
    "deciding": "รอตัดสินใจ",
    "reserved": "จอง/มัดจำ",
    "closed_won": "ปิดได้",
    "closed_lost": "หลุด",
    "paused": "พัก",
}

SHEET_HEADERS = [
    "รหัสเคส",
    "ช่องทาง",
    "ประเภทลูกค้า",
    "ชื่อในแชท",
    "เบอร์",
    "LINE ID",
    "ผู้รับผิดชอบ",
    "ประเภทดีล",
    "รหัสห้องที่ทักมา",
    "วันติดต่อครั้งแรก",
    "วันคุยล่าสุด",
    "ทักซ้ำในอีกกี่วัน",
    "วันฟอโล่วถัดไป",
    "สถานะ",
    "เหตุผลหลุด",
    "ประเภททรัพย์",
    "ทำเลที่ต้องการ",
    "BTS/MRT",
    "งบต่ำ",
    "งบสูง",
    "ห้องนอน",
    "เข้าอยู่ได้เมื่อ",
    "สัตว์เลี้ยง/ที่จอด/อื่น",
    "โจทย์สั้นๆ",
    "รหัสที่เสนอแล้ว",
    "วันเสนอล่าสุด",
    "ผลตอบจากที่เสนอ",
    "รหัสที่นัดดู",
    "วันนัดชม",
    "ผลหลังชม",
    "รหัสจอง/มัดจำ",
    "ชื่อโคเอเจนต์",
    "ลำดับความสำคัญ",
    "แท็ก",
    "โน้ตฟอโล่วล่าสุด",
    "ลิงก์แชท",
]

CUSTOMER_KINDS = {
    "direct": "ลูกค้าตรง",
    "co_agent": "โคเอเจนต์",
}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return date.today().isoformat()


def _parse_codes(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = raw
    else:
        parts = re.split(r"[,，|/\s]+", str(raw))
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        c = str(p or "").strip().upper()
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _parse_list(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        parts = raw
    else:
        parts = re.split(r"[,，|/]+", str(raw))
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        s = str(p or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _add_days(iso_day: str, days: int) -> str:
    try:
        d = date.fromisoformat((iso_day or "")[:10])
    except ValueError:
        d = date.today()
    return (d + timedelta(days=max(0, int(days or 0)))).isoformat()


def _next_case_code(items: list[dict]) -> str:
    prefix = f"FU-{date.today().strftime('%y%m%d')}-"
    n = 0
    for it in items:
        code = str(it.get("case_code") or "")
        if code.startswith(prefix):
            try:
                n = max(n, int(code[len(prefix) :]))
            except ValueError:
                pass
    return f"{prefix}{n + 1:02d}"


def _normalize(item: dict) -> dict:
    item = dict(item)
    item.setdefault("id", "")
    item.setdefault("case_code", "")
    item.setdefault("channel", "LINE OA")
    item.setdefault("chat_name", "")
    item.setdefault("phone", "")
    item.setdefault("line_id", "")
    item.setdefault("owner", "")
    kind = (item.get("customer_kind") or "direct").strip().lower()
    if kind in {"coagent", "co-agent", "coa", "โคเอเจนต์", "โคเอเจ้นท์"}:
        kind = "co_agent"
    if kind not in {"direct", "co_agent"}:
        kind = "direct"
    item["customer_kind"] = kind
    item["inquiry_codes"] = _parse_codes(item.get("inquiry_codes"))
    deal = (item.get("deal_type") or "rent").strip().lower()
    if deal not in {"rent", "sale", "both"}:
        deal = "rent"
    item["deal_type"] = deal
    item.setdefault("first_contact_at", "")
    item.setdefault("last_contact_at", "")
    try:
        item["followup_in_days"] = int(item.get("followup_in_days") or 3)
    except (TypeError, ValueError):
        item["followup_in_days"] = 3
    item.setdefault("next_followup_at", "")
    st = (item.get("status") or "new").strip()
    if st not in STATUSES:
        st = "new"
    item["status"] = st
    item.setdefault("lost_reason", "")
    item["property_types"] = _parse_list(item.get("property_types"))
    item.setdefault("locations", "")
    item["transits"] = _parse_list(item.get("transits"))
    for key in ("budget_min", "budget_max"):
        try:
            v = item.get(key)
            item[key] = int(str(v).replace(",", "").replace(" ", "")) if v not in (None, "") else 0
        except (TypeError, ValueError):
            item[key] = 0
    item["bedrooms"] = _parse_list(item.get("bedrooms"))
    item.setdefault("move_in", "")
    item.setdefault("constraints", "")
    item.setdefault("brief", "")
    item["offered_codes"] = _parse_codes(item.get("offered_codes"))
    item.setdefault("offered_at", "")
    item.setdefault("offer_feedback", "")
    item["viewing_codes"] = _parse_codes(item.get("viewing_codes"))
    item.setdefault("viewing_at", "")
    item.setdefault("viewing_feedback", "")
    item["reserved_codes"] = _parse_codes(item.get("reserved_codes"))
    item.setdefault("chat_link", "")
    item.setdefault("co_agent", "")
    pr = (item.get("priority") or "normal").strip().lower()
    if pr not in {"high", "normal", "low"}:
        pr = "normal"
    item["priority"] = pr
    item["tags"] = _parse_list(item.get("tags"))
    item.setdefault("last_note", "")
    item["recommended_codes"] = _parse_codes(item.get("recommended_codes"))
    item.setdefault("created_at", "")
    item.setdefault("updated_at", "")

    # Auto next follow-up from last contact + days when blank
    if not item["next_followup_at"] and item["last_contact_at"]:
        item["next_followup_at"] = _add_days(item["last_contact_at"], item["followup_in_days"])
    return item


def load_cases() -> list[dict]:
    if not CASES_PATH.exists():
        return []
    try:
        data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        items = data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [_normalize(x) for x in items]


def save_cases(items: list[dict]) -> None:
    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = [_normalize(dict(x)) for x in items]
    CASES_PATH.write_text(
        json.dumps(
            {"items": normalized, "updated_at": _now()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def case_stats(items: list[dict] | None = None) -> dict:
    items = items if items is not None else load_cases()
    today = _today()
    open_statuses = {
        "new",
        "waiting_info",
        "offered",
        "viewing",
        "deciding",
        "reserved",
        "paused",
    }
    open_n = sum(1 for x in items if x.get("status") in open_statuses)
    due = sum(
        1
        for x in items
        if x.get("status") in open_statuses
        and (x.get("next_followup_at") or "")[:10]
        and (x.get("next_followup_at") or "")[:10] <= today
    )
    return {"total": len(items), "open": open_n, "due": due}


def list_cases(*, include_closed: bool = False) -> list[dict]:
    items = load_cases()
    if not include_closed:
        items = [x for x in items if x.get("status") not in {"closed_won", "closed_lost"}]
    today = _today()

    def sort_key(x: dict):
        st = x.get("status") or ""
        closed = 1 if st in {"closed_won", "closed_lost"} else 0
        nxt = (x.get("next_followup_at") or "9999-99-99")[:10]
        due = 0 if (not closed and nxt <= today) else 1
        pri = {"high": 0, "normal": 1, "low": 2}.get(x.get("priority") or "normal", 1)
        return (closed, due, nxt, pri, x.get("case_code") or "")

    return sorted(items, key=sort_key)


def get_case(case_id: str) -> dict | None:
    cid = (case_id or "").strip()
    for it in load_cases():
        if it.get("id") == cid:
            return it
    return None


def add_case(**fields) -> dict:
    items = load_cases()
    now = _now()
    today = _today()
    item = _normalize(
        {
            **fields,
            "id": "fu_" + uuid.uuid4().hex[:10],
            "case_code": fields.get("case_code") or _next_case_code(items),
            "first_contact_at": fields.get("first_contact_at") or today,
            "last_contact_at": fields.get("last_contact_at") or today,
            "created_at": now,
            "updated_at": now,
        }
    )
    if not item.get("next_followup_at"):
        item["next_followup_at"] = _add_days(
            item["last_contact_at"], item["followup_in_days"]
        )
    items.append(item)
    save_cases(items)
    return item


def update_case(case_id: str, **fields) -> dict:
    items = load_cases()
    cid = (case_id or "").strip()
    for i, it in enumerate(items):
        if it.get("id") != cid:
            continue
        merged = dict(it)
        for k, v in fields.items():
            if v is None:
                continue
            merged[k] = v
        # Recalc next follow-up when days or last contact change
        if "followup_in_days" in fields or "last_contact_at" in fields:
            if fields.get("next_followup_at") is None:
                merged["next_followup_at"] = _add_days(
                    merged.get("last_contact_at") or _today(),
                    int(merged.get("followup_in_days") or 3),
                )
        merged["updated_at"] = _now()
        items[i] = _normalize(merged)
        save_cases(items)
        return items[i]
    raise ValueError("ไม่พบเคส")


def delete_case(case_id: str) -> None:
    cid = (case_id or "").strip()
    items = load_cases()
    new_items = [x for x in items if x.get("id") != cid]
    if len(new_items) == len(items):
        raise ValueError("ไม่พบเคส")
    save_cases(new_items)


def mark_contacted(case_id: str, *, note: str = "", followup_in_days: int | None = None) -> dict:
    """Bump last_contact + schedule next follow-up."""
    it = get_case(case_id)
    if not it:
        raise ValueError("ไม่พบเคส")
    days = (
        int(followup_in_days)
        if followup_in_days is not None
        else int(it.get("followup_in_days") or 3)
    )
    fields: dict = {
        "last_contact_at": _today(),
        "followup_in_days": days,
        "next_followup_at": _add_days(_today(), days),
    }
    if note:
        fields["last_note"] = note
    return update_case(case_id, **fields)


def append_codes(case_id: str, *, offered=None, viewing=None, reserved=None) -> dict:
    it = get_case(case_id)
    if not it:
        raise ValueError("ไม่พบเคส")
    fields: dict = {}
    if offered is not None:
        codes = list(
            dict.fromkeys((it.get("offered_codes") or []) + _parse_codes(offered))
        )
        fields["offered_codes"] = codes
        fields["offered_at"] = _today()
        if it.get("status") in {"new", "waiting_info"}:
            fields["status"] = "offered"
    if viewing is not None:
        fields["viewing_codes"] = list(
            dict.fromkeys((it.get("viewing_codes") or []) + _parse_codes(viewing))
        )
        fields["viewing_at"] = _today()
        if it.get("status") in {"new", "waiting_info", "offered"}:
            fields["status"] = "viewing"
    if reserved is not None:
        fields["reserved_codes"] = list(
            dict.fromkeys((it.get("reserved_codes") or []) + _parse_codes(reserved))
        )
        fields["status"] = "reserved"
    return update_case(case_id, **fields)


def case_to_sheet_row(it: dict) -> list[str]:
    it = _normalize(it)
    return [
        it.get("case_code") or "",
        it.get("channel") or "",
        CUSTOMER_KINDS.get(it.get("customer_kind") or "", it.get("customer_kind") or ""),
        it.get("chat_name") or "",
        it.get("phone") or "",
        it.get("line_id") or "",
        it.get("owner") or "",
        {"rent": "เช่า", "sale": "ซื้อ", "both": "เช่า+ซื้อ"}.get(
            it.get("deal_type") or "", it.get("deal_type") or ""
        ),
        ", ".join(it.get("inquiry_codes") or []),
        it.get("first_contact_at") or "",
        it.get("last_contact_at") or "",
        str(it.get("followup_in_days") or ""),
        it.get("next_followup_at") or "",
        STATUS_LABELS.get(it.get("status") or "", it.get("status") or ""),
        it.get("lost_reason") or "",
        ", ".join(it.get("property_types") or []),
        it.get("locations") or "",
        ", ".join(it.get("transits") or []),
        str(it.get("budget_min") or "") if it.get("budget_min") else "",
        str(it.get("budget_max") or "") if it.get("budget_max") else "",
        ", ".join(it.get("bedrooms") or []),
        it.get("move_in") or "",
        it.get("constraints") or "",
        it.get("brief") or "",
        ", ".join(it.get("offered_codes") or []),
        it.get("offered_at") or "",
        it.get("offer_feedback") or "",
        ", ".join(it.get("viewing_codes") or []),
        it.get("viewing_at") or "",
        it.get("viewing_feedback") or "",
        ", ".join(it.get("reserved_codes") or []),
        it.get("co_agent") or "",
        {"high": "สูง", "normal": "กลาง", "low": "ต่ำ"}.get(
            it.get("priority") or "", it.get("priority") or ""
        ),
        ", ".join(it.get("tags") or []),
        it.get("last_note") or "",
        it.get("chat_link") or "",
    ]


def write_followup_export_csv(items: list[dict] | None = None) -> Path:
    items = items if items is not None else load_cases()
    EXPORT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with EXPORT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(SHEET_HEADERS)
        for it in items:
            w.writerow(case_to_sheet_row(it))
    return EXPORT_CSV
