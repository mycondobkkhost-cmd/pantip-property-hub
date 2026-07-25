"""Trust-column mapping for「ชีตสำหรับทำงาน」link fields.

Agreed rules (do NOT horizontally reclassify URLs):
  ลิ้งค์โพส / ลิ้งค์โพส Pages  → copy as-is (trust 100%)
  ลิ้งค์ต้นโพสต์ (col Q):
    - URL  → ต้นทาง
    - text → หมายเหตุ (merge; clear Q)
  blank sub-col R beside ต้นโพสต์:
    - URL + เฟสเจ้าของ empty → เฟสเจ้าของ
    - URL + เฟสเจ้าของ set  → keep owner; R URL → หมายเหตุ if not duplicate
    - text → หมายเหตุ
  เฟสเจ้าของ URL stays; non-URL owner text → หมายเหตุ
  หมายเหตุ from OLD always included; merge rescued Q/R/owner text

Never move a Facebook post out of Q into ลิ้งค์โพส.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.hub.owner_facebook import (
    adjacent_column_index,
    cell_has_value,
    owner_column_index,
    source_column_index,
)
from src.hub.sheet_links import link_col_indexes, unwrap_link_cell

NOTES_JOIN = " | "


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
    clear_source_text: bool = False
    text_to_notes: list[str] = field(default_factory=list)


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return unwrap_link_cell(row[idx] or "")


def _raw_cell(row: list[str], idx: int | None) -> str:
    """Plain cell text when unwrap yields empty (notes / non-URL)."""
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    unwrapped = unwrap_link_cell(row[idx] or "")
    if unwrapped:
        return unwrapped
    raw = str(row[idx] or "").strip()
    if raw and not raw.lower().startswith("http"):
        return raw
    return ""


def _is_http(value: str) -> bool:
    s = (value or "").strip()
    return s.startswith("http://") or s.startswith("https://")


def notes_column_index(headers: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if (h or "").strip() == "หมายเหตุ":
            return i
    return None


def merge_notes(*parts: str, sep: str = NOTES_JOIN) -> str:
    """Join note fragments; skip empties / exact duplicates (order-preserving)."""
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        t = (part or "").strip()
        if not t or t in {"-", "—", "–", "."}:
            continue
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return sep.join(out)


def trust_map_row(headers: list[str], row: list[str]) -> TrustMappedRow:
    """Map one sheet row using trusted columns (no URL-kind reshuffle)."""
    code = (row[0] if row else "").upper().replace(" ", "").strip()
    cols = link_col_indexes(headers)
    adj_i = adjacent_column_index(headers)
    notes_i = notes_column_index(headers)

    post = _cell(row, cols.get("post"))
    pages = _cell(row, cols.get("pages"))
    source_raw = _raw_cell(row, cols.get("source"))
    owner_raw = _raw_cell(row, cols.get("owner"))
    adjacent_raw = _raw_cell(row, adj_i)
    notes_raw = _raw_cell(row, notes_i)

    rescued: list[str] = []
    source = ""
    owner = ""
    owner_action = "empty"
    clear_adjacent = False
    clear_source_text = False

    # --- Q ลิ้งค์ต้นโพสต์ ---
    if _is_http(source_raw):
        source = source_raw
    elif cell_has_value(source_raw):
        rescued.append(source_raw)
        clear_source_text = True

    # --- เฟสเจ้าของ (prefer existing URL; non-URL text → notes) ---
    if cell_has_value(owner_raw):
        if _is_http(owner_raw):
            owner = owner_raw
            owner_action = "already_owner"
        else:
            rescued.append(owner_raw)
            owner_action = "empty"

    # --- R adjacent beside ต้นโพสต์ ---
    if cell_has_value(adjacent_raw):
        clear_adjacent = True
        if _is_http(adjacent_raw):
            if not owner:
                # Prefer profile-like; any URL is still allowed into owner when empty
                owner = adjacent_raw
                owner_action = "from_adjacent"
            elif adjacent_raw.rstrip("/") != owner.rstrip("/"):
                rescued.append(adjacent_raw)
        else:
            rescued.append(adjacent_raw)

    notes = merge_notes(notes_raw, *rescued)

    return TrustMappedRow(
        code=code,
        source=source,
        owner=owner,
        post=post,
        pages=pages,
        notes=notes,
        adjacent="",
        owner_action=owner_action,
        clear_adjacent=clear_adjacent,
        clear_source_text=clear_source_text,
        text_to_notes=rescued,
    )


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
    _set(cols.get("source"), mapped.source)  # cleared when text moved to notes
    _set(cols.get("owner"), mapped.owner)
    if notes_i is not None:
        _set(notes_i, mapped.notes)
    if adj_i is not None:
        _set(adj_i, "")

    own_i = owner_column_index(headers)
    if own_i is not None:
        while len(out) <= own_i:
            out.append("")
        out[own_i] = mapped.owner or ""

    src_i = source_column_index(headers)
    if src_i is not None:
        while len(out) <= src_i:
            out.append("")
        out[src_i] = mapped.source or ""

    return out

