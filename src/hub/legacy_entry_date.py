"""Legacy Pantip data-entry date semantics — Phase Z7."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from src.hub.project_store import load_properties

# Canonical operational concept; persisted field remains properties.last_listed_at
LEGACY_RECORD_ENTERED_AT_FIELD = "last_listed_at"
LEGACY_RECORD_ENTERED_AT_SOURCE = "วันที่รับเข้า (sheet acquired_raw → build_master last_listed_at)"

AGE_BANDS = [
    ("<=30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("91-180", 91, 180),
    ("181-270", 181, 270),
    ("271-365", 271, 365),
    (">365", 366, 99999),
]

RECHECK_THRESHOLD_CANDIDATES = [90, 180, 270, 365]


def parse_legacy_record_entered_at(raw: str | None) -> date | None:
    """Parse properties.last_listed_at (DD/MM/YYYY from sheet วันที่รับเข้า)."""
    s = (raw or "").strip()
    if not s:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
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


def record_age_days(entered_at: date | None, *, today: date | None = None) -> int | None:
    if not entered_at:
        return None
    today = today or date.today()
    return max(0, (today - entered_at).days)


def age_band(age_days: int | None) -> str:
    if age_days is None:
        return "missing_invalid"
    for label, lo, hi in AGE_BANDS:
        if lo <= age_days <= hi:
            return label
    return "missing_invalid"


def _listing_kind(prop: dict[str, Any]) -> str:
    rent = bool((prop.get("rent_price") or "").strip())
    sale = bool((prop.get("sale_price") or "").strip())
    if rent and not sale:
        return "rent"
    if sale and not rent:
        return "sale"
    if rent and sale:
        return "both"
    return "other"


def audit_age_distribution(*, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    props = load_properties()
    band_counts: dict[str, int] = {b[0]: 0 for b in AGE_BANDS}
    band_counts["missing_invalid"] = 0
    rent_bands: dict[str, int] = {b[0]: 0 for b in AGE_BANDS}
    sale_bands: dict[str, int] = {b[0]: 0 for b in AGE_BANDS}
    rent_bands["missing_invalid"] = 0
    sale_bands["missing_invalid"] = 0
    valid = 0
    threshold_counts = {t: 0 for t in RECHECK_THRESHOLD_CANDIDATES}

    for p in props:
        entered = parse_legacy_record_entered_at(p.get(LEGACY_RECORD_ENTERED_AT_FIELD))
        age = record_age_days(entered, today=today)
        b = age_band(age)
        band_counts[b] = band_counts.get(b, 0) + 1
        kind = _listing_kind(p)
        if kind == "rent":
            rent_bands[b] = rent_bands.get(b, 0) + 1
        elif kind == "sale":
            sale_bands[b] = sale_bands.get(b, 0) + 1
        if entered:
            valid += 1
            if age is not None:
                for t in RECHECK_THRESHOLD_CANDIDATES:
                    if age >= t:
                        threshold_counts[t] += 1

    return {
        "field": LEGACY_RECORD_ENTERED_AT_FIELD,
        "source_semantics": LEGACY_RECORD_ENTERED_AT_SOURCE,
        "total_properties": len(props),
        "valid_entry_date_count": valid,
        "missing_invalid_count": len(props) - valid,
        "bands": band_counts,
        "rent_bands": rent_bands,
        "sale_bands": sale_bands,
        "recheck_workload_by_threshold": threshold_counts,
        "note": "Age from data-entry date only; NOT lease end or vacancy",
    }


def entry_date_semantics_proof() -> dict[str, Any]:
    return {
        "canonical_concept": "legacy_record_entered_at",
        "persisted_field": LEGACY_RECORD_ENTERED_AT_FIELD,
        "sheet_column": "วันที่รับเข้า",
        "build_master_mapping": "acquired_raw → parse_date → last_listed_at (DD/MM/YYYY)",
        "not_lease_end": True,
        "not_vacancy_date": True,
        "legacy_wang_date": "วันที่ว่าง preserved as LEGACY_RAW_EVIDENCE only in Z7",
    }
