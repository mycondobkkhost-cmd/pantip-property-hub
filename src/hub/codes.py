"""Shared property code numbering — one sequence across PTP / RXT / COA."""

from __future__ import annotations

import csv
import re
from pathlib import Path

CODE_RE = re.compile(r"^(PTP|RXT|COA)(\d+)$", re.I)


def code_number(code: str) -> int | None:
    m = CODE_RE.match((code or "").strip().upper().replace(" ", ""))
    if not m:
        return None
    return int(m.group(2))


def _headers_map(header_row: list[str]) -> dict[str, int]:
    """Map header labels → index. Strip BOM so utf-8-sig exports still match."""
    out: dict[str, int] = {}
    for i, h in enumerate(header_row):
        if h is None:
            continue
        key = str(h).replace("\ufeff", "").strip()
        if key:
            out[key] = i
    return out


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def row_is_filled_listing(row: list[str], cols: dict[str, int]) -> bool:
    """
    แถวที่กรอกจริง = มีชื่อโครงการ (ไม่นับแค่รหัส/วันที่/Available หรือลิงก์ที่แปะเผื่อไว้)
    """
    project = _cell(row, cols.get("โครงการ"))
    return bool(project)


def prop_is_filled_listing(p: dict) -> bool:
    return bool((p.get("project_name") or "").strip() or (p.get("project_id") or "").strip())


def existing_property_codes(properties: list[dict] | None) -> set[str]:
    """All property codes already reserved in the app (any status / fill level)."""
    out: set[str] = set()
    for p in properties or []:
        code = (p.get("code") or "").strip().upper().replace(" ", "")
        if code:
            out.add(code)
    return out


def max_code_number_from_properties(properties: list[dict]) -> int:
    """
    Max numeric part from app properties.

    Counts every reserved code in the app DB (not only “filled” rows). A code that
    already exists must advance the shared counter — otherwise the UI keeps
    suggesting the same RXT/COA after the first save.
    """
    max_n = 0
    for p in properties or []:
        n = code_number(str(p.get("code") or ""))
        if n is not None:
            max_n = max(max_n, n)
    return max_n


def max_code_number_from_csv(path: Path, col_name: str = "รหัสทรัพย์") -> int:
    """
    Max code number from CSV rows with a filled project name.
    Ignores pre-allocated codes (รหัส+วันที่ / ลิงก์ แต่ยังไม่มีโครงการ).
    """
    if not path.exists():
        return 0
    # utf-8-sig strips BOM when present (hub export); plain utf-8 files also work
    with path.open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    cols = _headers_map(rows[0])
    idx = cols.get(col_name, 0)
    max_n = 0
    for row in rows[1:]:
        if not row_is_filled_listing(row, cols):
            continue
        n = code_number(_cell(row, idx))
        if n is not None:
            max_n = max(max_n, n)
    return max_n


def next_sequence_number(
    properties: list[dict] | None = None,
    *,
    main_csv: Path | None = None,
    hub_csv: Path | None = None,
) -> int:
    """Next shared number after max PTP/RXT/COA across app + filled sheet CSVs."""
    max_n = max_code_number_from_properties(properties or [])
    if main_csv is not None:
        max_n = max(max_n, max_code_number_from_csv(main_csv))
    if hub_csv is not None:
        max_n = max(max_n, max_code_number_from_csv(hub_csv))
    return max_n + 1


def format_code(prefix: str, number: int) -> str:
    p = (prefix or "RXT").strip().upper() or "RXT"
    return f"{p}{int(number):04d}"


def next_hub_code(
    properties: list[dict] | None = None,
    *,
    prefix: str = "RXT",
    main_csv: Path | None = None,
    hub_csv: Path | None = None,
) -> str:
    """
    Next free Hub code for prefix (RXT/COA/…).

    Uses the shared numeric sequence, then skips any code string already present
    in properties (defense against stale UI / race / filter edge cases).
    """
    taken = existing_property_codes(properties)
    n = next_sequence_number(properties, main_csv=main_csv, hub_csv=hub_csv)
    # Hard cap avoids infinite loop if data is extremely pathological
    for _ in range(10000):
        code = format_code(prefix, n)
        if code not in taken:
            return code
        n += 1
    return format_code(prefix, n)


def is_hub_owned(prop: dict) -> bool:
    """True for listings created/managed in Hub (not rebuilt from main sheet)."""
    if (prop.get("data_source") or "").lower() == "hub":
        return True
    prefix = (prop.get("code_prefix") or "").upper()
    if prefix in {"RXT", "COA"}:
        return True
    code = (prop.get("code") or "").upper()
    return code.startswith("RXT") or code.startswith("COA")
