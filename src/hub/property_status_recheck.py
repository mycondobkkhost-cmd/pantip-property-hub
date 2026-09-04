"""Property status recheck — age-based legacy follow-up (NOT near-lease-end)."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.hub.legacy_entry_date import (
    LEGACY_RECORD_ENTERED_AT_FIELD,
    RECHECK_THRESHOLD_CANDIDATES,
    audit_age_distribution,
    parse_legacy_record_entered_at,
    record_age_days,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_DIR = BASE_DIR / ".local" / "property_status_recheck_phase_z7"
RECHECKS_PATH = LOCAL_DIR / "rechecks.json"
CONTACT_EVENTS_PATH = LOCAL_DIR / "contact_events.json"
CONFIG_PATH = LOCAL_DIR / "config.json"

RECHECK_STATUSES = frozenset(
    {
        "UPCOMING",
        "DUE",
        "OVERDUE",
        "CONTACTED_WAITING",
        "OWNER_CONFIRMED_AVAILABLE",
        "OWNER_CONFIRMED_AVAILABLE_SOON",
        "OWNER_CONFIRMED_NOT_AVAILABLE",
        "OWNER_CONFIRMED_RENTED",
        "OWNER_CONFIRMED_SOLD",
        "OWNER_NOT_MARKETING",
        "CONTACT_FAILED",
        "DEFERRED",
        "CLOSED",
    }
)

OWNER_RESPONSES = frozenset(
    {
        "CONTACTED_WAITING",
        "OWNER_CONFIRMED_AVAILABLE",
        "OWNER_CONFIRMED_AVAILABLE_SOON",
        "OWNER_CONFIRMED_NOT_AVAILABLE",
        "OWNER_CONFIRMED_RENTED",
        "OWNER_CONFIRMED_SOLD",
        "OWNER_NOT_MARKETING",
        "CONTACT_FAILED",
        "DEFERRED",
        "CALLBACK_REQUESTED",
    }
)

DEFAULT_THRESHOLDS = [90, 180, 270, 365]
DEFAULT_ACTIVE_THRESHOLD = 180  # policy candidate for dry-run default


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> date:
    return date.today()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _save_json(path: Path, data: Any) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict[str, Any]:
    cfg = _load_json(CONFIG_PATH, {})
    thresholds = cfg.get("recheck_thresholds_days") or DEFAULT_THRESHOLDS
    active = int(cfg.get("active_threshold_days") or DEFAULT_ACTIVE_THRESHOLD)
    return {
        "recheck_thresholds_days": [int(x) for x in thresholds],
        "active_threshold_days": active,
        "test_only": True,
        "legacy_wang_active_scheduling": False,
    }


def save_config(**fields: Any) -> dict[str, Any]:
    cfg = load_config()
    cfg.update({k: v for k, v in fields.items() if v is not None})
    _save_json(CONFIG_PATH, cfg)
    return cfg


def _load_rechecks() -> list[dict[str, Any]]:
    return list(_load_json(RECHECKS_PATH, {"items": []}).get("items") or [])


def _save_rechecks(items: list[dict[str, Any]]) -> None:
    _save_json(RECHECKS_PATH, {"items": items, "updated_at": _now(), "test_only": True})


def _load_contacts() -> list[dict[str, Any]]:
    return list(_load_json(CONTACT_EVENTS_PATH, {"items": []}).get("items") or [])


def _save_contacts(items: list[dict[str, Any]]) -> None:
    _save_json(CONTACT_EVENTS_PATH, {"items": items, "updated_at": _now(), "test_only": True})


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item)
    item.setdefault("recheck_id", "")
    item.setdefault("property_id", "")
    item.setdefault("property_code_display", "")
    item.setdefault("project_name_display", "")
    item.setdefault("source_record_entered_at", "")
    item.setdefault("record_age_days", 0)
    item.setdefault("trigger_stage", "")
    item.setdefault("recheck_status", "UPCOMING")
    item.setdefault("recommended_followup_at", "")
    item.setdefault("assigned_operator_id", "")
    item.setdefault("last_contacted_at", "")
    item.setdefault("next_followup_at", "")
    item.setdefault("owner_response", "")
    item.setdefault("owner_confirmed_available_from", "")
    item.setdefault("confirmed_at", "")
    item.setdefault("confirmed_by", "")
    item.setdefault("confirmation_source", "")
    item.setdefault("source_contact_event_id", "")
    item.setdefault("source_fingerprint", "")
    item.setdefault("test_only", True)
    item.setdefault("created_at", "")
    item.setdefault("updated_at", "")
    return item


def trigger_stage_for_age(age_days: int, thresholds: list[int] | None = None) -> str:
    thresholds = sorted(thresholds or load_config()["recheck_thresholds_days"])
    hit = [t for t in thresholds if age_days >= t]
    if not hit:
        return "UNDER_THRESHOLD"
    return f"AGE_{max(hit)}D"


def derive_recheck_status(item: dict[str, Any], *, today: date | None = None) -> str:
    today = today or _today()
    st = (item.get("recheck_status") or "UPCOMING").strip()
    if st in {"CLOSED", "OWNER_CONFIRMED_AVAILABLE", "OWNER_CONFIRMED_NOT_AVAILABLE", "OWNER_CONFIRMED_RENTED", "OWNER_CONFIRMED_SOLD", "OWNER_NOT_MARKETING"}:
        return st
    nxt = (item.get("next_followup_at") or item.get("recommended_followup_at") or "")[:10]
    if nxt:
        try:
            nd = date.fromisoformat(nxt)
            if nd < today:
                return "OVERDUE"
            if nd == today:
                return "DUE"
        except ValueError:
            pass
    age = int(item.get("record_age_days") or 0)
    active = load_config()["active_threshold_days"]
    if age >= active:
        return "UPCOMING"
    return st


def build_recheck_dry_run(*, threshold_days: int | None = None) -> dict[str, Any]:
    """Dry-run queue from data-entry age only — never legacy วันที่ว่าง."""
    from src.hub.project_store import load_properties

    threshold = threshold_days or load_config()["active_threshold_days"]
    today = _today()
    candidates: list[dict[str, Any]] = []
    for p in load_properties():
        pid = str(p.get("id") or "")
        entered = parse_legacy_record_entered_at(p.get(LEGACY_RECORD_ENTERED_AT_FIELD))
        age = record_age_days(entered, today=today)
        if age is None or age < threshold:
            continue
        candidates.append(
            {
                "property_id": pid,
                "property_code_display": p.get("code") or "",
                "project_name_display": p.get("project_name") or "",
                "source_record_entered_at": entered.isoformat() if entered else "",
                "record_age_days": age,
                "trigger_stage": trigger_stage_for_age(age),
                "recheck_status": "UPCOMING",
                "purpose": "PROPERTY_STATUS_RECHECK",
                "not_near_lease_end": True,
            }
        )
    candidates.sort(key=lambda x: (-int(x.get("record_age_days") or 0), x.get("property_code_display") or ""))
    audit = audit_age_distribution(today=today)
    workloads = audit["recheck_workload_by_threshold"]
    return {
        "threshold_days": threshold,
        "candidate_count": len(candidates),
        "workloads_by_threshold": workloads,
        "age_distribution": audit,
        "legacy_wang_scheduling_disabled": True,
        "candidates_sample": candidates[:20],
    }


def upsert_recheck(**fields: Any) -> dict[str, Any]:
    if not fields.get("property_id"):
        raise ValueError("property_id required")
    items = _load_rechecks()
    pid = str(fields["property_id"])
    now = _now()
    for i, it in enumerate(items):
        if it.get("property_id") == pid and it.get("recheck_status") not in {"CLOSED"}:
            merged = _normalize({**it, **fields, "updated_at": now})
            merged["recheck_status"] = derive_recheck_status(merged)
            items[i] = merged
            _save_rechecks(items)
            return merged
    rec = _normalize(
        {
            **fields,
            "recheck_id": fields.get("recheck_id") or f"psr_{uuid.uuid4().hex[:12]}",
            "created_at": now,
            "updated_at": now,
            "test_only": True,
        }
    )
    rec["recheck_status"] = derive_recheck_status(rec)
    items.append(rec)
    _save_rechecks(items)
    return rec


def record_contact(
    *,
    property_id: str,
    actor: str,
    result: str,
    note: str = "",
    next_followup_at: str = "",
    owner_confirmed_available_from: str = "",
) -> dict[str, Any]:
    if result not in OWNER_RESPONSES:
        raise ValueError(f"invalid result: {result}")
    evt = {
        "contact_event_id": f"ce_{uuid.uuid4().hex[:12]}",
        "property_id": property_id,
        "actor": actor,
        "contacted_at": _now(),
        "result": result,
        "note": note,
        "next_followup_at": next_followup_at,
        "test_only": True,
    }
    contacts = _load_contacts()
    contacts.append(evt)
    _save_contacts(contacts)

    status_map = {
        "OWNER_CONFIRMED_AVAILABLE": "OWNER_CONFIRMED_AVAILABLE",
        "OWNER_CONFIRMED_AVAILABLE_SOON": "OWNER_CONFIRMED_AVAILABLE_SOON",
        "OWNER_CONFIRMED_NOT_AVAILABLE": "OWNER_CONFIRMED_NOT_AVAILABLE",
        "OWNER_CONFIRMED_RENTED": "OWNER_CONFIRMED_RENTED",
        "OWNER_CONFIRMED_SOLD": "OWNER_CONFIRMED_SOLD",
        "OWNER_NOT_MARKETING": "OWNER_NOT_MARKETING",
        "CONTACTED_WAITING": "CONTACTED_WAITING",
        "CONTACT_FAILED": "CONTACT_FAILED",
        "CALLBACK_REQUESTED": "CONTACTED_WAITING",
        "DEFERRED": "DEFERRED",
    }
    updates: dict[str, Any] = {
        "owner_response": result,
        "last_contacted_at": evt["contacted_at"],
        "next_followup_at": next_followup_at,
        "source_contact_event_id": evt["contact_event_id"],
        "recheck_status": status_map.get(result, "CONTACTED_WAITING"),
    }
    if owner_confirmed_available_from and result in {"OWNER_CONFIRMED_AVAILABLE", "OWNER_CONFIRMED_AVAILABLE_SOON"}:
        updates.update(
            {
                "owner_confirmed_available_from": owner_confirmed_available_from[:10],
                "confirmed_at": _now(),
                "confirmed_by": actor,
                "confirmation_source": "operator_contact",
            }
        )
    upsert_recheck(property_id=property_id, **updates)
    return evt


def list_contact_events(property_id: str) -> list[dict[str, Any]]:
    pid = (property_id or "").strip()
    return [e for e in _load_contacts() if e.get("property_id") == pid]


def list_rechecks() -> list[dict[str, Any]]:
    return sorted(
        [_normalize(x) for x in _load_rechecks()],
        key=lambda x: (-int(x.get("record_age_days") or 0), x.get("property_code_display") or ""),
    )


def summary() -> dict[str, int]:
    items = list_rechecks()
    today = _today().isoformat()
    return {
        "due_today": sum(1 for x in items if (x.get("next_followup_at") or "")[:10] == today),
        "overdue": sum(1 for x in items if x.get("recheck_status") == "OVERDUE"),
        "old_recheck": sum(1 for x in items if int(x.get("record_age_days") or 0) >= load_config()["active_threshold_days"]),
        "waiting_owner": sum(1 for x in items if x.get("recheck_status") == "CONTACTED_WAITING"),
        "owner_confirmed_available": sum(
            1 for x in items if x.get("recheck_status") in {"OWNER_CONFIRMED_AVAILABLE", "OWNER_CONFIRMED_AVAILABLE_SOON"}
        ),
        "total_active": len([x for x in items if x.get("recheck_status") != "CLOSED"]),
    }


def seed_test_fixtures() -> list[dict[str, Any]]:
    today = _today()
    fixtures = [
        ("test_psr_recent", (today - __import__("datetime").timedelta(days=45)).isoformat(), 45, "UPCOMING"),
        ("test_psr_120d", (today - __import__("datetime").timedelta(days=120)).isoformat(), 120, "UPCOMING"),
        ("test_psr_200d", (today - __import__("datetime").timedelta(days=200)).isoformat(), 200, "DUE"),
        ("test_psr_400d", (today - __import__("datetime").timedelta(days=400)).isoformat(), 400, "OVERDUE"),
        ("test_psr_confirmed", (today - __import__("datetime").timedelta(days=300)).isoformat(), 300, "OWNER_CONFIRMED_AVAILABLE"),
    ]
    out = []
    for pid, entered, age, status in fixtures:
        out.append(
            upsert_recheck(
                property_id=pid,
                property_code_display=pid.upper(),
                project_name_display="Test Tower",
                source_record_entered_at=entered,
                record_age_days=age,
                trigger_stage=trigger_stage_for_age(age),
                recheck_status=status,
                test_only=True,
            )
        )
    # owner confirmed future date fixture
    record_contact(
        property_id="test_psr_confirmed",
        actor="qa",
        result="OWNER_CONFIRMED_AVAILABLE_SOON",
        owner_confirmed_available_from=(today + __import__("datetime").timedelta(days=30)).isoformat(),
    )
    return out
