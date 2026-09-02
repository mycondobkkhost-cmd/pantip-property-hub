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
# Crawler UAs sometimes get OG tags when browser UAs get a login wall.
CRAWLER_UAS = (
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "WhatsApp/2.23.20.0",
    "TelegramBot (like TwitterBot)",
    "Twitterbot/1.0",
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
    """Build alternate Facebook URLs — pfbid/story links need several shapes."""
    from urllib.parse import parse_qs, urlencode, urlunparse

    raw = (url or "").strip()
    if not raw:
        return []
    urls: list[str] = [raw]
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    qs = parse_qs(parsed.query or "", keep_blank_values=False)
    story = (qs.get("story_fbid") or qs.get("fbid") or [""])[0].strip()
    page_id = (qs.get("id") or [""])[0].strip()

    def _swap_host(u: str, new_host: str) -> str:
        p = urlparse(u)
        return urlunparse((p.scheme or "https", new_host, p.path, p.params, p.query, p.fragment))

    if "www.facebook.com" in host:
        urls.append(_swap_host(raw, "m.facebook.com"))
    elif host.startswith("m.facebook.com"):
        urls.append(_swap_host(raw, "www.facebook.com"))
    elif "facebook.com" in host:
        urls.append(_swap_host(raw, "m.facebook.com"))
        urls.append(_swap_host(raw, "www.facebook.com"))

    if story and page_id:
        for h in ("www.facebook.com", "m.facebook.com"):
            urls.append(f"https://{h}/{page_id}/posts/{story}")
            urls.append(f"https://{h}/permalink.php?{urlencode({'story_fbid': story, 'id': page_id})}")
            urls.append(f"https://{h}/story.php?{urlencode({'story_fbid': story, 'id': page_id})}")

    # share/p links: try www + m
    if "/share/p/" in (parsed.path or "") or "/share/v/" in (parsed.path or ""):
        if "www.facebook.com" in host:
            urls.append(_swap_host(raw, "m.facebook.com"))
        else:
            urls.append(_swap_host(raw, "www.facebook.com"))

    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        u = (u or "").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _is_generic_fb_icon(image_url: str) -> bool:
    low = (image_url or "").lower()
    if not low.startswith("http"):
        return True
    if "static.xx.fbcdn" in low or "/rsrc.php/" in low:
        return True
    if "emoji.php" in low or "/images/icons/" in low:
        return True
    # Incomplete host-only / truncated CDN URLs
    try:
        from urllib.parse import urlparse

        path = urlparse(image_url).path or ""
    except Exception:  # noqa: BLE001
        path = ""
    if len(path) < 8 or "." not in path.rsplit("/", 1)[-1]:
        if "scontent" in low or "fbcdn" in low:
            return True
    # Tiny profile placeholders
    if "scontent" in low and ("_s.jpg" in low or "p32x32" in low or "p50x50" in low):
        return True
    return False


def _image_dedupe_key(image_url: str) -> str:
    """Stable key so same FB photo with different size/query params counts once."""
    raw = (image_url or "").strip()
    if not raw:
        return ""
    try:
        from urllib.parse import urlparse, unquote

        parsed = urlparse(raw)
        path = unquote(parsed.path or "")
    except Exception:  # noqa: BLE001
        path = raw.split("?", 1)[0]
    # Prefer long numeric asset id in filename (common on scontent)
    nums = re.findall(r"(\d{10,})", path)
    if nums:
        # longest id is usually the photo/asset id
        return max(nums, key=len)
    base = path.rsplit("/", 1)[-1].lower()
    base = re.sub(r"_(?:n|s|o|q|p)\.(?:jpe?g|png|webp)$", "", base)
    base = re.sub(r"\.(?:jpe?g|png|webp)$", "", base)
    return base or path.lower()


def _image_quality_score(image_url: str) -> int:
    low = (image_url or "").lower()
    score = 0
    if "_n.jpg" in low or "_n.png" in low:
        score += 5
    if "t39.30808" in low or "/v/t39." in low:
        score += 3
    if "scontent" in low:
        score += 2
    # Prefer larger stp sizes when present
    m = re.search(r"s(\d{3,4})x(\d{3,4})", low)
    if m:
        score += min(int(m.group(1)), int(m.group(2))) // 100
    if "stp=" in low and "s960" in low:
        score += 2
    if "p32x32" in low or "p50x50" in low or "s130x130" in low:
        score -= 10
    return score


def _dedupe_image_urls(urls: list[str], *, limit: int = 12) -> list[str]:
    """Keep best-quality URL per photo identity."""
    best: dict[str, tuple[int, str]] = {}
    order: list[str] = []
    for u in urls:
        s = str(u or "").strip()
        if not s.startswith("http") or _is_generic_fb_icon(s):
            continue
        key = _image_dedupe_key(s)
        if not key:
            key = s
        score = _image_quality_score(s)
        prev = best.get(key)
        if prev is None:
            best[key] = (score, s)
            order.append(key)
        elif score > prev[0]:
            best[key] = (score, s)
    out = [best[k][1] for k in order if k in best]
    return out[: max(1, min(int(limit or 12), 12))]


def _extract_image_candidates_from_html(html: str) -> list[str]:
    """Collect likely photo URLs from meta tags + embedded scontent links."""
    found: list[str] = []
    for prop in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"):
        img = _meta(html, prop).strip()
        if img.startswith("//"):
            img = "https:" + img
        if img.startswith("http"):
            found.append(img)

    # Escape-aware scontent URLs inside JSON blobs
    for m in re.finditer(r"https:\\?/\\?/scontent[^\"'\\s<>]+", html, re.I):
        u = m.group(0).replace("\\/", "/").replace("\\u00253A", ":").replace("\\u00252F", "/")
        u = unescape(u)
        if u.startswith("http"):
            found.append(u)

    for m in re.finditer(r"https://scontent[^\"'\\s<>]+", html, re.I):
        found.append(unescape(m.group(0)))

    ranked: list[str] = []
    seen: set[str] = set()
    for img in found:
        if _is_generic_fb_icon(img):
            continue
        # Prefer full post photos over tiny thumbs
        score = _image_quality_score(img)
        if score <= 0 and "fbcdn" not in img.lower():
            continue
        if img in seen:
            continue
        seen.add(img)
        ranked.append(img)
    # Keep stable order but prefer higher-looking CDN photo URLs first
    ranked.sort(
        key=lambda u: (
            0 if "t39.30808" in u.lower() else 1,
            0 if "_n.jpg" in u.lower() or "_n.png" in u.lower() else 1,
            -_image_quality_score(u),
            len(u),
        )
    )
    return _dedupe_image_urls(ranked, limit=12)


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


def fetch_preview_image(url: str) -> tuple[str, list[str]]:
    """Best-effort single image (first candidate). Prefer fetch_preview_images for galleries."""
    imgs, warnings = fetch_preview_images(url, limit=1)
    return (imgs[0] if imgs else ""), warnings


def fetch_preview_images(url: str, *, limit: int = 12) -> tuple[list[str], list[str]]:
    """Collect up to `limit` distinct photo URLs from a listing/page HTML."""
    warnings: list[str] = []
    url = (url or "").strip()
    if not url.startswith("http"):
        return [], ["URL ไม่ถูกต้อง"]

    kind = classify_url(url)
    candidates = _facebook_fetch_urls(url) if kind == "facebook" else [url]
    agents = (
        [MOBILE_UA, DESKTOP_UA, *CRAWLER_UAS]
        if kind == "facebook"
        else [DESKTOP_UA, MOBILE_UA]
    )
    limit = max(1, min(int(limit or 12), 12))
    collected: list[str] = []
    seen: set[str] = set()
    last_error = ""
    saw_login_wall = False

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

            low_head = html[:8000].lower()
            if "login" in low_head or "เข้าสู่ระบบ" in html[:8000]:
                saw_login_wall = True

            for img in _extract_image_candidates_from_html(html):
                if img in seen:
                    continue
                # Also skip same photo identity (different CDN size/query)
                key = _image_dedupe_key(img)
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                seen.add(img)
                collected.append(img)
                if len(collected) >= limit:
                    return _dedupe_image_urls(collected, limit=limit), _unique_warnings(warnings)

    if not collected:
        if last_error:
            warnings.append(f"ดึงรูปไม่ได้: {last_error}")
        elif kind == "facebook":
            if saw_login_wall:
                warnings.append(
                    "Facebook บังคับล็อกอินจากเซิร์ฟเวอร์คลาวด์ — "
                    "อัปรูปเองใน Hub หรือให้ Agent บนเครื่องดึงจากเน็ตบ้าน"
                )
            else:
                warnings.append("Facebook มักไม่ให้ดึงรูปครบ — อัปเองชัวร์กว่า")
        else:
            warnings.append("ไม่พบรูปในหน้า")
    return _dedupe_image_urls(collected, limit=limit), _unique_warnings(warnings)


def fetch_image_bytes(image_url: str) -> tuple[bytes, str]:
    """Download image bytes for proxying (Facebook CDN often blocks browser hotlink)."""
    image_url = (image_url or "").strip()
    if not image_url.startswith("http"):
        return b"", ""
    last_error = ""
    for agent in (MOBILE_UA, DESKTOP_UA):
        try:
            req = Request(
                image_url,
                headers={
                    "User-Agent": agent,
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Accept-Language": "th,en;q=0.9",
                    "Referer": "https://www.facebook.com/",
                },
            )
            ctx = ssl.create_default_context()
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=ctx))
            with opener.open(req, timeout=TIMEOUT) as resp:
                data = resp.read()
                ctype = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
                if data and ctype.startswith("image/"):
                    return data, ctype
                if data and len(data) > 1000:
                    return data, ctype or "image/jpeg"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            continue
    if last_error:
        return b"", ""
    return b"", ""


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
    try:
        preview, _ = fetch_preview_image(url)
        if preview:
            data["preview_image"] = preview
    except Exception:  # noqa: BLE001
        pass
    return data
