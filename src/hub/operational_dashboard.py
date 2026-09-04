"""Unified operator dashboard — งานติดตามทรัพย์ (Phase Z7)."""

from __future__ import annotations

from datetime import date
from typing import Any

from src.hub.legacy_entry_date import audit_age_distribution, entry_date_semantics_proof
from src.hub.lease_capture_integration import build_migration_dry_run
from src.hub.lease_migration_sheet import pull_and_materialize_migration_candidates
from src.hub.lease_record import list_lease_records
from src.hub.listing_freshness import build_api_payload as freshness_payload
from src.hub.listing_freshness import derive_freshness_state
from src.hub.property_status_recheck import build_recheck_dry_run, list_rechecks, summary as recheck_summary
from src.hub.property_status_recheck import load_config as recheck_config
from src.hub.recheck_capacity import (
    active_capacity_summary,
    build_capacity_api_payload,
    build_eligible_backlog,
)


def _lease_end_soon_items(*, within_days: int = 60) -> list[dict[str, Any]]:
    today = date.today()
    out = []
    for rec in list_lease_records():
        end_raw = (rec.get("contract_end") or "")[:10]
        if not end_raw:
            continue
        try:
            end = date.fromisoformat(end_raw)
        except ValueError:
            continue
        days = (end - today).days
        if 0 <= days <= within_days:
            out.append(
                {
                    "lease_record_id": rec.get("lease_record_id"),
                    "property_id": rec.get("property_id"),
                    "contract_end": end_raw,
                    "days_remaining": days,
                    "lease_status": rec.get("lease_status"),
                }
            )
    return sorted(out, key=lambda x: x.get("days_remaining", 999))


def _missing_lease_data() -> list[dict[str, Any]]:
    return [
        {
            "lease_record_id": r.get("lease_record_id"),
            "property_id": r.get("property_id"),
            "lease_status": r.get("lease_status"),
        }
        for r in list_lease_records()
        if r.get("lease_status") == "DATA_COMPLETION_REQUIRED"
    ]


def _verification_due_items() -> list[dict[str, Any]]:
    fresh = freshness_payload()
    due_states = {"VERIFICATION_DUE", "VERIFICATION_OVERDUE", "STALE_UNCONFIRMED"}
    return [
        {
            "listing_id": x.get("listing_id"),
            "property_id": x.get("property_id"),
            "availability_state": derive_freshness_state(x),
            "verification_due_at": x.get("verification_due_at"),
        }
        for x in fresh.get("items") or []
        if derive_freshness_state(x) in due_states
    ]


def _owner_confirmed_future() -> list[dict[str, Any]]:
    return [
        {
            "property_id": x.get("property_id"),
            "property_code_display": x.get("property_code_display"),
            "owner_confirmed_available_from": x.get("owner_confirmed_available_from"),
            "confirmed_at": x.get("confirmed_at"),
            "confirmed_by": x.get("confirmed_by"),
        }
        for x in list_rechecks()
        if x.get("owner_confirmed_available_from")
    ]


def build_dashboard_payload(*, threshold_days: int | None = None) -> dict[str, Any]:
    """Single operational view for operator follow-up work."""
    dry = build_recheck_dry_run(threshold_days=threshold_days)
    rs = recheck_summary()
    cap = active_capacity_summary()
    categories = {
        "today": {
            "label_th": "วันนี้",
            "count": rs.get("due_today", 0),
        },
        "eligible_backlog": {
            "label_th": "Backlog (เข้าเกณฑ์)",
            "count": len(build_eligible_backlog()),
        },
        "active_queue": {
            "label_th": "คิวงาน Active",
            "count": cap.get("active_count", 0),
            "capacity": f"{cap.get('active_count',0)}/{cap.get('max_total_active_rechecks',0)}",
        },
        "batch_remaining_today": {
            "label_th": "ชุดใหม่วันนี้เหลือ",
            "count": cap.get("remaining_today", 0),
        },
        "old_record_recheck": {
            "label_th": "ทรัพย์เก่าควรตรวจสอบ",
            "count": dry.get("candidate_count", 0),
            "threshold_days": dry.get("threshold_days"),
        },
        "listing_verification": {
            "label_th": "ต้องยืนยันสถานะประกาศ",
            "count": len(_verification_due_items()),
        },
        "lease_end_soon": {
            "label_th": "ใกล้หมดสัญญา",
            "count": len(_lease_end_soon_items()),
        },
        "lease_data_incomplete": {
            "label_th": "ข้อมูลสัญญาไม่ครบ",
            "count": len(_missing_lease_data()),
        },
        "waiting_owner": {
            "label_th": "รอเจ้าของตอบ",
            "count": rs.get("waiting_owner", 0),
        },
        "owner_confirmed_available": {
            "label_th": "เจ้าของยืนยันว่าจะว่าง",
            "count": len(_owner_confirmed_future()),
        },
    }
    return {
        "ok": True,
        "test_only": True,
        "title_th": "งานติดตามทรัพย์",
        "legacy_wang_queue_removed": True,
        "entry_date_semantics": entry_date_semantics_proof(),
        "age_distribution": audit_age_distribution(),
        "recheck_dry_run": dry,
        "recheck_config": recheck_config(),
        "capacity": cap,
        "capacity_model": build_capacity_api_payload(),
        "categories": categories,
        "active_queue_rows": build_capacity_api_payload().get("active_queue", [])[:50],
        "recheck_rows": list_rechecks()[:50],
        "verification_items": _verification_due_items()[:30],
        "lease_end_soon": _lease_end_soon_items()[:30],
        "missing_lease_data": _missing_lease_data()[:30],
        "owner_confirmed_future": _owner_confirmed_future()[:30],
        "migration_dry_run_summary": pull_and_materialize_migration_candidates(use_live_sheet=False),
        "operator_actions_test_only": [
            "ติดต่อเจ้าของแล้ว",
            "ยังว่าง",
            "จะว่างวันที่...",
            "ไม่ว่าง",
            "ปล่อยเช่าแล้ว",
            "ขายแล้ว",
            "เจ้าของยังไม่ต้องการทำตลาด",
            "ติดต่อไม่ได้",
            "นัดติดตามใหม่",
            "เพิ่มข้อมูลสัญญา",
        ],
    }
