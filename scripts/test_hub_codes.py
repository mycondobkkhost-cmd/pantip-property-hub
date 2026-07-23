#!/usr/bin/env python3
"""Regression checks for Hub property code auto-increment (RXT/COA)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.hub.codes import (
    existing_property_codes,
    format_code,
    max_code_number_from_csv,
    max_code_number_from_properties,
    next_hub_code,
)


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_second_rxt_advances_after_first() -> None:
    props = [
        {"code": "PTP8211", "project_name": "A", "project_id": "1"},
    ]
    first = next_hub_code(props, prefix="RXT")
    _assert(first == "RXT8212", f"expected RXT8212, got {first}")

    props2 = [
        {"code": first, "code_prefix": "RXT", "project_name": "B", "project_id": "2"},
        *props,
    ]
    second = next_hub_code(props2, prefix="RXT")
    _assert(second == "RXT8213", f"expected RXT8213 after save, got {second}")
    _assert(second != first, "second suggestion must not reuse first code")


def test_counts_reserved_code_even_without_project() -> None:
    """App-reserved codes must advance the counter (root cause of stuck RXT)."""
    props = [
        {"code": "PTP8211", "project_name": "A", "project_id": "1"},
        {"code": "RXT8212", "project_name": "", "project_id": ""},
    ]
    _assert(max_code_number_from_properties(props) == 8212, "must count reserved RXT8212")
    nxt = next_hub_code(props, prefix="RXT")
    _assert(nxt == "RXT8213", f"expected RXT8213, got {nxt}")


def test_skips_collision_if_max_stale() -> None:
    props = [
        {"code": "RXT8212", "project_name": "X", "project_id": "x"},
        {"code": "RXT8213", "project_name": "Y", "project_id": "y"},
    ]
    # Even if sequence math were wrong, allocator must not return an existing code
    taken = existing_property_codes(props)
    code = next_hub_code(props, prefix="RXT")
    _assert(code not in taken, f"{code} already taken")
    _assert(code == "RXT8214", f"expected RXT8214, got {code}")


def test_coa_uses_same_sequence_different_prefix() -> None:
    props = [{"code": "PTP8211", "project_name": "A", "project_id": "1"}]
    _assert(next_hub_code(props, prefix="COA") == "COA8212", "COA shares numeric sequence")
    props2 = props + [{"code": "COA8212", "project_name": "B", "project_id": "2"}]
    _assert(next_hub_code(props2, prefix="RXT") == "RXT8213", "RXT advances after COA")


def test_csv_ignores_empty_preallocated_but_hub_bom_ok() -> None:
    td = Path(tempfile.mkdtemp())
    main = td / "main.csv"
    main.write_text(
        "รหัสทรัพย์,โครงการ\nPTP8211,Filled\nPTP9999,\n",
        encoding="utf-8",
    )
    _assert(max_code_number_from_csv(main) == 8211, "empty pre-alloc PTP9999 ignored")

    hub = td / "hub.csv"
    # utf-8-sig BOM like sheet_write export
    hub.write_text(
        "รหัสทรัพย์,วันที่รับเข้า,โครงการ\nRXT8212,1/1/2026,Hub Project\n",
        encoding="utf-8-sig",
    )
    _assert(max_code_number_from_csv(hub) == 8212, "BOM hub export must count RXT")


def test_format_code() -> None:
    _assert(format_code("rxt", 12) == "RXT0012", "zero-pad + upper")


if __name__ == "__main__":
    test_second_rxt_advances_after_first()
    test_counts_reserved_code_even_without_project()
    test_skips_collision_if_max_stale()
    test_coa_uses_same_sequence_different_prefix()
    test_csv_ignores_empty_preallocated_but_hub_bom_ok()
    test_format_code()
    print("ok — hub code increment regressions passed")
