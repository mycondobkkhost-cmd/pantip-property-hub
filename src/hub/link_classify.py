"""Horizontal link classification for「ชีตสำหรับทำงาน」rows.

Admins scatter Facebook / Living / Drive URLs across link columns and หมายเหตุ.
For each row we collect every URL, then assign:

  ต้นทาง (source)  ← group post OR Livinginsider
  เจ้าของ (owner)  ← Facebook profile (incl. /groups/.../user/)
  เพจ (pages)      ← Facebook Page URL, or a post that lived in Pages col
  ที่โพสต์ (post)   ← Facebook personal feed/post URL

Google Drive / Docs / Sheets anywhere → discard the whole property.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from src.hub.owner_facebook import (
    _GROUP_USER,
    _PEOPLE,
    _PROFILE_PHP,
    _is_fb_host,
    extract_urls,
    is_facebook_post_url,
    is_facebook_profile_url,
)
from src.hub.sheet_links import (  # noqa: F401 — re-exported for callers
    http_url_or_empty,
    link_col_indexes,
    pages_header_match,
    unwrap_link_cell,
)

_DRIVE_HOST_MARKERS = (
    "drive.google.com",
    "docs.google.com",
    "sheets.google.com",
)

_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


@dataclass
class UrlHit:
    url: str
    col_i: int
    role: str  # post | pages | source | owner | adjacent | notes | other
    kind: str  # drive | living | group | owner | page | post | other


@dataclass
class ClassifiedRow:
    code: str
    delete: bool = False
    source: str = ""
    owner: str = ""
    post: str = ""
    pages: str = ""
    notes: str = ""
    moved_from: dict[str, str] = field(default_factory=dict)
    all_urls: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def is_google_helper_url(url: str) -> bool:
    low = (url or "").strip().lower()
    return any(m in low for m in _DRIVE_HOST_MARKERS)


def is_living_url(url: str) -> bool:
    try:
        host = urlparse((url or "").split("#")[0]).netloc.lower()
    except Exception:
        return False
    return "livinginsider" in host


def is_facebook_group_url(url: str) -> bool:
    """Group feed/permalink — not a /groups/.../user/ profile."""
    u = (url or "").strip()
    if not u:
        return False
    try:
        parsed = urlparse(u.split("#")[0])
    except Exception:
        return False
    if not _is_fb_host(parsed.netloc):
        return False
    low = u.lower()
    if _GROUP_USER.search(low):
        return False
    return "/groups/" in low or "fb.com/groups/" in low


def is_facebook_page_url(url: str) -> bool:
    """Explicit Page URL patterns (not a vanity that might be a person)."""
    u = (url or "").strip()
    if not u:
        return False
    try:
        parsed = urlparse(u.split("#")[0])
    except Exception:
        return False
    if not _is_fb_host(parsed.netloc):
        return False
    low = u.lower()
    if is_facebook_post_url(u):
        # Page post under /pages/…/posts/…
        return "/pages/" in low
    path = (parsed.path or "").lower()
    if "/pages/" in path:
        return True
    # facebook.com/page_id_or_name with /about etc. — treat vanity as owner, not page
    return False


def classify_url_kind(url: str) -> str:
    """Single-URL kind: drive | living | group | owner | page | post | other."""
    u = (url or "").strip()
    if not u:
        return "other"
    if is_google_helper_url(u):
        return "drive"
    if is_living_url(u):
        return "living"
    try:
        host = urlparse(u.split("#")[0]).netloc.lower()
    except Exception:
        return "other"
    if not _is_fb_host(host):
        return "other"
    # Owner before group: /groups/X/user/Y is a profile
    if is_facebook_profile_url(u) or _GROUP_USER.search(u) or _PEOPLE.search(u) or _PROFILE_PHP.search(u):
        return "owner"
    if is_facebook_group_url(u):
        return "group"
    if is_facebook_page_url(u):
        return "page"
    if is_facebook_post_url(u):
        return "post"
    return "other"


def _header_role(headers: list[str], col_i: int, src_i: int | None, own_i: int | None) -> str:
    if col_i < 0 or col_i >= len(headers):
        return "other"
    hs = (headers[col_i] or "").strip()
    if hs == "ลิ้งค์โพส":
        return "post"
    if pages_header_match(headers[col_i] or ""):
        return "pages"
    if hs == "ลิ้งค์ต้นโพสต์":
        return "source"
    if hs == "เฟสเจ้าของ":
        return "owner"
    if hs == "หมายเหตุ":
        return "notes"
    # Blank header immediately beside source / owner → dump columns
    if not hs:
        if src_i is not None and col_i == src_i + 1:
            return "adjacent"
        if own_i is not None and col_i in {own_i + 1, own_i + 2}:
            return "adjacent"
        return "adjacent"
    return "other"


def _pick_preferred(
    hits: list[UrlHit],
    *,
    prefer_roles: tuple[str, ...],
) -> UrlHit | None:
    if not hits:
        return None
    for role in prefer_roles:
        for h in hits:
            if h.role == role:
                return h
    return hits[0]


def _strip_urls_from_notes(notes: str, urls_to_remove: set[str]) -> str:
    if not notes:
        return ""
    text = notes
    for u in sorted(urls_to_remove, key=len, reverse=True):
        text = text.replace(u, " ")
    # Collapse leftover whitespace / empty URL leftovers
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip(" \t\n|,;")


def collect_row_hits(headers: list[str], row: list[str]) -> list[UrlHit]:
    cols = link_col_indexes(headers)
    src_i = cols.get("source")
    own_i = cols.get("owner")
    hits: list[UrlHit] = []
    seen: set[str] = set()
    for col_i, cell in enumerate(row):
        raw = unwrap_link_cell(cell or "")
        if not raw:
            continue
        role = _header_role(headers, col_i, src_i, own_i)
        urls = extract_urls(raw)
        if not urls and raw.startswith("http"):
            urls = [raw.split()[0]]
        for u in urls:
            u = u.rstrip(").,;]'\"")
            key = u.lower().rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                UrlHit(
                    url=u,
                    col_i=col_i,
                    role=role,
                    kind=classify_url_kind(u),
                )
            )
    return hits


def classify_row(headers: list[str], row: list[str]) -> ClassifiedRow:
    code = (row[0] if row else "").upper().replace(" ", "").strip()
    notes_i = None
    for i, h in enumerate(headers):
        if (h or "").strip() == "หมายเหตุ":
            notes_i = i
            break
    notes_raw = (row[notes_i] if notes_i is not None and notes_i < len(row) else "") or ""
    notes_raw = str(notes_raw).strip()

    hits = collect_row_hits(headers, row)
    result = ClassifiedRow(code=code, all_urls=[h.url for h in hits], notes=notes_raw)

    if any(h.kind == "drive" for h in hits):
        result.delete = True
        result.reasons.append("drive_helper")
        return result

    living = [h for h in hits if h.kind == "living"]
    groups = [h for h in hits if h.kind == "group"]
    owners = [h for h in hits if h.kind == "owner"]
    pages_exact = [h for h in hits if h.kind == "page"]
    posts = [h for h in hits if h.kind == "post"]

    # --- source (ต้นทาง) ---
    src_hit = _pick_preferred(living, prefer_roles=("source", "notes", "adjacent", "other"))
    if src_hit is None:
        src_hit = _pick_preferred(
            groups, prefer_roles=("source", "owner", "adjacent", "notes", "post", "pages", "other")
        )
    if src_hit is not None:
        result.source = src_hit.url
        if src_hit.role != "source":
            result.moved_from["source"] = src_hit.role

    # --- owner (เจ้าของ) ---
    # Living-only rows may leave owner empty — do not invent.
    own_hit = _pick_preferred(
        owners, prefer_roles=("owner", "adjacent", "source", "notes", "post", "pages", "other")
    )
    if own_hit is not None:
        result.owner = own_hit.url
        if own_hit.role != "owner":
            result.moved_from["owner"] = own_hit.role

    # --- post / pages ---
    # Prefer values already in the correct column when they are post-typed.
    post_from_col = [h for h in posts if h.role == "post"]
    pages_from_col = [h for h in posts if h.role == "pages"] + pages_exact
    remaining_posts = [
        h
        for h in posts
        if h not in post_from_col and h not in pages_from_col
    ]

    if post_from_col:
        result.post = post_from_col[0].url
    if pages_from_col:
        result.pages = pages_from_col[0].url

    # Fill empties from leftover posts / exact page URLs
    leftovers = remaining_posts + [h for h in pages_exact if h.url != result.pages]
    for h in leftovers:
        if not result.post:
            result.post = h.url
            if h.role != "post":
                result.moved_from["post"] = h.role
            continue
        if not result.pages and h.url != result.post:
            result.pages = h.url
            if h.role != "pages":
                result.moved_from["pages"] = h.role

    # If Pages col held a profile/group wrongly, don't keep it as pages
    # (already handled — we only assign post-kind / page-kind)

    # Clean notes: remove URLs that we assigned into link buckets
    assigned = {u for u in (result.source, result.owner, result.post, result.pages) if u}
    drive_urls = {h.url for h in hits if h.kind == "drive"}
    result.notes = _strip_urls_from_notes(notes_raw, assigned | drive_urls)

    # Normalize http-only for link fields
    result.source = http_url_or_empty(result.source) or result.source
    result.owner = http_url_or_empty(result.owner) or result.owner
    result.post = http_url_or_empty(result.post)
    result.pages = http_url_or_empty(result.pages)

    return result


def notes_column_index(headers: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if (h or "").strip() == "หมายเหตุ":
            return i
    return None


def adjacent_dump_indexes(headers: list[str]) -> list[int]:
    """Blank columns used as link dump zones beside source/owner."""
    cols = link_col_indexes(headers)
    out: list[int] = []
    src_i = cols.get("source")
    own_i = cols.get("owner")
    if src_i is not None:
        adj = src_i + 1
        if adj < len(headers) and not (headers[adj] or "").strip():
            out.append(adj)
    if own_i is not None:
        for adj in (own_i + 1, own_i + 2):
            if adj < len(headers) and not (headers[adj] or "").strip():
                out.append(adj)
    return out
