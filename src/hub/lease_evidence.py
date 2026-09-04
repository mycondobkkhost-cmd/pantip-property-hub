"""Lease evidence authority, recovery dry-run, and source inventory — Phase Z6."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.hub.project_store import load_properties

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ARTIFACT_DIR = Path("/tmp/pantip-phase-z6")
MAIN_SHEET_CSV = BASE_DIR / "data" / "main_sheet.csv"
TENANTS_PATH = BASE_DIR / "data" / "current_tenants.json"

# Evidence authority levels
EVIDENCE_L1 = "L1_EXPLICIT_CONTRACT_RECORD"
EVIDENCE_L2 = "L2_TENANT_MANAGEMENT_RECORD"
EVIDENCE_L3 = "L3_START_PLUS_EXPLICIT_TERM"
EVIDENCE_L4 = "L4_OWNER_AVAILABILITY_DATE"
EVIDENCE_L5 = "L5_DEAL_DATE_ONLY"
EVIDENCE_L6 = "L6_LEGACY_AMBIGUOUS"

STRONG_LEVELS = frozenset({EVIDENCE_L1, EVIDENCE_L2, EVIDENCE_L3})
AVAILABILITY_ONLY_LEVELS = frozenset({EVIDENCE_L4})

# วันที่ว่าง semantic classes — NEVER auto-map to lease_end
AVAILABLE_SEMANTIC_AVAILABLE = "LITERAL_AVAILABLE_STATUS"
AVAILABLE_SEMANTIC_NOT_AVAILABLE = "LITERAL_NOT_AVAILABLE"
AVAILABLE_SEMANTIC_AVAILABLE_FROM_DATE = "AVAILABLE_FROM_DATE"
AVAILABLE_SEMANTIC_OWNER_EXPECTED = "OWNER_EXPECTED_AVAILABLE_DATE"
AVAILABLE_SEMANTIC_LEGACY_AMBIGUOUS = "LEGACY_AMBIGUOUS_DATE"
AVAILABLE_SEMANTIC_EMPTY = "EMPTY"

ESTIMATED_12M_DISCLAIMER_TH = "คาดการณ์จากรอบเช่าเดิม ยังไม่ได้ยืนยันจากเจ้าของ"

LINK_EXACT_PROPERTY_ID = "EXACT_PROPERTY_ID"
LINK_UNIQUE_PROPERTY_CODE = "UNIQUE_PROPERTY_CODE_REVIEWABLE"
LINK_DUPLICATE_CODE = "DUPLICATE_PROPERTY_CODE_AMBIGUOUS"
LINK_COMPOSITE = "COMPOSITE_EVIDENCE_REVIEWABLE"
LINK_UNLINKED = "UNLINKED"

_DATE_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), "iso"),
    (re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$"), "dmy"),
    (re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$", re.I), "mon_year"),
    (re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$", re.I), "mon_only"),
]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _fingerprint(*parts: str) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _parse_thai_sheet_date(raw: str) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except ValueError:
            return None
    return None


def classify_available_raw(raw: str) -> dict[str, Any]:
    """Classify วันที่ว่าง — MUST NOT auto-map to lease_end."""
    s = (raw or "").strip()
    if not s:
        return {"semantic": AVAILABLE_SEMANTIC_EMPTY, "may_map_to_lease_end": False}
    low = s.lower()
    if low == "available":
        return {
            "semantic": AVAILABLE_SEMANTIC_AVAILABLE,
            "may_map_to_lease_end": False,
            "meaning_th": "สถานะว่าง (ไม่ใช่วันสิ้นสัญญา)",
        }
    if low in {"not available", "notavailable", "unavailable", "ไม่ว่าง"}:
        return {
            "semantic": AVAILABLE_SEMANTIC_NOT_AVAILABLE,
            "may_map_to_lease_end": False,
            "meaning_th": "สถานะไม่ว่าง",
        }
    parsed = _parse_thai_sheet_date(s)
    if parsed:
        return {
            "semantic": AVAILABLE_SEMANTIC_AVAILABLE_FROM_DATE,
            "parsed_date": parsed.isoformat(),
            "may_map_to_lease_end": False,
            "meaning_th": "วันที่คาดว่าจะว่าง/พร้อมให้เช่า — ไม่ใช่ lease_end",
            "followup_type": "AVAILABLE_DATE_CONFIRMATION_DUE",
        }
    if re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", s, re.I):
        return {
            "semantic": AVAILABLE_SEMANTIC_OWNER_EXPECTED,
            "may_map_to_lease_end": False,
            "meaning_th": "เดือนที่คาดว่าจะว่าง — ต้องยืนยันกับเจ้าของ",
            "followup_type": "AVAILABLE_DATE_CONFIRMATION_DUE",
        }
    return {
        "semantic": AVAILABLE_SEMANTIC_LEGACY_AMBIGUOUS,
        "may_map_to_lease_end": False,
        "meaning_th": "ข้อมูลวันที่ไม่ชัดเจน",
    }


def build_source_inventory() -> list[dict[str, Any]]:
    """Complete lease/tenant source inventory (no PII)."""
    inv: list[dict[str, Any]] = [
        {
            "source_name": "properties.json",
            "source_type": "local_catalog",
            "location": "data/properties.json",
            "row_count": len(load_properties()),
            "available_fields": ["last_listed_at (acquisition only, not lease)"],
            "authority": "display_catalog",
            "identity_linkage": "property_id, property_code",
            "freshness": "sheet sync",
            "pii_risk": "owner_facebook in some rows",
        },
        {
            "source_name": "current_tenants.json",
            "source_type": "local_crm",
            "location": "data/current_tenants.json",
            "row_count": 0 if not TENANTS_PATH.exists() else len(json.loads(TENANTS_PATH.read_text()).get("items", [])),
            "available_fields": ["contract_start", "contract_end", "property_code", "status"],
            "authority": EVIDENCE_L2,
            "identity_linkage": "property_code → property_id",
            "freshness": "sheet pull when synced",
            "pii_risk": "high (tenant names/phones) — excluded from recovery artifact",
        },
        {
            "source_name": "Hubลูกค้าปัจจุบัน",
            "source_type": "google_sheet_tab",
            "location": "SOURCE_GOOGLE_SHEETS_ID / Hubลูกค้าปัจจุบัน",
            "available_fields": ["วันเริ่มสัญญา", "วันสิ้นสุดสัญญา", "รหัสทรัพย์"],
            "authority": EVIDENCE_L2,
            "identity_linkage": "property_code",
            "pii_risk": "high — read aggregate only",
        },
        {
            "source_name": "main_sheet.csv",
            "source_type": "sheet_export",
            "location": "data/main_sheet.csv",
            "available_fields": ["วันที่รับเข้า", "วันที่ว่าง", "รหัสทรัพย์"],
            "authority": "mixed",
            "identity_linkage": "property_code",
            "notes": "วันที่ว่าง is availability semantics, NOT contract_end",
            "pii_risk": "low in aggregate",
        },
        {
            "source_name": "customer_cases.json",
            "source_type": "local_crm",
            "location": "data/customer_cases.json",
            "available_fields": ["contract_started status", "contact dates"],
            "authority": EVIDENCE_L5,
            "identity_linkage": "property codes in case fields",
            "pii_risk": "high",
        },
    ]
    return inv


def _property_indexes() -> tuple[dict[str, dict], dict[str, list[dict]], set[str]]:
    props = load_properties()
    by_id: dict[str, dict] = {}
    by_code: dict[str, list[dict]] = defaultdict(list)
    for p in props:
        pid = str(p.get("id") or "")
        if pid:
            by_id[pid] = p
        code = str(p.get("code") or "").strip().upper()
        if code:
            by_code[code].append(p)
    dup_codes = {c for c, items in by_code.items() if len(items) > 1}
    return by_id, by_code, dup_codes


def classify_property_linkage(*, property_id: str = "", property_code: str = "") -> dict[str, str]:
    by_id, by_code, dup_codes = _property_indexes()
    if property_id and property_id in by_id:
        return {"linkage_class": LINK_EXACT_PROPERTY_ID, "property_id": property_id}
    code = (property_code or "").strip().upper()
    if not code:
        return {"linkage_class": LINK_UNLINKED}
    if code in dup_codes:
        return {"linkage_class": LINK_DUPLICATE_CODE, "property_code": code}
    items = by_code.get(code) or []
    if len(items) == 1:
        return {
            "linkage_class": LINK_UNIQUE_PROPERTY_CODE,
            "property_id": str(items[0].get("id") or ""),
            "property_code": code,
        }
    return {"linkage_class": LINK_UNLINKED, "property_code": code}


def _load_tenant_sources() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if TENANTS_PATH.exists():
        try:
            data = json.loads(TENANTS_PATH.read_text(encoding="utf-8"))
            rows.extend(data.get("items") or [])
        except json.JSONDecodeError:
            pass
    try:
        from src.hub.hub_state_sheet import pull_tenants_from_sheet

        sheet_rows = pull_tenants_from_sheet()
        seen = {(r.get("id") or "", r.get("tenant_code") or "") for r in rows}
        for r in sheet_rows or []:
            key = (r.get("id") or "", r.get("tenant_code") or "")
            if key not in seen:
                rows.append(r)
    except Exception:
        pass
    return rows


def _is_rental_row(rent: str, sale: str) -> bool:
    return bool((rent or "").strip()) and not bool((sale or "").strip())


def audit_main_sheet_available_semantics() -> dict[str, Any]:
    if not MAIN_SHEET_CSV.is_file():
        return {"available": False, "reason": "main_sheet.csv not found"}
    with MAIN_SHEET_CSV.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))
    headers = rows[0]
    idx = {h.strip(): i for i, h in enumerate(headers)}
    sem_counter: Counter[str] = Counter()
    rental_total = 0
    for r in rows[1:]:
        rent = r[idx.get("ราคาเช่า", -1)] if idx.get("ราคาเช่า") is not None else ""
        sale = r[idx.get("ราคาขาย", -1)] if idx.get("ราคาขาย") is not None else ""
        if not _is_rental_row(rent, sale):
            continue
        rental_total += 1
        av = r[idx["วันที่ว่าง"]] if "วันที่ว่าง" in idx and idx["วันที่ว่าง"] < len(r) else ""
        sem_counter[classify_available_raw(av)["semantic"]] += 1
    return {
        "rental_rows": rental_total,
        "semantic_counts": dict(sem_counter),
        "conclusion": "วันที่ว่าง is availability/vacancy semantics — NOT lease_end",
        "may_map_to_lease_end": False,
    }


def build_recovery_dry_run(*, skip_live_sheet: bool = False) -> dict[str, Any]:
    """Sanitized lease evidence recovery — no PII, no production writes."""
    by_id, by_code, dup_codes = _property_indexes()
    rentals = [p for p in load_properties() if (p.get("rent_price") or "").strip()]
    rental_ids = {str(p.get("id")) for p in rentals}
    code_to_pid: dict[str, str] = {}
    for code, items in by_code.items():
        if len(items) == 1:
            code_to_pid[code] = str(items[0].get("id") or "")

    categories: Counter[str] = Counter()
    records: list[dict[str, Any]] = []
    seen_property_cycle: set[str] = set()
    covered: set[str] = set()

    def link_pid(code: str) -> tuple[str, str]:
        code = (code or "").strip().upper()
        if not code:
            return "", LINK_UNLINKED
        if code in dup_codes:
            return "", LINK_DUPLICATE_CODE
        pid = code_to_pid.get(code, "")
        if pid:
            return pid, LINK_UNIQUE_PROPERTY_CODE
        return "", LINK_UNLINKED

    tenant_rows: list[dict[str, Any]] = []
    if TENANTS_PATH.exists():
        try:
            tenant_rows.extend(json.loads(TENANTS_PATH.read_text(encoding="utf-8")).get("items") or [])
        except json.JSONDecodeError:
            pass
    if not skip_live_sheet:
        try:
            from src.hub.hub_state_sheet import pull_tenants_from_sheet

            seen = {(r.get("id") or "", r.get("tenant_code") or "") for r in tenant_rows}
            for r in pull_tenants_from_sheet() or []:
                key = (r.get("id") or "", r.get("tenant_code") or "")
                if key not in seen:
                    tenant_rows.append(r)
        except Exception:
            pass

    for t in tenant_rows:
        pid, lclass = link_pid(str(t.get("property_code") or ""))
        if lclass == LINK_DUPLICATE_CODE:
            categories["IDENTITY_AMBIGUOUS"] += 1
            continue
        if not pid or pid not in rental_ids:
            continue
        cs = _parse_thai_sheet_date(str(t.get("contract_start") or ""))
        ce = _parse_thai_sheet_date(str(t.get("contract_end") or ""))
        if ce:
            key = f"{pid}::tenant"
            if key in seen_property_cycle:
                continue
            seen_property_cycle.add(key)
            covered.add(pid)
            categories["STRONG_EXPLICIT_LEASE_END"] += 1
            records.append(
                {
                    "property_id": pid,
                    "linkage_class": lclass,
                    "evidence_level": EVIDENCE_L2,
                    "lease_start_date": cs.isoformat() if cs else None,
                    "lease_end_date": ce.isoformat(),
                    "available_from_date": None,
                    "source_type": "tenant_management",
                    "source_fingerprint": _fingerprint("tenant", pid, str(ce)),
                    "confidence": "HIGH",
                    "review_status": "ACCEPTED_STRONG",
                }
            )
        elif cs:
            categories["AMBIGUOUS_DATE"] += 1

    if MAIN_SHEET_CSV.is_file():
        with MAIN_SHEET_CSV.open(encoding="utf-8") as f:
            sheet_rows = list(csv.reader(f))
        headers = sheet_rows[0]
        idx = {h.strip(): i for i, h in enumerate(headers)}
        for r in sheet_rows[1:]:
            rent = r[idx.get("ราคาเช่า", 0)] if idx.get("ราคาเช่า") is not None else ""
            if not (rent or "").strip():
                continue
            code = (r[idx.get("รหัสทรัพย์", 0)] if idx.get("รหัสทรัพย์") is not None else "").strip().upper()
            av = r[idx["วันที่ว่าง"]] if "วันที่ว่าง" in idx and idx["วันที่ว่าง"] < len(r) else ""
            sem = classify_available_raw(av)
            pid, lclass = link_pid(code)
            if lclass == LINK_DUPLICATE_CODE and sem["semantic"] == AVAILABLE_SEMANTIC_AVAILABLE_FROM_DATE:
                categories["IDENTITY_AMBIGUOUS"] += 1
                continue
            if not pid or pid not in rental_ids or pid in covered:
                continue
            if sem["semantic"] == AVAILABLE_SEMANTIC_AVAILABLE_FROM_DATE:
                covered.add(pid)
                categories["AVAILABLE_FROM_ONLY"] += 1
                records.append(
                    {
                        "property_id": pid,
                        "linkage_class": lclass,
                        "evidence_level": EVIDENCE_L4,
                        "lease_start_date": None,
                        "lease_end_date": None,
                        "available_from_date": sem.get("parsed_date"),
                        "source_type": "main_sheet_available_raw",
                        "source_fingerprint": _fingerprint("avail", pid, sem.get("parsed_date") or av),
                        "confidence": "MEDIUM",
                        "review_status": "AVAILABILITY_DATE_ONLY",
                    }
                )
            elif sem["semantic"] in {AVAILABLE_SEMANTIC_LEGACY_AMBIGUOUS, AVAILABLE_SEMANTIC_OWNER_EXPECTED}:
                categories["AMBIGUOUS_DATE"] += 1

    for p in rentals:
        pid = str(p.get("id") or "")
        if pid not in covered:
            categories["NO_EVIDENCE"] += 1

    total = len(rentals)
    high_conf = categories["STRONG_EXPLICIT_LEASE_END"] + categories.get("STRONG_START_PLUS_TERM", 0)
    avail_follow = categories["AVAILABLE_FROM_ONLY"]

    return {
        "generated_at": _now(),
        "audited_rental_population": total,
        "categories": dict(categories),
        "HIGH_CONFIDENCE_FOLLOWUP": high_conf,
        "AVAILABILITY_DATE_FOLLOWUP": avail_follow,
        "ESTIMATED_12M_CANDIDATE": categories.get("DEAL_DATE_ONLY", 0),
        "INSUFFICIENT_DATA": categories["NO_EVIDENCE"],
        "duplicate_property_code_count": len(dup_codes),
        "records": records,
        "available_date_semantics": audit_main_sheet_available_semantics(),
        "historical_data_recovery": "PARTIAL" if high_conf > 0 else "POOR",
        "tenant_source_rows": len(tenant_rows),
    }


def classify_lease_evidence_authority(
    *,
    contract_end: str | None = None,
    contract_start: str | None = None,
    term_months: int | None = None,
    available_from: str | None = None,
    deal_date: str | None = None,
    source_type: str = "",
) -> dict[str, Any]:
    ce = _parse_thai_sheet_date(contract_end)
    cs = _parse_thai_sheet_date(contract_start)
    af = _parse_thai_sheet_date(available_from)
    dd = _parse_thai_sheet_date(deal_date)

    if ce and source_type in {"tenant_management", "lease_record"}:
        return {"evidence_level": EVIDENCE_L2, "lease_end_date": ce.isoformat(), "strong": True}
    if ce:
        return {"evidence_level": EVIDENCE_L1, "lease_end_date": ce.isoformat(), "strong": True}
    if cs and term_months and term_months > 0:
        end = cs + timedelta(days=int(term_months * 30.437))
        return {
            "evidence_level": EVIDENCE_L3,
            "lease_start_date": cs.isoformat(),
            "lease_end_date": end.isoformat(),
            "strong": True,
        }
    if cs and not term_months:
        return {"evidence_level": EVIDENCE_L6, "strong": False, "note": "start only — no invented term"}
    if af:
        return {
            "evidence_level": EVIDENCE_L4,
            "available_from_date": af.isoformat(),
            "strong": False,
            "followup_type": "AVAILABLE_DATE_CONFIRMATION_DUE",
        }
    if dd:
        return {
            "evidence_level": EVIDENCE_L5,
            "strong": False,
            "disclaimer_th": ESTIMATED_12M_DISCLAIMER_TH,
            "note": "deal date only — never confirmed lease end",
        }
    return {"evidence_level": EVIDENCE_L6, "strong": False}


def write_recovery_artifact() -> str:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_recovery_dry_run()
    path = ARTIFACT_DIR / "lease-evidence-recovery.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
