"""Trust-column mapping for「ชีตสำหรับทำงาน」link fields.

Agreed rules (do NOT horizontally reclassify URLs):
  ลิ้งค์โพส / ลิ้งค์โพส Pages  → copy as-is (trust 100%)
  ลิ้งค์ต้นโพสต์ (col Q)       → ต้นทาง as-is (trust 100%)
  เฟสเจ้าของ                   → prefer existing; only if empty use blank
                                sub-column beside ต้นโพสต์ (col R)
  หมายเหตุ                     → copy as-is

Never move a Facebook post out of Q into ลิ้งค์โพส.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.hub.owner_facebook import (
    adjacent_column_index,
    cell_has_value,
    owner_column_index,
    source_column_index,
)
from src.hub.sheet_links import link_col_indexes, unwrap_link_cell


@dataclass
class TrustMappedRow:
    code: str
    source: str = ""
    owner: str = ""
    post: str = ""
    pages: str = ""
    notes: str = ""
    adjacent: str = ""
    owner_action: str = "empty"  # already_owner | from_adjacent | empty
    clear_adjacent: bool = False


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return unwrap_link_cell(row[idx] or "")


def notes_column_index(headers: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if (h or "").strip() == "หมายเหตุ":
            return i
    return None


def trust_map_row(headers: list[str], row: list[str]) -> TrustMappedRow:
    """Map one sheet row using trusted columns (no URL-kind reshuffle)."""
    code = (row[0] if row else "").upper().replace(" ", "").strip()
    cols = link_col_indexes(headers)
    adj_i = adjacent_column_index(headers)
    notes_i = notes_column_index(headers)

    post = _cell(row, cols.get("post"))
    pages = _cell(row, cols.get("pages"))
    source = _cell(row, cols.get("source"))
    owner = _cell(row, cols.get("owner"))
    adjacent = _cell(row, adj_i)
    notes = _cell(row, notes_i) if notes_i is not None else ""
    # notes may be plain text (not a URL) — prefer raw strip when unwrap emptied it
    if notes_i is not None and notes_i < len(row) and not notes:
        raw = str(row[notes_i] or "").strip()
        if raw and not raw.lower().startswith("http"):
            notes = raw

    result = TrustMappedRow(
        code=code,
        source=source,
        post=post,
        pages=pages,
        notes=notes,
        adjacent=adjacent,
    )

    if cell_has_value(owner):
        result.owner = owner
        result.owner_action = "already_owner"
        # Still clear adjacent dump on NEW after reorganization
        result.clear_adjacent = bool(cell_has_value(adjacent))
        return result

    if cell_has_value(adjacent):
        result.owner = adjacent
        result.owner_action = "from_adjacent"
        result.clear_adjacent = True
        result.adjacent = ""
        return result

    result.owner_action = "empty"
    return result


def apply_trust_map_to_row(
    headers: list[str],
    row: list[str],
    *,
    mapped: TrustMappedRow | None = None,
) -> list[str]:
    """Return a copy of ``row`` with owner/source/post/pages/notes + cleared R."""
    mapped = mapped or trust_map_row(headers, row)
    out = list(row)
    cols = link_col_indexes(headers)
    adj_i = adjacent_column_index(headers)
    notes_i = notes_column_index(headers)
    width = max(len(headers), len(out))
    while len(out) < width:
        out.append("")

    def _set(idx: int | None, val: str) -> None:
        if idx is None:
            return
        while len(out) <= idx:
            out.append("")
        out[idx] = val or ""

    _set(cols.get("post"), mapped.post)
    _set(cols.get("pages"), mapped.pages)
    _set(cols.get("source"), mapped.source)
    _set(cols.get("owner"), mapped.owner)
    if notes_i is not None:
        _set(notes_i, mapped.notes)
    if adj_i is not None and mapped.clear_adjacent:
        _set(adj_i, "")
    elif adj_i is not None:
        # Always clear dump col on NEW after reorg when we moved or left owner in S
        _set(adj_i, "")

    # Ensure owner header column exists physically even if trailing empties
    own_i = owner_column_index(headers)
    if own_i is not None:
        while len(out) <= own_i:
            out.append("")
        if mapped.owner:
            out[own_i] = mapped.owner

    src_i = source_column_index(headers)
    if src_i is not None and mapped.source:
        while len(out) <= src_i:
            out.append("")
        out[src_i] = mapped.source

    return out
