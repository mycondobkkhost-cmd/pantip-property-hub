"""Unique group-post captions from a full public-page original.

Priority for base text:
1. page_post_text — admin-pasted full original from the public Page post
2. Hub text_th — only if it looks complete (never prefer truncated FB scrape)
3. FB scrape — last resort, rejected when truncated / title-mashup

Anti-spam: keep the original body 100% intact; only micro-vary the end
(hashtag reorder / trailing newlines / invisible marks / soft date trailer).
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent.parent
HISTORY_PATH = BASE_DIR / "data" / "caption_copy_history.json"
_LOCK = threading.RLock()
BANGKOK = ZoneInfo("Asia/Bangkok")

REUSE_WINDOW_SEC = 120
MAX_ATTEMPTS = 48

# Soft trailers we append (never strip original page hashtags/contacts)
OUR_DATE_TRAILER_RE = re.compile(r"^อัปเดต \d{2}/\d{2}(?: · [a-f0-9]+)?$")
PAGE_BRAND_NOISE_RE = re.compile(
    r"Pantip\s*Property|จัดหา\s*ฝากขาย\s*บ้านคอนโด",
    re.I,
)


def caption_fingerprint(text: str) -> str:
    """Hash after collapsing normal whitespace; keep zero-width marks so variants differ."""
    norm = re.sub(r"[ \t\r\n\f\v]+", " ", (text or "").strip())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:20]


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_history(data: dict) -> None:
    _atomic_write(HISTORY_PATH, data)


def _seed_int(property_code: str, group_url: str) -> int:
    raw = f"{(property_code or '').strip().upper()}|{(group_url or '').strip()}"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12], 16)


def _strip_our_variant_markers(text: str) -> str:
    """Remove only markers this module appended — never strip original page content."""
    raw = (text or "").rstrip()
    # Strip trailing zero-width / word-joiner only lines and chars at end
    raw = re.sub(r"[\u200b\u200c\u200d\u2060]+$", "", raw)
    lines = raw.split("\n")
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        if OUR_DATE_TRAILER_RE.match(last):
            lines.pop()
            continue
        if re.fullmatch(r"[\u200b\u200c\u200d\u2060]+", last):
            lines.pop()
            continue
        break
    return "\n".join(lines).rstrip()


def _looks_like_truncated_fb_scrape(text: str) -> bool:
    """Facebook og:meta scrapes are short and often mash page title into the body."""
    t = (text or "").strip()
    if not t:
        return True
    newlines = t.count("\n")
    if len(t) < 180:
        return True
    if newlines < 4 and len(t) < 500:
        return True
    # Title/brand dumped mid-post (classic og:title + og:description mashup)
    if PAGE_BRAND_NOISE_RE.search(t) and newlines < 8:
        return True
    # Real page posts almost always include LINE / phone / many emoji lines
    has_contact = bool(re.search(r"LINE\s*:|@PTP\.|080-|064-", t, re.I))
    if not has_contact and newlines < 6:
        return True
    return False


def _looks_complete_original(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 120:
        return False
    if t.count("\n") < 3:
        return False
    return not _looks_like_truncated_fb_scrape(t) or (
        len(t) >= 300 and t.count("\n") >= 8
    )


def _rotate_hashtag_line(text: str, shift: int) -> str:
    """Reorder the last hashtag-only line — content unchanged, fingerprint changes."""
    if shift <= 0:
        return text
    lines = text.rstrip().split("\n")
    for i in range(len(lines) - 1, -1, -1):
        parts = [p for p in lines[i].split() if p]
        if len(parts) >= 2 and all(p.startswith("#") for p in parts):
            k = shift % len(parts)
            lines[i] = " ".join(parts[k:] + parts[:k])
            return "\n".join(lines)
    return text


def build_caption_variant(
    base_text: str,
    *,
    property_code: str,
    group_url: str,
    attempt: int = 0,
) -> str:
    """Keep original body intact; only micro-vary the ending for uniqueness."""
    base = _strip_our_variant_markers((base_text or "").strip())
    if not base:
        return ""

    seed = _seed_int(property_code, group_url)
    rng = random.Random(seed + attempt * 9973)

    # 1) Rotate trailing hashtags (same tags, different order)
    body = _rotate_hashtag_line(base, shift=1 + (seed + attempt) % 7)

    # 2) Trailing blank lines (1–3)
    extra_nl = 1 + ((attempt + rng.randint(0, 2)) % 3)
    out = body.rstrip() + ("\n" * extra_nl)

    # 3) Invisible unique marks (survive fingerprint; may be stripped by FB — ok as extra)
    zw = "\u200b" * (1 + ((seed + attempt) % 9))
    out = out + zw

    # 4) Soft visible trailer only when needed for higher attempts / collisions
    if attempt >= 1:
        today = datetime.now(BANGKOK).strftime("%d/%m")
        # Keep original contacts/hashtags — add a light date line after them
        out = out.rstrip("\u200b") + f"\nอัปเดต {today}" + zw

    if attempt >= 8:
        code = (property_code or "RXT").strip().upper() or "RXT"
        nonce = hashlib.sha256(f"{group_url}|{attempt}|{seed}".encode()).hexdigest()[:6]
        out = out.rstrip("\u200b") + f"\nอัปเดต {datetime.now(BANGKOK).strftime('%d/%m')} · {nonce}"
        out += "\u200b"

    return out


def _property_bucket(history: dict, property_code: str) -> dict:
    key = (property_code or "").strip().upper() or "_UNKNOWN"
    bucket = history.get(key)
    if not isinstance(bucket, dict):
        bucket = {"groups": {}, "hashes": []}
        history[key] = bucket
    bucket.setdefault("groups", {})
    bucket.setdefault("hashes", [])
    return bucket


def resolve_base_text(
    *,
    page_post_text: str = "",
    page_url: str = "",
    post_url: str = "",
    base_text: str = "",
    allow_scrape: bool = True,
) -> tuple[str, str, list[str]]:
    """
    Returns (text, source, warnings).

    source: page_original | text_th | page_scrape | post_scrape | none
    """
    warnings: list[str] = []
    page_post_text = (page_post_text or "").strip()
    page_url = (page_url or "").strip()
    post_url = (post_url or "").strip()
    base_text = (base_text or "").strip()

    # 1) Explicit full original pasted from the public Page post
    if page_post_text and _looks_complete_original(page_post_text):
        return page_post_text, "page_original", warnings
    if page_post_text:
        warnings.append("ข้อความต้นฉบับ สำหรับโพสต์กลุ่มสั้นผิดปกติ — ตรวจว่าคัดลอกครบทั้งโพสต์หรือยัง")
        return page_post_text, "page_original", warnings

    # 2) Hub Thai caption (often identical to what was posted on Page)
    if base_text and _looks_complete_original(base_text):
        warnings.append(
            "ใช้ข้อความไทยใน Hub — ถ้าไม่ตรงเพจ ให้วางต้นฉบับเต็มในช่อง「ข้อความต้นฉบับ สำหรับโพสต์กลุ่ม」"
        )
        return base_text, "text_th", warnings

    # 3) Scrape is unreliable — only accept if it looks complete AND longer than Hub text
    scraped_page = ""
    if allow_scrape and page_url.startswith("http"):
        try:
            from src.hub.scraper import fetch_page_text

            scraped_page, scrape_warnings = fetch_page_text(page_url)
            warnings.extend(scrape_warnings)
            scraped_page = (scraped_page or "").strip()
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"ดึงข้อความเพจอัตโนมัติไม่ได้: {exc}")

    if scraped_page and not _looks_like_truncated_fb_scrape(scraped_page):
        if not base_text or len(scraped_page) >= len(base_text):
            return scraped_page, "page_scrape", warnings
        warnings.append("ข้อความจากเพจสั้นกว่าใน Hub — ใช้ข้อความไทยใน Hub")
        return base_text, "text_th", warnings

    if scraped_page:
        warnings.append(
            "ดึงจากลิงก์เพจได้ไม่ครบ (Facebook ตัดข้อความ) — "
            "เปิดโพสต์เพจแล้วคัดลอกทั้งดุ้นมาวางในช่อง「ข้อความต้นฉบับ สำหรับโพสต์กลุ่ม」"
        )

    if base_text:
        if _looks_like_truncated_fb_scrape(base_text):
            warnings.append("ข้อความไทยใน Hub อาจไม่ครบ — แนะนำวางข้อความต้นฉบับ สำหรับโพสต์กลุ่ม")
        return base_text, "text_th", warnings

    if allow_scrape and post_url.startswith("http"):
        try:
            from src.hub.scraper import fetch_page_text

            scraped, scrape_warnings = fetch_page_text(post_url)
            warnings.extend(scrape_warnings)
            scraped = (scraped or "").strip()
            if scraped and not _looks_like_truncated_fb_scrape(scraped):
                return scraped, "post_scrape", warnings
            if scraped:
                warnings.append("ดึงจากโพสต์โปรไฟล์ได้ไม่ครบ")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"ดึงข้อความโพสต์โปรไฟล์ไม่ได้: {exc}")

    return "", "none", warnings


def prepare_group_caption(
    *,
    property_code: str,
    group_url: str,
    group_name: str = "",
    page_post_text: str = "",
    page_url: str = "",
    post_url: str = "",
    base_text: str = "",
    force_new: bool = False,
    allow_scrape: bool = True,
) -> dict:
    """Prepare clipboard caption: full original + light unique ending."""
    property_code = (property_code or "").strip()
    group_url = (group_url or "").strip()
    if not group_url:
        return {"ok": False, "error": "ไม่มีลิงก์กลุ่ม"}

    text, source, warnings = resolve_base_text(
        page_post_text=page_post_text,
        page_url=page_url,
        post_url=post_url,
        base_text=base_text,
        allow_scrape=allow_scrape,
    )
    if not text:
        return {
            "ok": False,
            "error": (
                "ยังไม่มี「ข้อความต้นฉบับ สำหรับโพสต์กลุ่ม」— "
                "เปิดโพสต์เพจสาธารณะ → คัดลอกทั้งดุ้น → วางในช่องนั้นแล้วกดบันทึกต้นฉบับ"
            ),
            "warnings": warnings,
            "source": source,
        }

    # Refuse to ship known-truncated scrape as if it were the page original
    if source in {"page_scrape", "post_scrape"} and _looks_like_truncated_fb_scrape(text):
        return {
            "ok": False,
            "error": (
                "ข้อความจากลิงก์เพจไม่ครบ (Facebook ไม่ให้ดึงทั้งโพสต์อัตโนมัติ) — "
                "กรุณาวางต้นฉบับเต็มในช่อง「ข้อความต้นฉบับ สำหรับโพสต์กลุ่ม」"
            ),
            "warnings": warnings,
            "source": source,
        }

    with _LOCK:
        history = _load_history()
        bucket = _property_bucket(history, property_code)
        groups: dict = bucket["groups"]
        used_hashes: list[str] = list(bucket.get("hashes") or [])
        used_set = set(used_hashes)

        entries = list(groups.get(group_url) or [])
        now = time.time()

        if not force_new and entries:
            last = entries[-1]
            age = now - float(last.get("ts") or 0)
            if age <= REUSE_WINDOW_SEC and last.get("caption"):
                return {
                    "ok": True,
                    "caption": last["caption"],
                    "hash": last.get("hash") or caption_fingerprint(last["caption"]),
                    "source": last.get("source") or source,
                    "reused": True,
                    "variant_index": int(last.get("variant_index") or 0),
                    "group_copy_count": len(entries),
                    "unique_across_property": True,
                    "base_chars": len(text),
                    "warnings": warnings
                    + ["ใช้ข้อความชุดล่าสุดของกลุ่มนี้ (กันคลิกซ้ำ)"],
                    "group_url": group_url,
                    "group_name": group_name,
                    "property_code": property_code,
                }

        start_attempt = len(entries)
        caption = ""
        fp = ""
        variant_index = start_attempt
        for i in range(MAX_ATTEMPTS):
            variant_index = start_attempt + i
            candidate = build_caption_variant(
                text,
                property_code=property_code,
                group_url=group_url,
                attempt=variant_index,
            )
            fp = caption_fingerprint(candidate)
            if fp not in used_set:
                caption = candidate
                break
        else:
            nonce = hashlib.sha256(
                f"{group_url}|{now}|{len(used_hashes)}".encode()
            ).hexdigest()[:6]
            caption = (
                _strip_our_variant_markers(text)
                + f"\nอัปเดต {datetime.now(BANGKOK).strftime('%d/%m')} · {nonce}"
            )
            fp = caption_fingerprint(caption)
            variant_index = start_attempt + MAX_ATTEMPTS

        entry = {
            "ts": now,
            "hash": fp,
            "caption": caption,
            "source": source,
            "variant_index": variant_index,
            "group_name": group_name or "",
            "preview": re.sub(r"\s+", " ", caption)[:120],
            "base_chars": len(text),
        }
        entries.append(entry)
        groups[group_url] = entries
        used_hashes.append(fp)
        bucket["hashes"] = used_hashes
        bucket["groups"] = groups
        bucket["updated_at"] = now
        _save_history(history)

        return {
            "ok": True,
            "caption": caption,
            "hash": fp,
            "source": source,
            "reused": False,
            "variant_index": variant_index,
            "group_copy_count": len(entries),
            "unique_across_property": True,
            "base_chars": len(text),
            "warnings": warnings,
            "group_url": group_url,
            "group_name": group_name,
            "property_code": property_code,
        }


def list_caption_history(property_code: str) -> dict:
    with _LOCK:
        history = _load_history()
        bucket = _property_bucket(history, property_code)
        return {
            "property_code": (property_code or "").strip().upper(),
            "total_unique": len(bucket.get("hashes") or []),
            "groups": {
                url: [
                    {
                        "hash": e.get("hash"),
                        "variant_index": e.get("variant_index"),
                        "ts": e.get("ts"),
                        "preview": e.get("preview"),
                        "source": e.get("source"),
                        "base_chars": e.get("base_chars"),
                    }
                    for e in (entries or [])
                ]
                for url, entries in (bucket.get("groups") or {}).items()
            },
        }
