"""Lease opportunity foundation — Phase Z5 (local TEST_ONLY storage)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.hub.operational_contracts import LEASE_OPPORTUNITY_CONTRACT
from src.hub.project_store import load_properties

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_DIR = BASE_DIR / ".local" / "lease_opportunity_phase_z5"
OPPORTUNITIES_PATH = LOCAL_DIR / "opportunities.json"
CONTACT_EVENTS_PATH = LOCAL_DIR / "contact_events.json"
CONFIG_PATH = LOCAL_DIR / "config.json"

EVIDENCE_CLASSES = frozenset(LEASE_OPPORTUNITY_CONTRACT["evidence_classes"])
STRONG_EVIDENCE = frozenset(LEASE_OPPORTUNITY_CONTRACT["strong_evidence"])
OPPORTUNITY_STATUSES = frozenset(LEASE_OPPORTUNITY_CONTRACT["statuses"])
CONTACT_RESULTS = frozenset(
    {
        "OWNER_CONFIRMED_VACANCY",
        "TENANT_RENEWED",
        "OWNER_NOT_MARKETING",
        "WAITING_FOR_OWNER",
        "CONTACT_FAILED",
        "CALLBACK_REQUESTED",
    }
)

DEFAULT_FOLLOW_UP_WINDOWS = [60, 45, 30, 14]
ESTIMATED_12M_DISCLAIMER_TH = "คาดการณ์จากรอบเช่าเดิม ยังไม่ได้ยืนยันจากเจ้าของ"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> date:
    return date.today()


def _parse_iso_day(raw: str | None) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict[str, Any]:
    cfg = _load_json(CONFIG_PATH, {})
    windows = cfg.get("follow_up_windows_days") or DEFAULT_FOLLOW_UP_WINDOWS
    return {
        "follow_up_windows_days": [int(x) for x in windows],
        "test_only": True,
        "storage": str(LOCAL_DIR),
    }


def save_config(**fields: Any) -> dict[str, Any]:
    cfg = load_config()
    cfg.update({k: v for k, v in fields.items() if v is not None})
    _save_json(CONFIG_PATH, cfg)
    return cfg


def _load_opportunities_raw() -> list[dict[str, Any]]:
    data = _load_json(OPPORTUNITIES_PATH, {"items": []})
    return list(data.get("items") or [])


def _save_opportunities(items: list[dict[str, Any]]) -> None:
    _save_json(OPPORTUNITIES_PATH, {"items": items, "updated_at": _now(), "test_only": True})


def _load_contact_events_raw() -> list[dict[str, Any]]:
    data = _load_json(CONTACT_EVENTS_PATH, {"items": []})
    return list(data.get("items") or [])


def _save_contact_events(items: list[dict[str, Any]]) -> None:
    _save_json(CONTACT_EVENTS_PATH, {"items": items, "updated_at": _now(), "test_only": True})


def _is_rental(prop: dict[str, Any]) -> bool:
    rent = str(prop.get("rent_price") or "").strip()
    sale = str(prop.get("sale_price") or "").strip()
    kind = str(prop.get("listing_kind") or prop.get("property_type") or "").lower()
    if rent and not sale:
        return True
    if "เช่า" in kind or kind == "rent":
        return True
    return bool(rent)


def audit_rental_data_coverage() -> dict[str, Any]:
    """Count lease evidence coverage without exposing PII."""
    props = load_properties()
    rentals = [p for p in props if _is_rental(p)]

    explicit_end = 0
    explicit_start_term = 0
    start_only = 0
    deal_date_only = 0
    no_usable = 0

    # properties.json has no lease fields; tenant store may
    from src.hub.tenant_store import load_tenants

    tenants = load_tenants()
    tenant_by_code: dict[str, dict] = {}
    for t in tenants:
        code = str(t.get("property_code") or "").strip().upper()
        if code:
            tenant_by_code[code] = t

    for p in rentals:
        code = str(p.get("code") or "").strip().upper()
        t = tenant_by_code.get(code) or {}
        cs = _parse_iso_day(t.get("contract_start"))
        ce = _parse_iso_day(t.get("contract_end"))
        if ce:
            explicit_end += 1
            continue
        if cs:
            # tenant store has start but no end — cannot derive term without explicit months
            start_only += 1
            continue
        # last_listed_at is acquisition date, NOT lease evidence
        if _parse_iso_day(p.get("last_listed_at")):
            deal_date_only += 1
        else:
            no_usable += 1

    total = len(rentals)
    high = explicit_end + explicit_start_term
    estimated = start_only + deal_date_only
    return {
        "RENTAL_PROPERTIES_TOTAL": total,
        "EXPLICIT_LEASE_END_AVAILABLE": explicit_end,
        "EXPLICIT_LEASE_START_AND_TERM_AVAILABLE": explicit_start_term,
        "EXPLICIT_LEASE_START_ONLY": start_only,
        "DEAL_DATE_ONLY": deal_date_only,
        "NO_USABLE_DATE": no_usable,
        "HIGH_CONFIDENCE_FOLLOWUP": high,
        "ESTIMATED_FOLLOWUP": estimated,
        "INSUFFICIENT_DATA": no_usable,
        "tenant_records": len(tenants),
        "properties_date_fields": ["last_listed_at (acquisition only, not lease end)"],
        "tenant_date_fields": ["contract_start", "contract_end"],
        "sheet_dropped_fields": ["วันที่ว่าง (available_raw read but not stored in properties.json)"],
        "data_ready_for_mvp": high > 0,
    }


def classify_lease_evidence(
    *,
    contract_end: str | None = None,
    contract_start: str | None = None,
    deal_date: str | None = None,
    term_months: int | None = None,
) -> dict[str, Any]:
    """Classify evidence without inventing dates."""
    ce = _parse_iso_day(contract_end)
    cs = _parse_iso_day(contract_start)
    dd = _parse_iso_day(deal_date)

    if ce:
        return {
            "evidence_class": "CONFIRMED_LEASE_END",
            "expected_lease_end_date": ce.isoformat(),
            "lease_start_date": cs.isoformat() if cs else None,
            "strong": True,
        }
    if cs and term_months and term_months > 0:
        end = cs + timedelta(days=int(term_months * 30.437))
        return {
            "evidence_class": "DERIVED_FROM_EXPLICIT_TERM",
            "expected_lease_end_date": end.isoformat(),
            "lease_start_date": cs.isoformat(),
            "expected_lease_term_months": term_months,
            "strong": True,
        }
    if cs and not term_months:
        return {
            "evidence_class": "INSUFFICIENT_EVIDENCE",
            "lease_start_date": cs.isoformat(),
            "strong": False,
            "note": "start date only does not invent term",
        }
    if dd:
        est_end = dd + timedelta(days=365)
        return {
            "evidence_class": "ESTIMATED_12M_CANDIDATE",
            "expected_lease_end_date": est_end.isoformat(),
            "source_event_date": dd.isoformat(),
            "strong": False,
            "disclaimer_th": ESTIMATED_12M_DISCLAIMER_TH,
        }
    if dd and not cs and not ce:
        return {
            "evidence_class": "DEAL_DATE_ONLY_CANDIDATE",
            "source_event_date": dd.isoformat(),
            "strong": False,
        }
    return {"evidence_class": "INSUFFICIENT_EVIDENCE", "strong": False}


def vacancy_safety_status(*, evidence_class: str, owner_confirmed: bool = False) -> str:
    """Never map elapsed time to AVAILABLE."""
    if owner_confirmed:
        return "OWNER_CONFIRMED_VACANT_SOON"
    if evidence_class in STRONG_EVIDENCE:
        return "FOLLOW_UP_RECOMMENDED"
    if evidence_class in {"ESTIMATED_12M_CANDIDATE", "DEAL_DATE_ONLY_CANDIDATE"}:
        return "FOLLOW_UP_RECOMMENDED"
    return "INSUFFICIENT_EVIDENCE"


def _normalize_opportunity(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item)
    item.setdefault("opportunity_id", "")
    item.setdefault("property_id", "")
    item.setdefault("listing_cycle_id", "")
    item.setdefault("project_id", "")
    item.setdefault("property_code_display", "")
    item.setdefault("project_name_display", "")
    item.setdefault("evidence_class", "INSUFFICIENT_EVIDENCE")
    item.setdefault("source_event_type", "")
    item.setdefault("source_event_date", "")
    item.setdefault("lease_start_date", "")
    item.setdefault("expected_lease_end_date", "")
    item.setdefault("expected_lease_term_months", 0)
    item.setdefault("opportunity_status", "UPCOMING")
    item.setdefault("first_followup_at", "")
    item.setdefault("next_followup_at", "")
    item.setdefault("assigned_operator_id", "")
    item.setdefault("owner_contact_state", "UNKNOWN")
    item.setdefault("owner_confirmed_status", "")
    item.setdefault("owner_confirmed_vacancy_date", "")
    item.setdefault("test_only", True)
    item.setdefault("created_at", "")
    item.setdefault("updated_at", "")
    return item


def _dedupe_key(property_id: str, listing_cycle_id: str) -> str:
    return f"{property_id}::{listing_cycle_id or 'default'}"


def list_opportunities(*, include_closed: bool = False) -> list[dict[str, Any]]:
    items = [_normalize_opportunity(x) for x in _load_opportunities_raw()]
    if not include_closed:
        items = [x for x in items if x.get("opportunity_status") not in {"CLOSED"}]
    today = _today()

    def sort_key(x: dict) -> tuple:
        end = _parse_iso_day(x.get("expected_lease_end_date")) or date.max
        nxt = _parse_iso_day(x.get("next_followup_at")) or date.max
        overdue = 0 if nxt <= today else 1
        return (overdue, end, x.get("property_code_display") or "")

    return sorted(items, key=sort_key)


def opportunity_summary() -> dict[str, int]:
    items = list_opportunities(include_closed=True)
    today = _today()
    due_today = 0
    overdue = 0
    within_30 = 0
    within_60 = 0
    owner_confirmed = 0
    waiting = 0
    for it in items:
        nxt = _parse_iso_day(it.get("next_followup_at"))
        end = _parse_iso_day(it.get("expected_lease_end_date"))
        if it.get("opportunity_status") == "OWNER_CONFIRMED_VACANT_SOON":
            owner_confirmed += 1
        if it.get("opportunity_status") == "CONTACTED_WAITING":
            waiting += 1
        if nxt:
            if nxt < today:
                overdue += 1
            elif nxt == today:
                due_today += 1
        if end:
            days = (end - today).days
            if 0 <= days <= 30:
                within_30 += 1
            if 0 <= days <= 60:
                within_60 += 1
    return {
        "due_today": due_today,
        "overdue": overdue,
        "within_30_days": within_30,
        "within_60_days": within_60,
        "owner_confirmed_vacant_soon": owner_confirmed,
        "waiting_for_owner": waiting,
        "total_active": len([x for x in items if x.get("opportunity_status") != "CLOSED"]),
    }


def get_opportunity(opportunity_id: str) -> dict[str, Any] | None:
    oid = (opportunity_id or "").strip()
    for it in _load_opportunities_raw():
        if it.get("opportunity_id") == oid:
            return _normalize_opportunity(it)
    return None


def upsert_opportunity(**fields: Any) -> dict[str, Any]:
    if not fields.get("property_id"):
        raise ValueError("lease opportunity requires property_id")
    items = _load_opportunities_raw()
    now = _now()
    pid = str(fields["property_id"])
    cycle = str(fields.get("listing_cycle_id") or "cycle_default")
    key = _dedupe_key(pid, cycle)

    for i, it in enumerate(items):
        if _dedupe_key(str(it.get("property_id") or ""), str(it.get("listing_cycle_id") or "cycle_default")) == key:
            if it.get("opportunity_status") not in {"CLOSED", "TENANT_RENEWED", "OWNER_NOT_MARKETING"}:
                merged = _normalize_opportunity({**it, **fields, "updated_at": now})
                items[i] = merged
                _save_opportunities(items)
                return merged

    opp = _normalize_opportunity(
        {
            **fields,
            "opportunity_id": fields.get("opportunity_id") or f"lo_{uuid.uuid4().hex[:12]}",
            "listing_cycle_id": cycle,
            "created_at": now,
            "updated_at": now,
            "test_only": True,
        }
    )
    items.append(opp)
    _save_opportunities(items)
    return opp


def record_contact_event(
    *,
    opportunity_id: str,
    actor: str,
    result: str,
    note: str = "",
    next_followup_at: str = "",
) -> dict[str, Any]:
    if result not in CONTACT_RESULTS:
        raise ValueError(f"invalid contact result: {result}")
    events = _load_contact_events_raw()
    evt = {
        "contact_event_id": f"ce_{uuid.uuid4().hex[:12]}",
        "opportunity_id": opportunity_id,
        "actor": actor,
        "contacted_at": _now(),
        "result": result,
        "note": note,
        "next_followup_at": next_followup_at,
        "test_only": True,
    }
    events.append(evt)
    _save_contact_events(events)

    # Update opportunity status from result (append-only history preserved)
    opp = get_opportunity(opportunity_id)
    if opp:
        status_map = {
            "OWNER_CONFIRMED_VACANCY": "OWNER_CONFIRMED_VACANT_SOON",
            "TENANT_RENEWED": "TENANT_RENEWED",
            "OWNER_NOT_MARKETING": "OWNER_NOT_MARKETING",
            "WAITING_FOR_OWNER": "CONTACTED_WAITING",
            "CONTACT_FAILED": "CONTACT_FAILED",
            "CALLBACK_REQUESTED": "CONTACTED_WAITING",
        }
        upsert_opportunity(
            property_id=opp["property_id"],
            listing_cycle_id=opp.get("listing_cycle_id"),
            opportunity_status=status_map.get(result, opp.get("opportunity_status")),
            next_followup_at=next_followup_at or opp.get("next_followup_at"),
            owner_confirmed_status="CONFIRMED" if result == "OWNER_CONFIRMED_VACANCY" else opp.get("owner_confirmed_status"),
        )
    return evt


def list_contact_events(opportunity_id: str) -> list[dict[str, Any]]:
    oid = (opportunity_id or "").strip()
    return [e for e in _load_contact_events_raw() if e.get("opportunity_id") == oid]


def seed_test_fixtures() -> list[dict[str, Any]]:
    """Sanitized TEST_ONLY opportunities for local MVP."""
    today = _today()
    fixtures = [
        {
            "property_id": "test_prop_explicit_end",
            "listing_cycle_id": "cycle_2024_01",
            "property_code_display": "TEST-EXPLICIT-END",
            "project_name_display": "Test Tower A",
            "evidence_class": "CONFIRMED_LEASE_END",
            "expected_lease_end_date": (today + timedelta(days=25)).isoformat(),
            "opportunity_status": "FOLLOW_UP_DUE",
            "next_followup_at": today.isoformat(),
        },
        {
            "property_id": "test_prop_derived_term",
            "listing_cycle_id": "cycle_2023_06",
            "property_code_display": "TEST-DERIVED-TERM",
            "project_name_display": "Test Tower B",
            "evidence_class": "DERIVED_FROM_EXPLICIT_TERM",
            "lease_start_date": (today - timedelta(days=335)).isoformat(),
            "expected_lease_end_date": (today + timedelta(days=30)).isoformat(),
            "expected_lease_term_months": 12,
            "opportunity_status": "UPCOMING",
            "next_followup_at": (today + timedelta(days=14)).isoformat(),
        },
        {
            "property_id": "test_prop_estimated_12m",
            "listing_cycle_id": "cycle_est",
            "property_code_display": "TEST-EST-12M",
            "project_name_display": "Test Tower C",
            "evidence_class": "ESTIMATED_12M_CANDIDATE",
            "expected_lease_end_date": (today + timedelta(days=45)).isoformat(),
            "disclaimer_th": ESTIMATED_12M_DISCLAIMER_TH,
            "opportunity_status": "UPCOMING",
        },
        {
            "property_id": "test_prop_overdue",
            "listing_cycle_id": "cycle_overdue",
            "property_code_display": "TEST-OVERDUE",
            "project_name_display": "Test Tower D",
            "evidence_class": "CONFIRMED_LEASE_END",
            "expected_lease_end_date": (today - timedelta(days=5)).isoformat(),
            "opportunity_status": "FOLLOW_UP_DUE",
            "next_followup_at": (today - timedelta(days=3)).isoformat(),
        },
        {
            "property_id": "test_prop_owner_confirmed",
            "listing_cycle_id": "cycle_confirmed",
            "property_code_display": "TEST-OWNER-OK",
            "project_name_display": "Test Tower E",
            "evidence_class": "CONFIRMED_LEASE_END",
            "expected_lease_end_date": (today + timedelta(days=10)).isoformat(),
            "opportunity_status": "OWNER_CONFIRMED_VACANT_SOON",
            "owner_confirmed_status": "CONFIRMED",
            "owner_confirmed_vacancy_date": (today + timedelta(days=10)).isoformat(),
        },
        {
            "property_id": "test_prop_renewed",
            "listing_cycle_id": "cycle_renewed",
            "property_code_display": "TEST-RENEWED",
            "project_name_display": "Test Tower F",
            "evidence_class": "CONFIRMED_LEASE_END",
            "expected_lease_end_date": (today + timedelta(days=60)).isoformat(),
            "opportunity_status": "TENANT_RENEWED",
        },
    ]
    out = []
    for f in fixtures:
        out.append(upsert_opportunity(**f))
    return out


def build_api_payload() -> dict[str, Any]:
    audit = audit_rental_data_coverage()
    return {
        "ok": True,
        "test_only": True,
        "storage": str(LOCAL_DIR),
        "summary": opportunity_summary(),
        "data_coverage": audit,
        "config": load_config(),
        "opportunities": list_opportunities(),
        "vacancy_safety_rule": "expected lease end approaching → FOLLOW_UP_RECOMMENDED; never AVAILABLE",
    }
