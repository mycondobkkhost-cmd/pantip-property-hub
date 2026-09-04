"""Future lease record contract — Phase Z6 (TEST_ONLY local storage)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_DIR = BASE_DIR / ".local" / "lease_record_phase_z6"
RECORDS_PATH = LOCAL_DIR / "lease_records.json"

LEASE_STATUSES = frozenset(
    {
        "PENDING_START",
        "ACTIVE",
        "RENEWED",
        "ENDED_CONFIRMED",
        "TERMINATED",
        "STATUS_CONFIRMATION_DUE",
        "UNKNOWN",
        "DATA_COMPLETION_REQUIRED",
    }
)

CAPTURE_STAGE_RECOMMENDED = "CONTRACT_STARTED"  # customer_store pipeline status


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _parse_day(raw: str | None) -> date | None:
    if not raw:
        return None
    s = str(raw).strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def _load_records() -> list[dict[str, Any]]:
    if not RECORDS_PATH.exists():
        return []
    try:
        data = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(data.get("items") or [])


def _save_records(items: list[dict[str, Any]]) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    RECORDS_PATH.write_text(
        json.dumps({"items": items, "updated_at": _now(), "test_only": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item)
    item.setdefault("lease_record_id", "")
    item.setdefault("property_id", "")
    item.setdefault("listing_cycle_id", "")
    item.setdefault("deal_id", "")
    item.setdefault("contract_start", "")
    item.setdefault("contract_end", "")
    item.setdefault("lease_term_months", 0)
    item.setdefault("lease_status", "UNKNOWN")
    item.setdefault("source_type", "operator_entry")
    item.setdefault("evidence_level", "L2_TENANT_MANAGEMENT_RECORD")
    item.setdefault("renewed_from_lease_id", "")
    item.setdefault("test_only", True)
    item.setdefault("created_at", "")
    item.setdefault("updated_at", "")
    return item


def validate_lease_dates(contract_start: str, contract_end: str) -> None:
    cs = _parse_day(contract_start)
    ce = _parse_day(contract_end)
    if contract_start and not cs:
        raise ValueError("invalid contract_start")
    if contract_end and not ce:
        raise ValueError("invalid contract_end")
    if cs and ce and ce < cs:
        raise ValueError("contract_end must be >= contract_start")


def derive_status(item: dict[str, Any]) -> str:
    """Expired contract does NOT auto-mark ENDED_CONFIRMED or AVAILABLE."""
    st = (item.get("lease_status") or "UNKNOWN").strip()
    if st in {"ENDED_CONFIRMED", "TERMINATED", "RENEWED"}:
        return st
    cs = _parse_day(item.get("contract_start"))
    ce = _parse_day(item.get("contract_end"))
    if not cs and not ce:
        return "DATA_COMPLETION_REQUIRED"
    if cs and not ce and not item.get("lease_term_months"):
        return "DATA_COMPLETION_REQUIRED"
    if ce and date.today() > ce:
        return "STATUS_CONFIRMATION_DUE"
    if cs and date.today() >= cs:
        return "ACTIVE"
    if cs:
        return "PENDING_START"
    return "UNKNOWN"


def create_lease_record(**fields: Any) -> dict[str, Any]:
    if not fields.get("property_id"):
        raise ValueError("lease_record requires property_id")
    validate_lease_dates(
        str(fields.get("contract_start") or ""),
        str(fields.get("contract_end") or ""),
    )
    items = _load_records()
    now = _now()
    rec = _normalize(
        {
            **fields,
            "lease_record_id": fields.get("lease_record_id") or f"lr_{uuid.uuid4().hex[:12]}",
            "created_at": now,
            "updated_at": now,
            "test_only": True,
        }
    )
    rec["lease_status"] = derive_status(rec)
    items.append(rec)
    _save_records(items)
    return rec


def renew_lease_record(lease_record_id: str, **new_fields: Any) -> dict[str, Any]:
    """Preserve old record; create new lease_record with RENEWED link."""
    items = _load_records()
    lid = (lease_record_id or "").strip()
    old = None
    old_idx = -1
    for i, it in enumerate(items):
        if it.get("lease_record_id") == lid:
            old = dict(it)
            old_idx = i
            break
    if not old:
        raise ValueError("lease record not found")
    old["lease_status"] = "RENEWED"
    old["updated_at"] = _now()
    items[old_idx] = _normalize(old)

    now = _now()
    new = _normalize(
        {
            "property_id": old["property_id"],
            "listing_cycle_id": new_fields.get("listing_cycle_id") or old.get("listing_cycle_id"),
            "deal_id": new_fields.get("deal_id") or "",
            "contract_start": new_fields.get("contract_start") or "",
            "contract_end": new_fields.get("contract_end") or "",
            "lease_term_months": new_fields.get("lease_term_months") or 0,
            "renewed_from_lease_id": lid,
            "source_type": new_fields.get("source_type") or "renewal",
            "lease_record_id": f"lr_{uuid.uuid4().hex[:12]}",
            "created_at": now,
            "updated_at": now,
            "test_only": True,
        }
    )
    new["lease_status"] = derive_status(new)
    items.append(new)
    _save_records(items)
    return new


def list_lease_records(*, property_id: str = "") -> list[dict[str, Any]]:
    items = [_normalize(x) for x in _load_records()]
    if property_id:
        items = [x for x in items if x.get("property_id") == property_id]
    return items


def build_capture_contract() -> dict[str, Any]:
    return {
        "version": "0.1",
        "capture_stage_recommended": CAPTURE_STAGE_RECOMMENDED,
        "workflow_note": "Enter contract_start/contract_end when customer case reaches เริ่มสัญญา",
        "required_fields_strong": ["property_id", "contract_start", "contract_end"],
        "unknown_allowed": True,
        "missing_data_status": "DATA_COMPLETION_REQUIRED",
        "expired_does_not_mean": ["ENDED_CONFIRMED", "AVAILABLE"],
        "renewal_model": "old record RENEWED + new lease_record",
        "storage": str(LOCAL_DIR),
        "test_only": True,
    }
