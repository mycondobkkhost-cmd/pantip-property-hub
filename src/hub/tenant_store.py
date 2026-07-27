"""Current tenants / active leases — Hub CRM for renting customers.

Store: data/current_tenants.json
Sheet tab: Hubลูกค้าปัจจุบัน (via hub_state_sheet)

One row = one active (or recently ended) lease.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TENANTS_PATH = BASE_DIR / "data" / "current_tenants.json"

STATUSES = [
    "active",
    "ending_soon",
    "renewing",
    "moved_out",
]

STATUS_LABELS = {
    "active": "กำลังเช่า",
    "ending_soon": "ใกล้หมดสัญญา",
    "renewing": "กำลังต่อสัญญา",
    "moved_out": "ย้ายออกแล้ว",
}

SHEET_HEADERS = [
    "รหัสผู้เช่า",
    "ชื่อผู้เช่า",
    "เบอร์",
    "LINE ID",
    "รหัสทรัพย์",
    "ชื่อโครงการ/ทรัพย์",
    "วันเริ่มสัญญา",
    "วันสิ้นสุดสัญญา",
    "วันชำระค่าเช่า (ของเดือน)",
    "วันแจ้งเตือนค่าเช่า",
    "เตือนก่อนหมดสัญญา (วัน)",
    "ค่าเช่า",
    "เงินมัดจำ",
    "ลิงก์สัญญา",
    "สถานะ",
    "วันฟอโล่วถัดไป",
    "หมายเหตุ",
    "ผู้รับผิดชอบ",
]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return date.today().isoformat()


def _parse_day(raw) -> int:
    """Day-of-month 1–31; 0 = unset."""
    try:
        d = int(str(raw or "").strip() or 0)
    except (TypeError, ValueError):
        return 0
    if d < 0:
        return 0
    if d > 31:
        return 31
    return d


def _parse_int(raw, default: int = 0) -> int:
    try:
        return int(str(raw).replace(",", "").replace(" ", "")) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _normalize_code(code: str) -> str:
    return str(code or "").strip().upper().replace(" ", "")


def _add_days(iso_day: str, days: int) -> str:
    try:
        d = date.fromisoformat((iso_day or "")[:10])
    except ValueError:
        d = date.today()
    return (d + timedelta(days=int(days or 0))).isoformat()


def _next_tenant_code(items: list[dict]) -> str:
    prefix = f"TN-{date.today().strftime('%y%m%d')}-"
    n = 0
    for it in items:
        code = str(it.get("tenant_code") or "")
        if code.startswith(prefix):
            try:
                n = max(n, int(code[len(prefix) :]))
            except ValueError:
                pass
    return f"{prefix}{n + 1:02d}"


def _auto_status(item: dict) -> str:
    """Derive ending_soon from contract_end when still active/renewing."""
    st = (item.get("status") or "active").strip()
    if st in {"moved_out"}:
        return st
    if st not in STATUSES:
        st = "active"
    end = (item.get("contract_end") or "")[:10]
    warn_days = _parse_int(item.get("contract_warn_days"), 30)
    if end and re.match(r"^\d{4}-\d{2}-\d{2}$", end):
        try:
            end_d = date.fromisoformat(end)
        except ValueError:
            return st
        today = date.today()
        if end_d < today and st != "renewing":
            return "ending_soon"
        if 0 <= (end_d - today).days <= max(1, warn_days) and st == "active":
            return "ending_soon"
    return st


def _normalize(item: dict) -> dict:
    item = dict(item)
    item.setdefault("id", "")
    item.setdefault("tenant_code", "")
    item.setdefault("name", "")
    item.setdefault("phone", "")
    item.setdefault("line_id", "")
    item.setdefault("property_code", "")
    item["property_code"] = _normalize_code(item.get("property_code") or "")
    item.setdefault("property_name", "")
    item.setdefault("project_name", "")
    # Prefer project_name; fall back to property_name label
    if not item.get("project_name") and item.get("property_name"):
        item["project_name"] = item["property_name"]
    item.setdefault("contract_start", "")
    item.setdefault("contract_end", "")
    item["rent_day"] = _parse_day(item.get("rent_day"))
    item["rent_remind_day"] = _parse_day(item.get("rent_remind_day") or item.get("rent_day"))
    item["contract_warn_days"] = max(0, _parse_int(item.get("contract_warn_days"), 30))
    item["rent_amount"] = _parse_int(item.get("rent_amount"), 0)
    item["deposit_amount"] = _parse_int(item.get("deposit_amount"), 0)
    item.setdefault("contract_link", "")
    st = (item.get("status") or "active").strip()
    # Accept Thai labels
    if st not in STATUSES:
        for code, label in STATUS_LABELS.items():
            if st == label:
                st = code
                break
    if st not in STATUSES:
        st = "active"
    item["status"] = st
    item["status"] = _auto_status(item)
    item.setdefault("next_followup_at", "")
    item.setdefault("notes", "")
    item.setdefault("owner", "")
    item.setdefault("created_at", "")
    item.setdefault("updated_at", "")
    return item


def load_tenants() -> list[dict]:
    if not TENANTS_PATH.exists():
        return []
    try:
        data = json.loads(TENANTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        items = data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [_normalize(x) for x in items]


def _sheet_sync_enabled() -> bool:
    import os

    flag = (os.environ.get("HUB_TENANTS_SHEET_SYNC") or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def save_tenants(items: list[dict], *, sync_sheet: bool = True) -> None:
    TENANTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = [_normalize(dict(x)) for x in items]
    TENANTS_PATH.write_text(
        json.dumps(
            {"items": normalized, "updated_at": _now()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if sync_sheet and _sheet_sync_enabled():
        try:
            from src.hub.hub_state_sheet import push_tenants_to_sheet

            push_tenants_to_sheet(normalized)
        except Exception as exc:  # noqa: BLE001
            print(f"[hub] tenants sheet push failed: {exc}")


def replace_tenants_from_sheet() -> dict:
    """Pull Hubลูกค้าปัจจุบัน from Google Sheet into local JSON."""
    from src.hub.hub_state_sheet import pull_tenants_from_sheet

    raw = pull_tenants_from_sheet()
    items: list[dict] = []
    for entry in raw:
        it = _normalize(dict(entry))
        if not it.get("id"):
            it["id"] = "tn_" + uuid.uuid4().hex[:10]
        if not it.get("tenant_code"):
            it["tenant_code"] = _next_tenant_code(items)
        items.append(it)
    save_tenants(items, sync_sheet=False)
    return {"ok": True, "count": len(items), "source": "sheet"}


def merge_tenants_from_sheet() -> dict:
    """Union sheet + local tenants by id/tenant_code. Never wipe local."""
    from src.hub.hub_state_sheet import pull_tenants_from_sheet

    local = load_tenants()
    try:
        raw = pull_tenants_from_sheet()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": True,
            "count": len(local),
            "merged": 0,
            "source": "local",
            "warning": str(exc),
        }

    by_key: dict[str, dict] = {}
    for entry in local:
        it = _normalize(dict(entry))
        key = (it.get("id") or "").strip() or (it.get("tenant_code") or "").strip()
        if key:
            by_key[key] = it

    merged = 0
    for entry in raw or []:
        it = _normalize(dict(entry))
        if not it.get("id"):
            it["id"] = "tn_" + uuid.uuid4().hex[:10]
        key = (it.get("id") or "").strip() or (it.get("tenant_code") or "").strip()
        if not key:
            continue
        prev = by_key.get(key)
        if not prev:
            if not it.get("tenant_code"):
                it["tenant_code"] = _next_tenant_code(list(by_key.values()))
            by_key[key] = it
            merged += 1
            continue
        if (it.get("updated_at") or "") > (prev.get("updated_at") or ""):
            by_key[key] = {**prev, **it}
            merged += 1

    out = list(by_key.values())
    save_tenants(out, sync_sheet=False)
    return {
        "ok": True,
        "count": len(out),
        "merged": merged,
        "local_before": len(local),
        "sheet": len(raw or []),
        "source": "merge",
    }


def _rent_due_soon(item: dict, *, within_days: int = 5) -> bool:
    """True if rent_remind_day falls within the next within_days (incl. today)."""
    day = item.get("rent_remind_day") or item.get("rent_day") or 0
    if not day or item.get("status") == "moved_out":
        return False
    today = date.today()
    for offset in range(0, within_days + 1):
        d = today + timedelta(days=offset)
        if d.month == 12:
            last = 31
        else:
            last = (date(d.year, d.month + 1, 1) - timedelta(days=1)).day
        target = min(int(day), last)
        if d.day == target:
            return True
    return False


def _contract_ending_soon(item: dict) -> bool:
    if item.get("status") == "moved_out":
        return False
    end = (item.get("contract_end") or "")[:10]
    if not end:
        return False
    try:
        end_d = date.fromisoformat(end)
    except ValueError:
        return False
    warn = max(1, _parse_int(item.get("contract_warn_days"), 30))
    days_left = (end_d - date.today()).days
    return days_left <= warn


def tenant_stats(items: list[dict] | None = None) -> dict:
    items = items if items is not None else load_tenants()
    active = [x for x in items if x.get("status") != "moved_out"]
    rent_due = sum(1 for x in active if _rent_due_soon(x))
    ending = sum(1 for x in active if _contract_ending_soon(x) or x.get("status") == "ending_soon")
    return {
        "total": len(items),
        "active": len(active),
        "rent_due_soon": rent_due,
        "ending_soon": ending,
        "alerts": rent_due + ending,
    }


def list_tenants(*, include_moved_out: bool = False) -> list[dict]:
    items = load_tenants()
    if not include_moved_out:
        items = [x for x in items if x.get("status") != "moved_out"]
    today = _today()

    def sort_key(x: dict):
        moved = 1 if x.get("status") == "moved_out" else 0
        end = (x.get("contract_end") or "9999-99-99")[:10]
        rent_alert = 0 if _rent_due_soon(x) else 1
        end_alert = 0 if _contract_ending_soon(x) else 1
        nxt = (x.get("next_followup_at") or "9999-99-99")[:10]
        due = 0 if nxt <= today else 1
        return (moved, rent_alert, end_alert, due, end, x.get("tenant_code") or "")

    return sorted(items, key=sort_key)


def get_tenant(tenant_id: str) -> dict | None:
    tid = (tenant_id or "").strip()
    for it in load_tenants():
        if it.get("id") == tid:
            return it
    return None


def add_tenant(**fields) -> dict:
    items = load_tenants()
    now = _now()
    item = _normalize(
        {
            **fields,
            "id": "tn_" + uuid.uuid4().hex[:10],
            "tenant_code": fields.get("tenant_code") or _next_tenant_code(items),
            "created_at": now,
            "updated_at": now,
        }
    )
    if not item.get("name"):
        raise ValueError("ต้องมีชื่อผู้เช่า")
    items.append(item)
    save_tenants(items)
    return item


def update_tenant(tenant_id: str, **fields) -> dict:
    items = load_tenants()
    tid = (tenant_id or "").strip()
    for i, it in enumerate(items):
        if it.get("id") != tid:
            continue
        merged = dict(it)
        for k, v in fields.items():
            if v is None:
                continue
            merged[k] = v
        merged["updated_at"] = _now()
        items[i] = _normalize(merged)
        save_tenants(items)
        return items[i]
    raise ValueError("ไม่พบผู้เช่า")


def delete_tenant(tenant_id: str) -> None:
    tid = (tenant_id or "").strip()
    items = load_tenants()
    new_items = [x for x in items if x.get("id") != tid]
    if len(new_items) == len(items):
        raise ValueError("ไม่พบผู้เช่า")
    save_tenants(new_items)


def tenant_alerts(items: list[dict] | None = None) -> list[dict]:
    """Upcoming rent / contract alerts for Hub UI banner."""
    items = items if items is not None else list_tenants(include_moved_out=False)
    alerts: list[dict] = []
    for it in items:
        if _rent_due_soon(it):
            alerts.append(
                {
                    "type": "rent",
                    "label": "ใกล้วันชำระค่าเช่า",
                    "tenant_id": it.get("id"),
                    "tenant_code": it.get("tenant_code"),
                    "name": it.get("name"),
                    "property_code": it.get("property_code"),
                    "detail": f"แจ้งเตือนวันที่ {it.get('rent_remind_day') or it.get('rent_day')} ของเดือน",
                }
            )
        if _contract_ending_soon(it):
            end = (it.get("contract_end") or "")[:10]
            alerts.append(
                {
                    "type": "contract",
                    "label": "ใกล้หมดสัญญา",
                    "tenant_id": it.get("id"),
                    "tenant_code": it.get("tenant_code"),
                    "name": it.get("name"),
                    "property_code": it.get("property_code"),
                    "detail": f"สิ้นสุด {end} — ฟอโล่วต่อสัญญา / หาห้องใหม่",
                }
            )
    return alerts


def tenant_to_sheet_row(it: dict) -> list[str]:
    it = _normalize(it)
    return [
        it.get("tenant_code") or "",
        it.get("name") or "",
        it.get("phone") or "",
        it.get("line_id") or "",
        it.get("property_code") or "",
        it.get("project_name") or it.get("property_name") or "",
        it.get("contract_start") or "",
        it.get("contract_end") or "",
        str(it.get("rent_day") or "") if it.get("rent_day") else "",
        str(it.get("rent_remind_day") or "") if it.get("rent_remind_day") else "",
        str(it.get("contract_warn_days") or "") if it.get("contract_warn_days") else "",
        str(it.get("rent_amount") or "") if it.get("rent_amount") else "",
        str(it.get("deposit_amount") or "") if it.get("deposit_amount") else "",
        it.get("contract_link") or "",
        STATUS_LABELS.get(it.get("status") or "", it.get("status") or ""),
        it.get("next_followup_at") or "",
        it.get("notes") or "",
        it.get("owner") or "",
    ]
