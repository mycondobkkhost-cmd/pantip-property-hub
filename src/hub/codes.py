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
    return {h.strip(): i for i, h in enumerate(header_row) if h is not None}


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


def max_code_number_from_properties(properties: list[dict]) -> int:
    """Max number from app properties that are real listings."""
    max_n = 0
    for p in properties or []:
        if not prop_is_filled_listing(p):
            continue
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
    with path.open(encoding="utf-8") as f:
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
    """Next shared number after max filled PTP/RXT/COA across app + sheet CSVs."""
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
    return format_code(prefix, next_sequence_number(properties, main_csv=main_csv, hub_csv=hub_csv))


def is_hub_owned(prop: dict) -> bool:
    """True for listings created/managed in Hub (not rebuilt from main sheet)."""
    if (prop.get("data_source") or "").lower() == "hub":
        return True
    prefix = (prop.get("code_prefix") or "").upper()
    if prefix in {"RXT", "COA"}:
        return True
    code = (prop.get("code") or "").upper()
    return code.startswith("RXT") or code.startswith("COA")
