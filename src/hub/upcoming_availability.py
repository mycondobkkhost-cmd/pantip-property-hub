"""Upcoming rental availability — Phase Z14.2/Z14.3.

TWO lifecycle qualification paths + ONE operational override (rental only):

  TYPE A — annual follow-up after REAL staff post (ถึงรอบเช็ก)
    base = properties.last_posted_at  (NEVER last_listed_at)
    target = last_posted_at.date + 1 calendar year
    ±WINDOW_DAYS; missing last_posted_at → never Type A

  TYPE B — admin confirmed availability (ยืนยันวันว่าง)
    owner_confirmed_available_from only
    ±WINDOW_DAYS; when both A and B → confirmed wins

  TYPE C — explicit operational Follow-up (ติดตาม) — Z14.3
    recheck_after in upcoming_followup_state.json (property_id keyed)
    Future recheck_after ⇒ hide from Upcoming list (snooze)
    Due/overdue within ±WINDOW_DAYS ⇒ face date = recheck_after (wins over annual)
    Confirmed vacancy still wins over operational when both due
    resolve_active_followup / get_property_followup: explicit recheck_after
    always wins as working date (even future / outside window)

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

from src.hub.legacy_entry_date import parse_legacy_record_entered_at

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BANGKOK = ZoneInfo("Asia/Bangkok")

# Canonical annual base — true staff publish clock (NOT วันที่รับเข้า / last_listed_at).
ANNUAL_RECHECK_BASE_FIELD = "last_posted_at"
CONFIRMED_FIELD = "owner_confirmed_available_from"
WINDOW_DAYS = 30

EVIDENCE_CONFIRMED = "confirmed"
EVIDENCE_ANNUAL = "annual_recheck"
EVIDENCE_OPERATIONAL = "operational_recheck"

LABEL_CONFIRMED = "ยืนยันวันว่าง"
LABEL_ANNUAL = "ถึงรอบเช็ก"
LABEL_OPERATIONAL = "ติดตาม"

# Canonical operational Follow-up date for property rental workflow (Z14.3).
# Stored in upcoming_followup_state.json — NOT last_posted_at / owner_confirmed.
OPERATIONAL_FOLLOWUP_FIELD = "recheck_after"


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


def bangkok_now_stamp() -> str:
    """Bangkok-local wall clock for last_posted_at (no UTC confusion in UI)."""
    return datetime.now(BANGKOK).strftime("%Y-%m-%dT%H:%M:%S")


def parse_iso_or_dmy(raw: str | None) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    # ISO date or datetime (take calendar date in stamp / ISO forms)
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


def in_followup_window(days: int, *, window: int = WINDOW_DAYS) -> bool:
    """Inclusive ±window. Outside → auto-drop from menu (property unchanged)."""
    return -window <= days <= window


def format_compact_date(d: date) -> str:
    return f"{d.day}/{d.month}/{d.year % 100}"


def target_date_phrase(d: date, *, evidence: str) -> str:
    compact = format_compact_date(d)
    if evidence == EVIDENCE_CONFIRMED:
        return f"กำลังจะว่างวันที่ {compact}"
    if evidence == EVIDENCE_OPERATIONAL:
        return f"ติดตามวันที่ {compact}"
    return f"ถึงรอบเช็กวันที่ {compact}"


def countdown_label(days: int, *, evidence: str = EVIDENCE_ANNUAL) -> str:
    if days > 0:
        return f"เหลืออีก {days} วัน"
    if days == 0:
        return "วันนี้"
    n = abs(days)
    if evidence == EVIDENCE_CONFIRMED:
        return f"เลยวันว่างมา {n} วัน"
    if evidence == EVIDENCE_OPERATIONAL:
        return f"เลยกำหนด {n} วัน"
    return f"เลยรอบเช็กมา {n} วัน"


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


def _candidate_operational(
    recheck_after: date | None,
    *,
    today: date,
) -> dict[str, Any] | None:
    """TYPE C — explicit staff operational Follow-up date (recheck_after).

    Future recheck_after snoozes (caller hides). When due/overdue within ±30,
    it becomes the face date and wins over annual (but not over confirmed vacancy).
    """
    if not recheck_after:
        return None
    days = days_until(recheck_after, today=today)
    if not in_followup_window(days):
        return None
    return {
        "evidence": EVIDENCE_OPERATIONAL,
        "label": LABEL_OPERATIONAL,
        "target_date": recheck_after.isoformat(),
        "target_display": format_compact_date(recheck_after),
        "target_phrase": target_date_phrase(recheck_after, evidence=EVIDENCE_OPERATIONAL),
        "days_until": days,
        "countdown": countdown_label(days, evidence=EVIDENCE_OPERATIONAL),
        "bucket": "overdue" if days < 0 else "upcoming",
        "base_field": OPERATIONAL_FOLLOWUP_FIELD,
    }


def resolve_active_followup(
    prop: dict[str, Any],
    *,
    today: date | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Active Follow-up date for a property (Z14.3 priority).

    Priority:
      1. Explicit operational ``recheck_after`` (always wins once set — any future/past)
      2. Otherwise ``owner_confirmed_available_from`` when present
      3. Otherwise ``last_posted_at + 1 year`` when present

    Upcoming *listing* still uses ±30 window + future-recheck hide; this resolver
    returns the working face date for Follow-up UI even when deferred/outside window.
    """
    today = bangkok_today(today)
    st = state if state is not None else _load_state()
    pid = str(prop.get("id") or "").strip()
    if not pid or not is_rental_inventory(prop):
        return None
    if is_suppressed(pid, st):
        return {
            "property_id": pid,
            "deferred": False,
            "suppressed": True,
            "active_date": None,
            "active_field": None,
            "reason": "SUPPRESSED",
            "candidate": None,
        }
    item_st = (st.get("items") or {}).get(pid) or {}
    ra = parse_iso_or_dmy(str(item_st.get(OPERATIONAL_FOLLOWUP_FIELD) or ""))

    def _pack(cand: dict[str, Any], *, deferred: bool = False) -> dict[str, Any]:
        return {
            "property_id": pid,
            "deferred": deferred,
            "suppressed": False,
            "active_date": cand["target_date"],
            "active_field": cand.get("base_field")
            or (
                CONFIRMED_FIELD
                if cand["evidence"] == EVIDENCE_CONFIRMED
                else ANNUAL_RECHECK_BASE_FIELD
            ),
            "reason": {
                EVIDENCE_OPERATIONAL: "OPERATIONAL_RECHECK",
                EVIDENCE_CONFIRMED: "CONFIRMED_AVAILABILITY",
                EVIDENCE_ANNUAL: "POST_FIRST_YEAR",
            }.get(cand["evidence"], cand["evidence"]),
            "evidence": cand["evidence"],
            "label": cand.get("label") or "",
            "target_display": cand.get("target_display") or "",
            "target_phrase": cand.get("target_phrase") or "",
            "countdown": cand.get("countdown") or "",
            "days_until": cand.get("days_until"),
            "candidate": cand,
        }

    # Explicit staff date always wins (even future / outside ±30).
    if ra:
        days = days_until(ra, today=today)
        cand = {
            "evidence": EVIDENCE_OPERATIONAL,
            "label": LABEL_OPERATIONAL,
            "target_date": ra.isoformat(),
            "target_display": format_compact_date(ra),
            "target_phrase": target_date_phrase(ra, evidence=EVIDENCE_OPERATIONAL),
            "days_until": days,
            "countdown": countdown_label(days, evidence=EVIDENCE_OPERATIONAL),
            "bucket": "overdue" if days < 0 else ("upcoming" if days == 0 or in_followup_window(days) else "scheduled"),
            "base_field": OPERATIONAL_FOLLOWUP_FIELD,
        }
        return _pack(cand, deferred=ra > today)

    # Derived lifecycle targets (may be outside Upcoming ±30 — still shown in sheet).
    conf_raw = prop.get(CONFIRMED_FIELD) or prop.get("owner_confirmed_available_from")
    conf_d = parse_iso_or_dmy(str(conf_raw or ""))
    if conf_d:
        days = days_until(conf_d, today=today)
        cand = {
            "evidence": EVIDENCE_CONFIRMED,
            "label": LABEL_CONFIRMED,
            "target_date": conf_d.isoformat(),
            "target_display": format_compact_date(conf_d),
            "target_phrase": target_date_phrase(conf_d, evidence=EVIDENCE_CONFIRMED),
            "days_until": days,
            "countdown": countdown_label(days, evidence=EVIDENCE_CONFIRMED),
            "bucket": "overdue" if days < 0 else "upcoming",
            "base_field": CONFIRMED_FIELD,
        }
        return _pack(cand)

    posted = parse_iso_or_dmy(str(prop.get(ANNUAL_RECHECK_BASE_FIELD) or ""))
    if posted:
        target = add_one_year(posted)
        days = days_until(target, today=today)
        cand = {
            "evidence": EVIDENCE_ANNUAL,
            "label": LABEL_ANNUAL,
            "target_date": target.isoformat(),
            "target_display": format_compact_date(target),
            "target_phrase": target_date_phrase(target, evidence=EVIDENCE_ANNUAL),
            "days_until": days,
            "countdown": countdown_label(days, evidence=EVIDENCE_ANNUAL),
            "bucket": "overdue" if days < 0 else "upcoming",
            "base_date": posted.isoformat(),
            "base_field": ANNUAL_RECHECK_BASE_FIELD,
        }
        return _pack(cand)

    return {
        "property_id": pid,
        "deferred": False,
        "suppressed": False,
        "active_date": None,
        "active_field": None,
        "reason": "NONE",
        "candidate": None,
    }


def get_property_followup(
    property_id: str,
    *,
    today: date | None = None,
    properties: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Load Follow-up detail for one property_id (never property_code first-match)."""
    pid = str(property_id or "").strip()
    if not pid:
        raise ValueError("property_id required")
    if properties is None:
        from src.hub.project_store import load_properties

        properties = load_properties()
    prop = None
    for p in properties or []:
        if str(p.get("id") or "").strip() == pid:
            prop = p
            break
    if not prop:
        raise ValueError("ไม่พบทรัพย์")
    detail = resolve_active_followup(prop, today=today)
    if not detail:
        detail = {
            "property_id": pid,
            "deferred": False,
            "suppressed": False,
            "active_date": None,
            "active_field": None,
            "reason": "NONE",
            "candidate": None,
        }
    detail["code"] = str(prop.get("code") or "")
    detail["project_name"] = str(prop.get("project_name") or "")
    detail["notes"] = str(prop.get("notes") or "").strip()
    detail["last_posted_at"] = str(prop.get(ANNUAL_RECHECK_BASE_FIELD) or "")
    detail["owner_confirmed_available_from"] = str(
        prop.get(CONFIRMED_FIELD) or prop.get("owner_confirmed_available_from") or ""
    )
    detail["operational_field"] = OPERATIONAL_FOLLOWUP_FIELD
    return detail


def _candidate_confirmed(prop: dict[str, Any], *, today: date) -> dict[str, Any] | None:
    raw = prop.get(CONFIRMED_FIELD) or prop.get("owner_confirmed_available_from")
    target = parse_iso_or_dmy(str(raw or ""))
    if not target:
        return None
    days = days_until(target, today=today)
    if not in_followup_window(days):
        return None
    return {
        "evidence": EVIDENCE_CONFIRMED,
        "label": LABEL_CONFIRMED,
        "target_date": target.isoformat(),
        "target_display": format_compact_date(target),
        "target_phrase": target_date_phrase(target, evidence=EVIDENCE_CONFIRMED),
        "days_until": days,
        "countdown": countdown_label(days, evidence=EVIDENCE_CONFIRMED),
        "bucket": "overdue" if days < 0 else "upcoming",
    }


def _candidate_annual(prop: dict[str, Any], *, today: date) -> dict[str, Any] | None:
    """TYPE A: one year after LATEST real last_posted_at — never last_listed_at."""
    posted = parse_iso_or_dmy(str(prop.get(ANNUAL_RECHECK_BASE_FIELD) or ""))
    if not posted:
        return None
    # Safety: never fall back to last_listed_at even if present
    target = add_one_year(posted)
    days = days_until(target, today=today)
    if not in_followup_window(days):
        return None
    return {
        "evidence": EVIDENCE_ANNUAL,
        "label": LABEL_ANNUAL,
        "target_date": target.isoformat(),
        "target_display": format_compact_date(target),
        "target_phrase": target_date_phrase(target, evidence=EVIDENCE_ANNUAL),
        "days_until": days,
        "countdown": countdown_label(days, evidence=EVIDENCE_ANNUAL),
        "bucket": "overdue" if days < 0 else "upcoming",
        "base_date": posted.isoformat(),
        "base_field": ANNUAL_RECHECK_BASE_FIELD,
    }


def _row_from_prop(prop: dict[str, Any], cand: dict[str, Any]) -> dict[str, Any]:
    notes = str(prop.get("notes") or "").strip()
    if notes in ("-", "—", "–"):
        notes = ""
    return {
        "property_id": str(prop.get("id") or ""),
        "code": str(prop.get("code") or ""),
        "project_name": str(prop.get("project_name") or ""),
        "rent_price": str(prop.get("rent_price") or ""),
        "notes": notes[:200],
        "source_url": str(prop.get("source_url") or ""),
        "post_pages_url": str(prop.get("post_pages_url") or ""),
        "post_url": str(prop.get("post_url") or ""),
        **cand,
    }


def build_upcoming_items(
    properties: list[dict[str, Any]] | None = None,
    *,
    today: date | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive upcoming/overdue rental reminders. One row per property_id; confirmed wins."""
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
        item_st = (st.get("items") or {}).get(pid) or {}
        ra = parse_iso_or_dmy(str(item_st.get(OPERATIONAL_FOLLOWUP_FIELD) or ""))
        if ra and ra > today:
            continue

        confirmed = _candidate_confirmed(prop, today=today)
        operational = _candidate_operational(ra, today=today)
        annual = _candidate_annual(prop, today=today)
        # Priority: confirmed vacancy > explicit operational recheck > annual
        chosen = confirmed or operational or annual
        if not chosen:
            continue
        row = _row_from_prop(prop, chosen)
        if row["bucket"] == "overdue":
            overdue.append(row)
        else:
            upcoming.append(row)

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
            "operational": LABEL_OPERATIONAL,
        },
        "operational_field": OPERATIONAL_FOLLOWUP_FIELD,
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
