"""Main-sheet ↔ property ↔ overview link column mapping.

Main「ชีตสำหรับทำงาน」(yellow link cols) → property fields →「ทรัพย์รวม」:

  ลิ้งค์ต้นโพสต์     → source_url       → ต้นทาง
  เฟสเจ้าของ         → owner_facebook   → เจ้าของ
  ลิ้งค์โพส          → post_url         → ที่โพสต์
  ลิ้งค์โพส Pages    → post_pages_url   → เพจ

「ทรัพย์รวม」is a Hub-derived view (short HYPERLINK labels), not a cell-for-cell
copy of every main-sheet URL column. Empty โพสต์/เพจ means the property object
has no post_url / post_pages_url (often newest rows not posted yet).
"""

from __future__ import annotations

import re

# =HYPERLINK("url","label") or =HYPERLINK("url")
_HYPERLINK_RE = re.compile(
    r"""^=\s*HYPERLINK\s*\(\s*"(.*?)"(?:\s*,\s*"(?:.*?)"\s*)?\)\s*$""",
    re.I | re.DOTALL,
)
# Looser: HYPERLINK("url" anywhere in a formula
_HYPERLINK_URL_RE = re.compile(
    r"""HYPERLINK\s*\(\s*"(https?://[^"]+)""",
    re.I,
)

_EMPTY_TOKENS = {
    "",
    ".",
    "-",
    "—",
    "–",
    "n/a",
    "N/A",
    "NA",
    "na",
    "none",
    "None",
    "Not Available⛔️",
}


def unwrap_link_cell(raw: str) -> str:
    """Return a usable URL (or original text) from a sheet cell.

    Handles plain URLs and ``=HYPERLINK("url","label")`` formulas. Display
    labels alone (e.g. 「โพสต์」) cannot be recovered without the formula.
    """
    s = str(raw or "").strip()
    if not s or s in _EMPTY_TOKENS:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        return s
    m = _HYPERLINK_RE.match(s)
    if m:
        url = (m.group(1) or "").replace('""', '"').strip()
        return url if url.startswith("http") else s
    m2 = _HYPERLINK_URL_RE.search(s)
    if m2:
        return m2.group(1).strip()
    return s


def http_url_or_empty(raw: str) -> str:
    """Keep only http(s) URLs; unwrap HYPERLINK first. Non-URL text → empty."""
    s = unwrap_link_cell(raw)
    if s.startswith("http://") or s.startswith("https://"):
        return s
    return ""


def pages_header_match(header: str) -> bool:
    return (header or "").strip().rstrip() == "ลิ้งค์โพส Pages"


def link_col_indexes(headers: list[str]) -> dict[str, int | None]:
    """Map logical link keys → column index on main sheet (by header name)."""
    out: dict[str, int | None] = {
        "post": None,
        "pages": None,
        "source": None,
        "owner": None,
    }
    for i, h in enumerate(headers):
        hs = (h or "").strip()
        if hs == "ลิ้งค์โพส":
            out["post"] = i
        elif pages_header_match(h or ""):
            out["pages"] = i
        elif hs == "ลิ้งค์ต้นโพสต์":
            out["source"] = i
        elif hs == "เฟสเจ้าของ":
            out["owner"] = i
    return out


def merge_formula_and_formatted(
    formula_rows: list[list],
    formatted_rows: list[list],
) -> list[list[str]]:
    """Prefer HYPERLINK-unwrapped formula cells; else formatted display value.

    Important: for plain cells (esp. dates), always prefer FORMATTED_VALUE.
    FORMULA/UNFORMATTED renders turn dates into serials and break import status.
    """
    n = max(len(formula_rows), len(formatted_rows))
    out: list[list[str]] = []
    for r in range(n):
        frow = formula_rows[r] if r < len(formula_rows) else []
        drow = formatted_rows[r] if r < len(formatted_rows) else []
        width = max(len(frow), len(drow))
        row: list[str] = []
        for c in range(width):
            f = frow[c] if c < len(frow) else ""
            d = drow[c] if c < len(drow) else ""
            fs = str(f or "").strip()
            ds = str(d or "").strip()
            if fs.upper().startswith("=HYPERLINK"):
                row.append(unwrap_link_cell(fs) or ds)
            elif fs.startswith("="):
                # Other formulas — keep formatted display
                row.append(ds)
            else:
                # Plain value: prefer formatted (dates stay DD/MM/YYYY)
                row.append(unwrap_link_cell(ds) if ds else unwrap_link_cell(fs))
        out.append(row)
    return out
