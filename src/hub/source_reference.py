"""Source reference helpers — internal free-text vs Co-Agent safe public URL."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Stored on property records as ``source_url`` (backward compatible).
SOURCE_REFERENCE_FIELD = "source_url"


def normalize_http_url(raw: Any) -> str:
    """Return a normalized http(s) URL or empty string."""
    s = str(raw or "").strip()
    if not s or re.search(r"\s", s):
        return ""
    if re.match(r"^(www\.|facebook\.com|fb\.com|m\.facebook\.com)", s, re.I):
        s = "https://" + s
    if not re.match(r"^https?://", s, re.I):
        return ""
    try:
        parsed = urlparse(s)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if re.search(r"\s", parsed.netloc):
        return ""
    if not re.match(r"^[a-zA-Z0-9._-]+(\.[a-zA-Z0-9._-]+)*(:[0-9]+)?$", parsed.netloc.split("@")[-1]):
        return ""
    return s


def is_http_url(raw: Any) -> bool:
    return bool(normalize_http_url(raw))


def derive_public_listing_url(prop: dict[str, Any]) -> str:
    """Co-Agent safe public listing URL.

    Uses only published post links (page or personal). Internal ``source_url``
    is never exposed — staff may store arbitrary reference text there.
    """
    for key in ("post_pages_url", "post_url"):
        url = normalize_http_url(prop.get(key))
        if url:
            return url
    return ""


def source_reference_display(raw: Any) -> dict[str, Any]:
    """Presentation helper for internal UI."""
    text = str(raw or "").strip()
    href = normalize_http_url(text)
    return {
        "text": text,
        "is_link": bool(href),
        "href": href,
    }


def validate_url_for_action(url: Any, *, action: str = "generic") -> tuple[bool, str]:
    """Validate URL only at action boundaries (scrape, Facebook automation, etc.)."""
    s = str(url or "").strip()
    if not s:
        return False, "กรุณาใส่ URL"
    if not is_http_url(s):
        if action == "scrape":
            return False, "ดึงจากลิงก์ต้องเป็น URL ที่ขึ้นต้นด้วย http:// หรือ https://"
        if action == "facebook":
            return False, "ต้องเป็นลิงก์ Facebook ที่ถูกต้อง"
        return False, "ต้องเป็น URL ที่ถูกต้อง"
    return True, ""


def co_agent_safe_property_fields(prop: dict[str, Any]) -> dict[str, Any]:
    """Return only fields safe to expose on Co-Agent (never internal source text)."""
    pub_url = derive_public_listing_url(prop)
    return {
        "public_listing_url": pub_url,
        "has_public_listing_url": bool(pub_url),
        "source_reference_exposed": False,
    }
