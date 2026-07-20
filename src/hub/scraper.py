"""Fetch listing pages (Facebook / Living Insider) and extract text."""

from __future__ import annotations

import re
import ssl
from html import unescape
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from src.hub.parser import is_group_boilerplate, parse_listing_text, parsed_to_dict

DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
TIMEOUT = 25


def classify_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "livinginsider" in host:
        return "living"
    if "facebook" in host or "fb." in host:
        return "facebook"
    return "other"


def _meta(html: str, prop: str) -> str:
    patterns = [
        rf'<meta[^>]+property=["\']{prop}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{prop}["\']',
        rf'<meta[^>]+name=["\']{prop}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{prop}["\']',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.I)
        if m:
            return unescape(m.group(1))
    return ""


def _title(html: str) -> str:
    m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    return unescape(m.group(1)).strip() if m else ""


def _living_body(html: str) -> str:
    chunks: list[str] = []
    for pat in [
        r'<div[^>]+class="[^"]*detail[^"]*"[^>]*>(.*?)</div>',
        r"<article[^>]*>(.*?)</article>",
    ]:
        for m in re.finditer(pat, html, re.I | re.S):
            text = re.sub(r"<[^>]+>", " ", m.group(1))
            text = unescape(re.sub(r"\s+", " ", text)).strip()
            if len(text) > 40:
                chunks.append(text)
    return "\n".join(chunks)


def _facebook_fetch_urls(url: str) -> list[str]:
    """Try original + mobile mirror for share links."""
    urls = [url.strip()]
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "www.facebook.com" in host:
        urls.append(url.replace("www.facebook.com", "m.facebook.com", 1))
    elif "m.facebook.com" not in host and "facebook.com" in host:
        urls.append(url.replace("facebook.com", "m.facebook.com", 1))
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _http_get(url: str, user_agent: str) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "th,en;q=0.9",
        },
    )
    ctx = ssl.create_default_context()
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ctx))
    with opener.open(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _extract_from_html(html: str, kind: str) -> tuple[list[str], list[str]]:
    parts: list[str] = []
    warnings: list[str] = []

    og_title = _meta(html, "og:title")
    og_desc = _meta(html, "og:description")
    page_title = _title(html)

    if og_desc:
        parts.append(og_desc)
    if og_title and og_title not in parts:
        # Trim Facebook suffix from titles
        clean_title = re.sub(r"\s*\|\s*Facebook\s*$", "", og_title, flags=re.I)
        if clean_title and clean_title not in parts:
            parts.append(clean_title)
    if page_title and page_title not in parts and "facebook" not in page_title.lower():
        parts.append(page_title)

    if kind == "living":
        body = _living_body(html)
        if body:
            parts.append(body)
    elif kind == "facebook":
        if not og_desc and ("login" in html.lower()[:8000] or "เข้าสู่ระบบ" in html):
            warnings.append("Facebook ต้อง login — คัดลอกข้อความโพสต์มาวางเองด้านล่าง")

    return parts, warnings


def fetch_page_text(url: str) -> tuple[str, list[str]]:
    """Return (combined_text, warnings)."""
    warnings: list[str] = []
    url = url.strip()
    if not url.startswith("http"):
        return "", ["URL ไม่ถูกต้อง"]

    kind = classify_url(url)
    candidates = _facebook_fetch_urls(url) if kind == "facebook" else [url]
    agents = [MOBILE_UA, DESKTOP_UA] if kind == "facebook" else [DESKTOP_UA, MOBILE_UA]

    last_error = ""
    for candidate in candidates:
        for agent in agents:
            try:
                html = _http_get(candidate, agent)
            except URLError as exc:
                last_error = str(exc.reason)
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                continue

            parts, html_warnings = _extract_from_html(html, kind)
            warnings.extend(html_warnings)
            text = "\n".join(p for p in parts if p).strip()
            if text:
                if candidate != url:
                    warnings.append("ดึงผ่าน mobile URL")
                return text, _unique_warnings(warnings)

    if last_error:
        if kind == "facebook":
            warnings.append(
                f"ดึง Facebook อัตโนมัติไม่ได้ ({last_error}) — "
                "เปิดลิงก์ในเบราว์เซอร์ แล้วคัดลอกข้อความโพสต์มาวางด้านล่าง"
            )
        else:
            warnings.append(f"ดึงหน้าเว็บไม่ได้: {last_error}")
    else:
        warnings.append("ไม่พบข้อความจากหน้าเว็บ — วางข้อความโพสต์เอง")

    return "", _unique_warnings(warnings)


def _unique_warnings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for w in items:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


PARTIAL_FB_MSG = (
    "Facebook ให้ข้อความไม่ครบ — คัดลอกโพสต์เต็มจากมือถือ "
    "→ วางทับช่องต้นฉบับ → กด「วิเคราะห์ข้อความ」"
)

GROUP_RULES_FB_MSG = (
    "Facebook ส่งข้อความกฎกลุ่มมาแทนโพสต์ห้อง — "
    "คัดลอกเนื้อหาโพสต์จริง (เช่น Thong Lo Tower / ราคา / ชั้น) "
    "วางทับช่องต้นฉบับ แล้วกด「วิเคราะห์ข้อความ」"
)


def is_partial_text(text: str, kind: str = "") -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if is_group_boilerplate(t):
        return True
    if t.endswith("...") or t.endswith("…"):
        return True
    # Facebook มักตัดกลางบรรทัด เช่น "8 นาที..."
    if re.search(r"[^\s]\.\.\.|[^\s]…", t):
        return True
    if "..." in t[-120:] and len(t) < 700:
        return True
    # og:description มักซ้ำชื่อโครงการท้ายข้อความ
    if kind == "facebook" and len(t) < 550:
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        if len(lines) >= 2 and lines[-1].count("For Rent") and lines[-1].count("For Rent") >= 1:
            if any("For Rent" in ln for ln in lines[:-1]):
                return True
    return False


def pick_text(fetched: str, pasted: str) -> tuple[str, str]:
    """Return (text_to_parse, source_note)."""
    fetched = (fetched or "").strip()
    pasted = (pasted or "").strip()
    # never prefer group-rules blurbs over a real pasted listing
    if pasted and is_group_boilerplate(fetched) and not is_group_boilerplate(pasted):
        return pasted, "ใช้ข้อความที่วางเอง (ลิงก์ส่งกฎกลุ่มมา)"
    if pasted and len(pasted) > len(fetched) + 30:
        return pasted, "ใช้ข้อความที่วางเอง (ครบกว่าที่ดึงจากลิงก์)"
    if pasted and is_partial_text(fetched, "facebook") and len(pasted) > 40:
        return pasted, "ใช้ข้อความที่วางเอง (ครบกว่าที่ดึงจากลิงก์)"
    if fetched:
        return fetched, ""
    return pasted, ""


def scrape_url(url: str, pasted_text: str = "") -> dict:
    kind = classify_url(url)
    fetched, fetch_warnings = fetch_page_text(url)
    text, note = pick_text(fetched, pasted_text)
    warnings = list(fetch_warnings)
    if note:
        warnings.append(note)
    elif fetched and is_group_boilerplate(fetched) and not pasted_text.strip():
        warnings.insert(0, GROUP_RULES_FB_MSG)
    elif fetched and is_partial_text(fetched, kind) and not pasted_text.strip():
        warnings.insert(0, PARTIAL_FB_MSG)

    if text:
        parsed = parse_listing_text(text)
        parsed.warnings = warnings + parsed.warnings
    else:
        parsed = parse_listing_text("")
        parsed.warnings = warnings
        parsed.warnings = [w for w in parsed.warnings if "ไม่มีข้อความให้วิเคราะห์" not in w]

    data = parsed_to_dict(parsed)
    data["source_url"] = url
    data["source_kind"] = classify_url(url)
    data["fetch_ok"] = bool(text) and not is_group_boilerplate(text)
    data["is_partial"] = bool(
        (fetched and is_partial_text(fetched, kind) and not pasted_text.strip())
        or is_group_boilerplate(text)
    )
    return data
