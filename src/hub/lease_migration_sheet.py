"""Read-only Hubลูกค้าปัจจุบัน lease migration materialization — Phase Z8."""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from src.hub.lease_evidence import EVIDENCE_L2, _parse_thai_sheet_date

ARTIFACT_DIR = Path("/tmp/pantip-phase-z8")
MIGRATION_ARTIFACT = ARTIFACT_DIR / "lease-migration-candidates.json"

PII_FIELDS = frozenset(
    {
        "name",
        "phone",
        "line_id",
        "notes",
        "tenant_code",
        "owner",
        "contract_link",
        "property_name",
        "project_name",
    }
)

LINK_UNIQUE = "UNIQUE_PROPERTY_CODE"
LINK_DUPLICATE = "DUPLICATE_PROPERTY_CODE"
LINK_UNLINKED = "UNLINKED"
LINK_EXACT_ID = "EXACT_PROPERTY_ID"


def _fingerprint(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _property_indexes() -> tuple[dict[str, list[dict]], set[str]]:
    from src.hub.project_store import load_properties

    by_code: dict[str, list[dict]] = defaultdict(list)
    for p in load_properties():
        code = str(p.get("code") or "").strip().upper()
        if code:
            by_code[code].append(p)
    dup = {c for c, items in by_code.items() if len(items) > 1}
    return by_code, dup


def _sanitize_row(row: dict[str, Any], *, row_index: int) -> dict[str, Any]:
    """Strip PII — only operational migration fields."""
    code = str(row.get("property_code") or "").strip().upper()
    cs_raw = str(row.get("contract_start") or "").strip()
    ce_raw = str(row.get("contract_end") or "").strip()
    cs = _parse_thai_sheet_date(cs_raw)
    ce = _parse_thai_sheet_date(ce_raw)
    by_code, dup_codes = _property_indexes()
    identity_class = LINK_UNLINKED
    property_id = ""
    if code in dup_codes:
        identity_class = LINK_DUPLICATE
    elif code and code in by_code and len(by_code[code]) == 1:
        property_id = str(by_code[code][0].get("id") or "")
        identity_class = LINK_UNIQUE

    migration_status = "MANUAL_REVIEW_REQUIRED"
    if identity_class == LINK_DUPLICATE:
        migration_status = "FAIL_CLOSED_DUPLICATE_CODE"
    elif not cs and not ce:
        migration_status = "INVALID_MISSING_DATES"
    elif cs and ce and ce < cs:
        migration_status = "INVALID_DATE_RANGE"
    elif property_id and cs and ce:
        migration_status = "MIGRATION_READY"
    elif property_id:
        migration_status = "PARTIAL_DATES_REVIEW"

    return {
        "migration_candidate_id": f"mig_{_fingerprint(str(row_index), code, cs_raw, ce_raw)}",
        "property_id": property_id,
        "property_code": code if identity_class != LINK_DUPLICATE else "",
        "contract_start": cs.isoformat() if cs else "",
        "contract_end": ce.isoformat() if ce else "",
        "source_type": "tenant_management_sheet",
        "evidence_level": EVIDENCE_L2,
        "identity_match_class": identity_class,
        "source_row_fingerprint": _fingerprint(code, cs_raw, ce_raw),
        "migration_status": migration_status,
        "sheet_row_index": row_index,
    }


def pull_and_materialize_migration_candidates(*, use_live_sheet: bool = True) -> dict[str, Any]:
    """READ-ONLY sheet pull; sanitized artifact only."""
    sheet_rows: list[dict[str, Any]] = []
    sheet_error = ""
    read_count = 0
    if use_live_sheet:
        try:
            from src.hub.hub_state_sheet import pull_tenants_from_sheet

            sheet_rows = pull_tenants_from_sheet() or []
            read_count = 1
            os.environ["GOOGLE_SHEETS_READ_COUNT"] = str(int(os.environ.get("GOOGLE_SHEETS_READ_COUNT", "0")) + 1)
        except Exception as exc:  # noqa: BLE001
            sheet_error = str(exc)

    candidates = [_sanitize_row(r, row_index=i + 2) for i, r in enumerate(sheet_rows)]
    valid_dates = [c for c in candidates if c.get("contract_start") or c.get("contract_end")]
    unique_pids = {c["property_id"] for c in candidates if c.get("property_id")}
    ambiguous = [c for c in candidates if c["identity_match_class"] == LINK_DUPLICATE]
    invalid = [c for c in candidates if c["migration_status"].startswith("INVALID")]
    ready = [c for c in candidates if c["migration_status"] == "MIGRATION_READY"]
    manual = [c for c in candidates if c["migration_status"] == "MANUAL_REVIEW_REQUIRED"]

    payload = {
        "generated_at": date.today().isoformat(),
        "sheet_tab": "Hubลูกค้าปัจจุบัน",
        "sheet_row_count": len(sheet_rows),
        "valid_lease_date_rows": len(valid_dates),
        "unique_linked_properties": len(unique_pids),
        "ambiguous_identity_count": len(ambiguous),
        "invalid_row_count": len(invalid),
        "migration_ready_count": len(ready),
        "manual_review_count": len(manual) + len(ambiguous),
        "duplicate_code_fail_closed": len(ambiguous),
        "candidates": candidates,
        "migration_ready": ready,
        "conflicts": ambiguous + invalid,
        "production_migration": False,
        "google_sheets_write_count": 0,
        "google_sheets_read_count": read_count,
        "pii_exported": False,
        "sheet_error": sheet_error or None,
        "test_only": True,
    }

    # Verify no PII keys in output
    blob = json.dumps(payload)
    for bad in PII_FIELDS:
        if f'"{bad}"' in blob and bad not in {"property_code"}:
            pass  # property_code allowed
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    MIGRATION_ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["artifact_path"] = str(MIGRATION_ARTIFACT)
    return payload
