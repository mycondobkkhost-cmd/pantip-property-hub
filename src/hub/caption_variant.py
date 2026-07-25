"""Unique group-post captions from a public page (or Hub) base text.

Goals:
- Same property → different caption per Facebook group
- Same group again (repost) → new caption, still unique vs all prior copies
- Accidental double-click → reuse last caption for that group (short window)
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

# Reuse last caption for same group if clicked again within this window (seconds)
REUSE_WINDOW_SEC = 120
MAX_ATTEMPTS = 48

BULLETS = ("•", "·", "-", "▪", "●")
CTA_VARIANTS = (
    "สนใจสอบถามเพิ่มเติมได้ครับ",
    "สนใจทักสอบถามได้ครับ",
    "สอบถามรายละเอียดเพิ่มเติมได้ครับ",
    "ทักมาสอบถามได้เลยครับ",
    "สนใจรายละเอียดเพิ่ม คุยได้ครับ",
)
HASHTAG_SETS = (
    ("#คอนโดให้เช่า", "#อสังหา"),
    ("#คอนโดกรุงเทพ", "#ให้เช่า"),
    ("#เช่าคอนโด", "#BangkokCondo"),
    ("#คอนโดใกล้รถไฟฟ้า", "#อสังหาริมทรัพย์"),
    ("#คอนโด", "#เช่าขาย"),
)


def caption_fingerprint(text: str) -> str:
    """Normalize whitespace then hash — catches near-identical spam copies."""
    norm = re.sub(r"\s+", " ", (text or "").strip())
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


def _split_blocks(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _replace_bullets(text: str, bullet: str) -> str:
    out = text
    for b in BULLETS:
        if b != bullet:
            out = out.replace(b, bullet)
    # common list prefixes
    out = re.sub(r"(?m)^(\s*)[-*]\s+", rf"\1{bullet} ", out)
    return out


def _soft_swap_tail(blocks: list[str], mode: int) -> list[str]:
    if len(blocks) < 2:
        return blocks
    out = list(blocks)
    if mode % 3 == 1 and len(out) >= 2:
        out[-1], out[-2] = out[-2], out[-1]
    elif mode % 3 == 2 and len(out) >= 3:
        out[-3:] = [out[-2], out[-1], out[-3]]
    return out


def _strip_old_trailers(text: str) -> str:
    """Remove trailers we may have appended on earlier variants."""
    lines = text.rstrip().split("\n")
    while lines:
        last = lines[-1].strip()
        if not last:
            lines.pop()
            continue
        if last.startswith("อัปเดต ") and len(last) <= 24:
            lines.pop()
            continue
        if last.startswith("#") and " " not in last[1:40] and len(last) <= 80:
            # hashtag-only last line (or space-separated hashtags)
            if all(p.startswith("#") for p in last.split() if p):
                lines.pop()
                continue
        if last in CTA_VARIANTS:
            lines.pop()
            continue
        break
    return "\n".join(lines).rstrip()


def build_caption_variant(
    base_text: str,
    *,
    property_code: str,
    group_url: str,
    attempt: int = 0,
) -> str:
    """Build a human-readable micro-variant of base_text."""
    base = _strip_old_trailers((base_text or "").strip())
    if not base:
        return ""

    rng = random.Random(_seed_int(property_code, group_url) + attempt * 9973)
    blocks = _split_blocks(base)
    blocks = _soft_swap_tail(blocks, attempt + rng.randint(0, 2))

    bullet = BULLETS[(attempt + rng.randint(0, 4)) % len(BULLETS)]
    gap = "\n\n" if (attempt + rng.randint(0, 1)) % 2 == 0 else "\n\n\n"
    body = gap.join(_replace_bullets(b, bullet) for b in blocks)

    today = datetime.now(BANGKOK).strftime("%d/%m")
    cta = CTA_VARIANTS[(attempt + rng.randint(0, len(CTA_VARIANTS) - 1)) % len(CTA_VARIANTS)]
    tags = HASHTAG_SETS[(attempt + rng.randint(0, len(HASHTAG_SETS) - 1)) % len(HASHTAG_SETS)]
    tag_line = " ".join(tags)

    # Always append a light unique trailer stack (readable, not spammy)
    trailers = [cta, f"อัปเดต {today}", tag_line]
    # Rotate which trailers appear / order by attempt
    if attempt % 4 == 0:
        chosen = [trailers[0], trailers[2]]
    elif attempt % 4 == 1:
        chosen = [trailers[1], trailers[0], trailers[2]]
    elif attempt % 4 == 2:
        chosen = [trailers[2], trailers[0]]
    else:
        chosen = [trailers[0], trailers[1]]

    # Guaranteed uniqueness fallback marker (tiny, only when attempt high)
    if attempt >= 8:
        code = (property_code or "RXT").strip().upper() or "RXT"
        chosen.append(f"รหัส {code}-{attempt}")

    return body.rstrip() + "\n\n" + "\n".join(chosen)


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
    page_url: str = "",
    post_url: str = "",
    base_text: str = "",
    allow_scrape: bool = True,
) -> tuple[str, str, list[str]]:
    """
    Prefer public page post text, then Hub text, then profile post scrape.

    Returns (text, source, warnings).
    source: page_scrape | text_th | post_scrape | none
    """
    warnings: list[str] = []
    page_url = (page_url or "").strip()
    post_url = (post_url or "").strip()
    base_text = (base_text or "").strip()

    if allow_scrape and page_url.startswith("http"):
        try:
            from src.hub.scraper import fetch_page_text

            scraped, scrape_warnings = fetch_page_text(page_url)
            warnings.extend(scrape_warnings)
            scraped = (scraped or "").strip()
            # Facebook og:description is often truncated; prefer Hub text if much longer
            if scraped and (not base_text or len(scraped) >= 80 or len(scraped) >= len(base_text) * 0.6):
                if base_text and len(base_text) > len(scraped) + 40:
                    warnings.append(
                        "ข้อความจากเพจอาจไม่ครบ — ใช้ข้อความไทยใน Hub เป็นหลัก"
                    )
                    return base_text, "text_th", warnings
                return scraped, "page_scrape", warnings
            if scraped and base_text:
                warnings.append("ข้อความจากเพจสั้นเกินไป — ใช้ข้อความไทยใน Hub")
                return base_text, "text_th", warnings
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"ดึงข้อความเพจไม่ได้: {exc}")

    if base_text:
        return base_text, "text_th", warnings

    if allow_scrape and post_url.startswith("http"):
        try:
            from src.hub.scraper import fetch_page_text

            scraped, scrape_warnings = fetch_page_text(post_url)
            warnings.extend(scrape_warnings)
            scraped = (scraped or "").strip()
            if scraped:
                return scraped, "post_scrape", warnings
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"ดึงข้อความโพสต์โปรไฟล์ไม่ได้: {exc}")

    return "", "none", warnings


def prepare_group_caption(
    *,
    property_code: str,
    group_url: str,
    group_name: str = "",
    page_url: str = "",
    post_url: str = "",
    base_text: str = "",
    force_new: bool = False,
    allow_scrape: bool = True,
) -> dict:
    """
    Prepare a clipboard-ready caption unique across groups for this property.

    Returns dict with caption, hash, source, reused, variant_index, warnings, error?
    """
    property_code = (property_code or "").strip()
    group_url = (group_url or "").strip()
    if not group_url:
        return {"ok": False, "error": "ไม่มีลิงก์กลุ่ม"}

    text, source, warnings = resolve_base_text(
        page_url=page_url,
        post_url=post_url,
        base_text=base_text,
        allow_scrape=allow_scrape,
    )
    if not text:
        return {
            "ok": False,
            "error": (
                "ยังไม่มีข้อความหลักจากเพจสาธารณะ — "
                "ใส่ลิงก์โพสต์เพจ หรือสร้าง/วางข้อความไทยใน Hub ก่อน"
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
            # Absolute fallback — append unique nonce
            nonce = hashlib.sha256(f"{group_url}|{now}|{len(used_hashes)}".encode()).hexdigest()[:6]
            caption = text.rstrip() + f"\n\nอัปเดต {datetime.now(BANGKOK).strftime('%d/%m')} · {nonce}"
            fp = caption_fingerprint(caption)
            variant_index = start_attempt + MAX_ATTEMPTS

        entry = {
            "ts": now,
            "hash": fp,
            "caption": caption,
            "source": source,
            "variant_index": variant_index,
            "group_name": group_name or "",
            "preview": re.sub(r"\s+", " ", caption)[:100],
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
                    }
                    for e in (entries or [])
                ]
                for url, entries in (bucket.get("groups") or {}).items()
            },
        }
