"""CONTRACT_STARTED → future lease capture hook — Phase Z7 (TEST_ONLY local)."""

from __future__ import annotations

from typing import Any

from src.hub.lease_record import CAPTURE_STAGE_RECOMMENDED, create_lease_record, list_lease_records
from src.hub.project_store import load_properties

CONTRACT_STARTED_STATUS = "contract_started"


def _resolve_property_id_from_codes(codes: list[str]) -> tuple[str, str]:
    """Map reserved/viewing property codes to property_id (fail closed on duplicates)."""
    from collections import defaultdict

    props = load_properties()
    by_code: dict[str, list[dict]] = defaultdict(list)
    for p in props:
        code = str(p.get("code") or "").strip().upper()
        if code:
            by_code[code].append(p)
    for raw in codes:
        code = str(raw or "").strip().upper()
        if not code:
            continue
        matches = by_code.get(code) or []
        if len(matches) == 1:
            return str(matches[0].get("id") or ""), "UNIQUE_PROPERTY_CODE"
        if len(matches) > 1:
            return "", "DUPLICATE_PROPERTY_CODE"
    return "", "UNLINKED"


def on_customer_status_changed(
    *,
    case_id: str,
    old_status: str,
    new_status: str,
    reserved_codes: list[str] | None = None,
    contract_start: str = "",
    contract_end: str = "",
    lease_term_months: int = 0,
    deal_id: str = "",
) -> dict[str, Any]:
    """When customer case reaches CONTRACT_STARTED, require lease capture (local TEST_ONLY)."""
    if new_status != CONTRACT_STARTED_STATUS:
        return {"action": "none", "reason": "status_not_contract_started"}
    if old_status == CONTRACT_STARTED_STATUS:
        return {"action": "none", "reason": "already_contract_started"}

    property_id, link_class = _resolve_property_id_from_codes(list(reserved_codes or []))
    if not property_id:
        return {
            "action": "LEASE_DATA_COMPLETION_REQUIRED",
            "case_id": case_id,
            "property_id": "",
            "linkage_class": link_class,
            "capture_stage": CAPTURE_STAGE_RECOMMENDED,
            "test_only": True,
        }

    existing = [r for r in list_lease_records(property_id=property_id) if r.get("deal_id") == case_id]
    if existing:
        return {"action": "existing", "lease_record_id": existing[0].get("lease_record_id"), "test_only": True}

    if not contract_start and not contract_end and not lease_term_months:
        return {
            "action": "LEASE_DATA_COMPLETION_REQUIRED",
            "case_id": case_id,
            "property_id": property_id,
            "linkage_class": link_class,
            "capture_stage": CAPTURE_STAGE_RECOMMENDED,
            "notification_event": "LEASE_DATA_COMPLETION_REQUIRED",
            "test_only": True,
        }

    rec = create_lease_record(
        property_id=property_id,
        deal_id=case_id,
        contract_start=contract_start,
        contract_end=contract_end,
        lease_term_months=lease_term_months,
        source_type="customer_workflow_contract_started",
    )
    return {
        "action": "lease_record_created",
        "lease_record_id": rec.get("lease_record_id"),
        "lease_status": rec.get("lease_status"),
        "property_id": property_id,
        "capture_stage": CAPTURE_STAGE_RECOMMENDED,
        "test_only": True,
    }


def build_migration_dry_run(*, skip_live_sheet: bool = True) -> dict[str, Any]:
    """Controlled 7-record L2 tenant migration candidate — dry-run only."""
    from src.hub.lease_evidence import (
        EVIDENCE_L2,
        LINK_DUPLICATE_CODE,
        _property_indexes,
        _parse_thai_sheet_date,
        build_recovery_dry_run,
    )

    recovery = build_recovery_dry_run(skip_live_sheet=skip_live_sheet)
    strong = [
        r
        for r in recovery.get("records") or []
        if r.get("evidence_level") == EVIDENCE_L2 and r.get("lease_end_date")
    ]
    _, _, dup_codes = _property_indexes()
    candidates = []
    conflicts = []
    seen_pid: set[str] = set()
    for row in strong:
        pid = row.get("property_id") or ""
        if pid in seen_pid:
            conflicts.append({"property_id": pid, "reason": "duplicate_property_linkage"})
            continue
        seen_pid.add(pid)
        if row.get("linkage_class") == LINK_DUPLICATE_CODE:
            conflicts.append({"property_id": pid, "reason": "duplicate_property_code"})
            continue
        candidates.append(
            {
                "property_id": pid,
                "contract_start": row.get("lease_start_date") or "",
                "contract_end": row.get("lease_end_date") or "",
                "evidence_level": EVIDENCE_L2,
                "source_type": row.get("source_type") or "tenant_management",
                "migration_status": "DRY_RUN_CANDIDATE",
            }
        )
    return {
        "candidate_count": len(candidates),
        "conflict_count": len(conflicts),
        "candidates": candidates,
        "conflicts": conflicts,
        "production_migration": False,
        "test_only": True,
    }
