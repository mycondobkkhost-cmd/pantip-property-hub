"""Upcoming rental availability — Phase Z14 compact operational reminder.

Evidence types (semantically separate):
  TYPE A confirmed — owner_confirmed_available_from (explicit owner evidence only)
  TYPE B annual_recheck — last_listed_at + 1 year (ถึงรอบเช็ก; never writes confirmed date)

Legacy วันที่ว่าง is NEVER used.
Does not merge OLD_RECORD_RECHECK / LEASE_END_FOLLOWUP engines.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.hub.legacy_entry_date import (
    LEGACY_RECORD_ENTERED_AT_FIELD,
    parse_legacy_record_entered_at,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BANGKOK = ZoneInfo("Asia/Bangkok")

# Canonical annual base — properties.last_listed_at (sheet วันที่รับเข้า / data-entry date).
ANNUAL_RECHECK_BASE_FIELD = LEGACY_RECORD_ENTERED_AT_FIELD  # "last_listed_at"
CONFIRMED_FIELD = "owner_confirmed_available_from"
WINDOW_DAYS = 30

EVIDENCE_CONFIRMED = "confirmed"
EVIDENCE_ANNUAL = "annual_recheck"

LABEL_CONFIRMED = "ยืนยันวันว่างแล้ว"
LABEL_ANNUAL = "ถึงรอบเช็ก"


def _e2e_root() -> Path | None:
    raw = (os.environ.get("PANTIP_E2E_DATA_ROOT") or "").strip()
    return Path(raw) if raw else None


def state_path() -> Path:
    root = _e2e_root()
    if root:
        return root / "upcoming_followup_state.json"
    return BASE_DIR / "data" / "upcoming_followup_state.json"


def bangkok_today(today: date | None = None) -> date:
    if today is not None:
        return today
    return datetime.now(timezone.utc).astimezone(BANGKOK).date()


def parse_iso_or_dmy(raw: str | None) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None
    return parse_legacy_record_entered_at(s)


def add_one_year(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:
        # Feb 29 → Feb 28 next year
        return d + timedelta(days=365)


def is_rental_inventory(prop: dict[str, Any]) -> bool:
    """Rental-capable (rent price present). Sale-only excluded."""
    return bool(str(prop.get("rent_price") or "").strip())


def is_sale_only(prop: dict[str, Any]) -> bool:
    rent = bool(str(prop.get("rent_price") or "").strip())
    sale = bool(str(prop.get("sale_price") or "").strip())
    return sale and not rent


def days_until(target: date, *, today: date | None = None) -> int:
    return (target - bangkok_today(today)).days


def countdown_label(days: int) -> str:
    if days > 0:
        return f"{days} วัน"
    if days == 0:
        return "วันนี้"
    return f"เลยมา {abs(days)} วัน"


def format_compact_date(d: date) -> str:
    return f"{d.day}/{d.month}/{d.year % 100}"


def _load_state() -> dict[str, Any]:
    path = state_path()
    if not path.exists():
        return {"items": {}, "updated_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"items": {}, "updated_at": ""}
    if not isinstance(data, dict):
        return {"items": {}, "updated_at": ""}
    items = data.get("items")
    if not isinstance(items, dict):
        data["items"] = {}
    return data


def _save_state(data: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now(BANGKOK).strftime("%Y-%m-%d %H:%M:%S")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def is_suppressed(property_id: str, state: dict[str, Any] | None = None) -> bool:
    st = state or _load_state()
    item = (st.get("items") or {}).get(str(property_id or "").strip()) or {}
    return bool(item.get("suppressed"))


def suppress_property(
    property_id: str,
    *,
    reason: str = "ไม่ติดตามต่อ",
    by: str = "",
) -> dict[str, Any]:
    pid = str(property_id or "").strip()
    if not pid:
        raise ValueError("property_id required")
    st = _load_state()
    items = st.setdefault("items", {})
    items[pid] = {
        "suppressed": True,
        "reason": (reason or "ไม่ติดตามต่อ").strip()[:120],
        "suppressed_at": datetime.now(BANGKOK).strftime("%Y-%m-%d %H:%M:%S"),
        "suppressed_by": (by or "").strip()[:80],
        # Optional snooze target for recheck-later (NOT confirmed vacancy)
        "recheck_after": "",
    }
    _save_state(st)
    return items[pid]


def set_recheck_after(property_id: str, recheck_after: str, *, by: str = "") -> dict[str, Any]:
    """Snooze / recheck-later — does NOT write owner_confirmed_available_from."""
    pid = str(property_id or "").strip()
    if not pid:
        raise ValueError("property_id required")
    d = parse_iso_or_dmy(recheck_after)
    if not d:
        raise ValueError("วันที่ไม่ถูกต้อง")
    st = _load_state()
    items = st.setdefault("items", {})
    prev = dict(items.get(pid) or {})
    prev.update(
        {
            "suppressed": False,
            "recheck_after": d.isoformat(),
            "recheck_after_set_at": datetime.now(BANGKOK).strftime("%Y-%m-%d %H:%M:%S"),
            "recheck_after_by": (by or "").strip()[:80],
        }
    )
    items[pid] = prev
    _save_state(st)
    return prev


def clear_suppression(property_id: str) -> None:
    pid = str(property_id or "").strip()
    if not pid:
        return
    st = _load_state()
    items = st.setdefault("items", {})
    if pid in items:
        items[pid]["suppressed"] = False
        _save_state(st)


def _candidate_confirmed(prop: dict[str, Any], *, today: date) -> dict[str, Any] | None:
    raw = prop.get(CONFIRMED_FIELD) or prop.get("owner_confirmed_available_from")
    target = parse_iso_or_dmy(str(raw or ""))
    if not target:
        return None
    days = days_until(target, today=today)
    # Confirmed: upcoming within window OR any overdue until suppressed
    if days > WINDOW_DAYS:
        return None
    return {
        "evidence": EVIDENCE_CONFIRMED,
        "label": LABEL_CONFIRMED,
        "target_date": target.isoformat(),
        "target_display": format_compact_date(target),
        "days_until": days,
        "countdown": countdown_label(days),
        "bucket": "overdue" if days < 0 else "upcoming",
    }


def _candidate_annual(prop: dict[str, Any], *, today: date) -> dict[str, Any] | None:
    entered = parse_legacy_record_entered_at(str(prop.get(ANNUAL_RECHECK_BASE_FIELD) or ""))
    if not entered:
        return None
    target = add_one_year(entered)
    days = days_until(target, today=today)
    # ±30 day window around anniversary (avoids flooding all ancient rentals as overdue)
    if days > WINDOW_DAYS or days < -WINDOW_DAYS:
        return None
    return {
        "evidence": EVIDENCE_ANNUAL,
        "label": LABEL_ANNUAL,
        "target_date": target.isoformat(),
        "target_display": format_compact_date(target),
        "days_until": days,
        "countdown": countdown_label(days),
        "bucket": "overdue" if days < 0 else "upcoming",
        "base_date": entered.isoformat(),
        "base_field": ANNUAL_RECHECK_BASE_FIELD,
    }


def _row_from_prop(prop: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
    return {
        "property_id": str(prop.get("id") or ""),
        "code": str(prop.get("code") or ""),
        "project_name": str(prop.get("project_name") or ""),
        "rent_price": str(prop.get("rent_price") or ""),
        "notes": str(prop.get("notes") or "")[:120],
        **cand,
    }


def build_upcoming_items(
    properties: list[dict[str, Any]] | None = None,
    *,
    today: date | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive upcoming/overdue rental reminders. One row per property; confirmed wins."""
    from src.hub.project_store import load_properties

    today = bangkok_today(today)
    props = properties if properties is not None else load_properties()
    st = state if state is not None else _load_state()
    upcoming: list[dict[str, Any]] = []
    overdue: list[dict[str, Any]] = []

    for prop in props:
        if not is_rental_inventory(prop):
            continue
        pid = str(prop.get("id") or "").strip()
        if not pid:
            continue
        if is_suppressed(pid, st):
            continue
        # Recheck-later snooze: hide until recheck_after
        item_st = (st.get("items") or {}).get(pid) or {}
        ra = parse_iso_or_dmy(str(item_st.get("recheck_after") or ""))
        if ra and ra > today:
            continue

        confirmed = _candidate_confirmed(prop, today=today)
        annual = _candidate_annual(prop, today=today)
        # Priority: confirmed wins; never duplicate
        chosen = confirmed or annual
        if not chosen:
            continue
        row = _row_from_prop(prop, chosen)
        if row["bucket"] == "overdue":
            overdue.append(row)
        else:
            upcoming.append(row)

    # upcoming: soonest first; overdue: most overdue first (most negative days)
    upcoming.sort(key=lambda x: (x["days_until"], x.get("code") or ""))
    overdue.sort(key=lambda x: (x["days_until"], x.get("code") or ""))

    return {
        "ok": True,
        "today": today.isoformat(),
        "window_days": WINDOW_DAYS,
        "annual_base_field": ANNUAL_RECHECK_BASE_FIELD,
        "confirmed_field": CONFIRMED_FIELD,
        "upcoming": upcoming,
        "overdue": overdue,
        "counts": {
            "total": len(upcoming) + len(overdue),
            "upcoming": len(upcoming),
            "overdue": len(overdue),
        },
        "labels": {
            "confirmed": LABEL_CONFIRMED,
            "annual": LABEL_ANNUAL,
        },
    }


def summary_counts(
    properties: list[dict[str, Any]] | None = None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    data = build_upcoming_items(properties, today=today)
    return {
        "ok": True,
        "today": data["today"],
        "counts": data["counts"],
    }
