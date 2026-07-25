"""Resolve owner Facebook profile links from main-sheet columns.

Admins often leave「เฟสเจ้าของ」empty and put the profile in the blank column
immediately beside「ลิ้งค์ต้นโพสต์」, or (rarely) paste a profile URL into the
post-link column itself.

Conservative URL classification: only move/clear when a URL is clearly a
profile — never treat permalinks / share / photo / story links as profiles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)

# Strong post / content markers — never treat as profile.
_POST_MARKERS = re.compile(
    r"(?:/permalink(?:\.php)?/|/posts?/|/story\.php\b|/stories/|"
    r"/photo(?:s|s\.php)?(?:/|\?|$)|/videos?/|/reel(?:s)?/|/watch/|"
    r"/share/p/|/share/v/|"
    r"story_fbid=|/groups/[^/]+/(?:posts|permalink)\b)",
    re.I,
)
# facebook.com/share/<token> (post share short-links, not /share/p/)
_SHARE_BARE = re.compile(
    r"(?:facebook|fb)\.com/share/[A-Za-z0-9_-]+/?(?:\?|$)", re.I
)
_PROFILE_PHP = re.compile(r"profile\.php\?id=\d+", re.I)
# Group member profile: /groups/<id>/user/<id>
_GROUP_USER = re.compile(r"/groups/[^/]+/user/\d+", re.I)
_PEOPLE = re.compile(r"/people/[^/]+/\d+", re.I)

_EMPTY_TOKENS = {".", "-", "—", "n/a", "N/A", "NA", "na", "none", "None"}

# First path segment reserved by Facebook — not a vanity username.
_RESERVED_FIRST = frozenset(
    {
        "groups",
        "pages",
        "events",
        "watch",
        "reel",
        "reels",
        "marketplace",
        "stories",
        "photo",
        "photos",
        "photo.php",
        "video",
        "videos",
        "permalink",
        "permalink.php",
        "share",
        "story.php",
        "people",
        "profile.php",
        "login",
        "recover",
        "help",
        "privacy",
        "settings",
        "notifications",
        "friends",
        "gaming",
        "live",
        "hashtag",
        "public",
        "dialog",
        "sharer",
        "plugins",
        "home",
        "bookmarks",
        "messages",
        "friends",
        "menu",
        "policies",
        "privacy_center",
        "ads",
        "adsmanager",
        "business",
        "directory",
        "helpdesk",
        "donate",
        "fundraisers",
        "jobs",
        "notes",
        "places",
        "timeline",
        "media",
        "cgi-bin",
    }
)


def extract_urls(text: str) -> list[str]:
    if not text:
        return []
    return _URL_RE.findall(text)


def _is_fb_host(host: str) -> bool:
    h = (host or "").lower()
    return (
        h.endswith("facebook.com")
        or h.endswith("fb.com")
        or h.endswith("fb.me")
        or h == "fb.com"
        or h == "fb.me"
    )


def is_facebook_post_url(url: str) -> bool:
    """True when URL clearly points at a post/share/photo/story (not a profile)."""
    u = (url or "").strip()
    if not u:
        return False
    low = u.lower()
    try:
        host = urlparse(u.split("#")[0]).netloc
    except Exception:
        return False
    if not _is_fb_host(host):
        return False
    if _POST_MARKERS.search(low) or _SHARE_BARE.search(low):
        return True
    return False


def is_facebook_profile_url(url: str) -> bool:
    """Conservative: only True when the URL looks like a person/page profile."""
    u = (url or "").strip()
    if not u:
        return False
    low = u.lower()
    try:
        parsed = urlparse(u.split("#")[0])
    except Exception:
        return False
    if not _is_fb_host(parsed.netloc):
        return False
    # Posts win over profile heuristics.
    if is_facebook_post_url(u):
        return False
    if _PROFILE_PHP.search(low):
        return True
    if _GROUP_USER.search(low):
        return True
    if _PEOPLE.search(low):
        return True
    path = (parsed.path or "/").strip("/")
    if not path:
        return False
    parts = [p for p in path.split("/") if p]
    first = parts[0].lower()
    if first in _RESERVED_FIRST:
        return False
    # Vanity username: facebook.com/some.name  (single segment)
    if len(parts) == 1:
        # Reject pure numeric (often page ids in odd paths) unless profile.php handled
        if parts[0].isdigit():
            return False
        return True
    return False


def cell_has_value(raw: str) -> bool:
    s = (raw or "").strip()
    if not s or s in _EMPTY_TOKENS:
        return False
    return True


def first_profile_url(raw: str) -> str:
    """Return first profile-classified URL in a cell, else ''."""
    for u in extract_urls(raw or ""):
        if is_facebook_profile_url(u):
            return u
    return ""


def adjacent_owner_candidate(raw: str) -> str:
    """Value to take from the blank column beside「ลิ้งค์ต้นโพสต์」.

    Prefer a profile URL; if the cell is only a profile URL (or starts with one),
    return the full cell text so query strings / extras are preserved.
    """
    s = (raw or "").strip()
    if not cell_has_value(s):
        return ""
    profile = first_profile_url(s)
    if profile:
        # If the whole cell is essentially that one URL, keep original text.
        urls = extract_urls(s)
        if len(urls) == 1 and s.startswith("http"):
            return s
        return profile
    return ""


@dataclass
class OwnerResolveResult:
    owner: str
    source_url: str
    adjacent: str
    action: str  # already_owner | from_adjacent | from_source_profile | empty
    clear_adjacent: bool = False
    clear_source: bool = False


def resolve_owner_facebook(
    *,
    owner_raw: str,
    adjacent_raw: str = "",
    source_raw: str = "",
) -> OwnerResolveResult:
    """Pick owner profile per product rules (conservative).

    1. 「เฟสเจ้าของ」non-empty → keep
    2. else profile URL in adjacent (blank col beside「ลิ้งค์ต้นโพสต์」) → use it
    3. else「ลิ้งค์ต้นโพสต์」itself is a profile (not a post) → move to owner
    """
    owner = (owner_raw or "").strip()
    adjacent = (adjacent_raw or "").strip()
    source = (source_raw or "").strip()

    if cell_has_value(owner):
        # Soft fix:「เฟสเจ้าของ」sometimes holds a second post permalink while the
        # real profile sits in the blank adjacent column. Prefer the profile.
        owner_urls = extract_urls(owner)
        owner_is_post_only = bool(
            owner_urls
            and is_facebook_post_url(owner_urls[0])
            and not first_profile_url(owner)
        )
        if owner_is_post_only:
            adj_val = adjacent_owner_candidate(adjacent)
            if adj_val:
                return OwnerResolveResult(
                    owner=adj_val,
                    source_url=source,
                    adjacent="",
                    action="from_adjacent_over_post",
                    clear_adjacent=True,
                )
        return OwnerResolveResult(
            owner=owner,
            source_url=source,
            adjacent=adjacent,
            action="already_owner",
        )

    adj_val = adjacent_owner_candidate(adjacent)
    if adj_val:
        return OwnerResolveResult(
            owner=adj_val,
            source_url=source,
            adjacent="",
            action="from_adjacent",
            clear_adjacent=True,
        )

    # Source column looks like a profile (misplaced) — move, clear post link.
    profile_in_source = first_profile_url(source)
    if profile_in_source:
        urls = extract_urls(source)
        moved = source if len(urls) == 1 and source.startswith("http") else profile_in_source
        return OwnerResolveResult(
            owner=moved,
            source_url="",
            adjacent=adjacent,
            action="from_source_profile",
            clear_source=True,
        )

    return OwnerResolveResult(
        owner="",
        source_url=source,
        adjacent=adjacent,
        action="empty",
    )


def owner_column_index(headers: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if (h or "").strip() == "เฟสเจ้าของ":
            return i
    return None


def source_column_index(headers: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if (h or "").strip() == "ลิ้งค์ต้นโพสต์":
            return i
    return None


def adjacent_column_index(headers: list[str]) -> int | None:
    """Blank header immediately after「ลิ้งค์ต้นโพสต์」, if any."""
    src_i = source_column_index(headers)
    if src_i is None:
        return None
    adj_i = src_i + 1
    if adj_i >= len(headers):
        return None
    # Only treat as the "beside" dump column when header is empty
    # (not when เฟสเจ้าของ sits directly next door).
    if (headers[adj_i] or "").strip():
        return None
    return adj_i
