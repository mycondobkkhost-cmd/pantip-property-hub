"""Helpers to build no-link captions + image URL candidates for publish jobs."""

from __future__ import annotations

from typing import Any

from src.hub.group_post_publish_store import sanitize_caption_no_links
from src.hub.project_store import load_properties_cached
from src.hub.property_resolve import (
    ERROR_AMBIGUOUS,
    resolve_for_action,
    resolve_by_code,
)
from src.hub.text_gen import generate_caption_variants_no_links, generate_text_no_links


def find_property_by_code(code: str) -> dict[str, Any] | None:
    """Return property only when code is unique — never first-of-many."""
    res = resolve_by_code(load_properties_cached(), code, allow_ambiguous=False)
    return res.record if res.ok else None


def find_properties_by_code(code: str) -> list[dict[str, Any]]:
    """Human search — all matches for a code."""
    res = resolve_by_code(load_properties_cached(), code, allow_ambiguous=True)
    if res.status == "ambiguous" and res.candidates:
        props = load_properties_cached()
        ids = {c.get("property_id") for c in res.candidates}
        return [p for p in props if str(p.get("id") or "") in ids]
    if res.ok and res.record:
        return [res.record]
    return []


def resolve_property_for_publish(
    *,
    property_id: str = "",
    property_code: str = "",
) -> dict[str, Any]:
    res = resolve_for_action(
        load_properties_cached(),
        property_id=property_id,
        property_code=property_code,
    )
    if res.ok and res.record:
        return {"ok": True, "property": res.record}
    out = res.to_api_dict()
    out["ok"] = False
    return out


def property_to_text_data(prop: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": prop.get("code") or "",
        "code_prefix": prop.get("code_prefix") or "",
        "project_name": prop.get("project_name") or "",
        "rent_price": prop.get("rent_price") or "",
        "sale_price": prop.get("sale_price") or "",
        "bedrooms": prop.get("bedrooms") or "",
        "size_sqm": prop.get("size_sqm") or "",
        "floor": prop.get("floor") or "",
        "transit_tags": prop.get("transit_from_sheet") or prop.get("transit_tags") or [],
        "notes": prop.get("notes") or "",
    }


def build_no_link_captions(
    code: str,
    *,
    lang: str = "th",
    n: int = 4,
    property_id: str = "",
) -> dict[str, Any]:
    resolved = resolve_property_for_publish(property_id=property_id, property_code=code)
    if not resolved.get("ok"):
        if resolved.get("error_code") == ERROR_AMBIGUOUS:
            return {
                "ok": False,
                "error": resolved.get("error"),
                "error_code": ERROR_AMBIGUOUS,
                "candidates": resolved.get("candidates") or [],
                "match_count": resolved.get("match_count") or 0,
            }
        return {"ok": False, "error": resolved.get("error") or f"ไม่พบรหัส {code}"}
    prop = resolved["property"]
    data = property_to_text_data(prop)
    variants = generate_caption_variants_no_links(data, lang, n=n)
    if not variants:
        variants = [generate_text_no_links(data, lang, variant=0)]
    variants = [sanitize_caption_no_links(v) for v in variants if v]
    return {
        "ok": True,
        "property_id": prop.get("id") or "",
        "code": data["code"],
        "caption": variants[0] if variants else "",
        "variants": variants,
        "line_cta": "LINE ID only (no URLs)",
    }


def resolve_image_urls_for_property(
    code: str,
    *,
    extra: list[str] | None = None,
    property_id: str = "",
) -> list[str]:
    """Prefer explicit URLs; else collect as many page photos as available (cap 12)."""
    out: list[str] = []
    for u in extra or []:
        s = str(u or "").strip()
        if s.startswith("http") and s not in out:
            out.append(s)
        elif s.startswith("/api/publish-uploads/") and s not in out:
            out.append(s)
    if out:
        try:
            from src.hub.scraper import _dedupe_image_urls

            httpish = [x for x in out if x.startswith("http")]
            local = [x for x in out if x.startswith("/api/")]
            return (local + _dedupe_image_urls(httpish, limit=12))[:12]
        except Exception:  # noqa: BLE001
            return out[:12]

    resolved = resolve_property_for_publish(property_id=property_id, property_code=code)
    if not resolved.get("ok"):
        return []
    prop = resolved["property"]
    candidates = [
        str(prop.get("post_pages_url") or "").strip(),
        str(prop.get("source_url") or "").strip(),
        str(prop.get("post_url") or "").strip(),
    ]
    try:
        from src.hub.scraper import fetch_preview_images
    except Exception:  # noqa: BLE001
        return []
    for page in candidates:
        if not page.startswith("http"):
            continue
        try:
            imgs, _warn = fetch_preview_images(page, limit=12)
        except Exception:  # noqa: BLE001
            continue
        for img in imgs:
            if img.startswith("http") and img not in out:
                out.append(img)
        if out:
            break
    try:
        from src.hub.scraper import _dedupe_image_urls

        return _dedupe_image_urls(out, limit=12)
    except Exception:  # noqa: BLE001
        return out[:12]


def micro_vary_caption(base: str, *, property_code: str = "", group_url: str = "", index: int = 0) -> str:
    """Light per-group variation to reduce identical spam fingerprints."""
    text = sanitize_caption_no_links(base)
    if not text:
        return ""
    try:
        from src.hub.caption_variant import build_caption_variant

        varied = build_caption_variant(
            text,
            property_code=property_code or "X",
            group_url=group_url or f"group-{index}",
            attempt=index,
        )
        if varied and str(varied).strip():
            return sanitize_caption_no_links(str(varied))
    except Exception:  # noqa: BLE001
        pass
    trailers = ["", "\n", "\n\n", "\u200b", "\n\u200b"]
    return sanitize_caption_no_links(text + trailers[index % len(trailers)])


def fetch_publish_bundle(
    code: str,
    *,
    allow_scrape: bool = True,
    property_id: str = "",
) -> dict[str, Any]:
    """Pull caption + page photos for a property (prefer Page post original)."""
    resolved = resolve_property_for_publish(property_id=property_id, property_code=code)
    if not resolved.get("ok"):
        return {
            "ok": False,
            "error": resolved.get("error") or f"ไม่พบรหัส {(code or '').strip().upper()}",
            "error_code": resolved.get("error_code") or "",
            "candidates": resolved.get("candidates") or [],
        }
    prop = resolved["property"]

    page_url = str(prop.get("post_pages_url") or "").strip()
    post_url = str(prop.get("source_url") or prop.get("post_url") or "").strip()
    page_post_text = str(prop.get("page_post_text") or "").strip()
    base_text = str(prop.get("text_th") or "").strip()

    warnings: list[str] = []
    source = "none"
    text = ""
    try:
        from src.hub.caption_variant import resolve_base_text

        text, source, scrape_warnings = resolve_base_text(
            page_post_text=page_post_text,
            page_url=page_url,
            post_url=post_url,
            base_text=base_text,
            allow_scrape=bool(allow_scrape),
        )
        warnings.extend([str(w) for w in (scrape_warnings or []) if w])
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"ดึงข้อความไม่ได้: {exc}")
        text = page_post_text or base_text
        source = "page_original" if page_post_text else ("text_th" if base_text else "none")

    if (not text or source == "none") and allow_scrape:
        try:
            from src.hub.scraper import fetch_page_text

            for url, label in ((page_url, "page_scrape"), (post_url, "post_scrape")):
                if not str(url).startswith("http"):
                    continue
                scraped, scrape_warnings = fetch_page_text(url)
                warnings.extend([str(w) for w in (scrape_warnings or []) if w])
                scraped = (scraped or "").strip()
                if len(scraped) >= 40:
                    text = scraped
                    source = label
                    warnings.append(
                        "ข้อความจากเพจอาจไม่ครบ (Facebook ตัด) — ตรวจก่อนโพส หรือวางต้นฉบับเอง"
                    )
                    break
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"ดึงข้อความเพจซ้ำไม่ได้: {exc}")

    caption = sanitize_caption_no_links(text) if text else ""
    used_generated = False
    if not caption:
        gen = build_no_link_captions(
            str(prop.get("code") or code),
            n=1,
            property_id=str(prop.get("id") or property_id or ""),
        )
        if not gen.get("ok"):
            return gen
        caption = str(gen.get("caption") or "").strip()
        used_generated = bool(caption)
        if caption:
            source = "generated"
            warnings.append("ไม่มีข้อความจากโพสเพจ — สร้างแคปชันอัตโนมัติแทน")

    image_urls = resolve_image_urls_for_property(
        str(prop.get("code") or code),
        property_id=str(prop.get("id") or property_id or ""),
    )
    if not image_urls:
        warnings.append("ยังไม่พบรูปจากโพสเพจ — อัปเองในขั้นรูปได้")
    if not page_url and not post_url:
        warnings.append("ทรัพย์นี้ยังไม่มีลิงก์โพสเพจ/ต้นโพส")

    return {
        "ok": True,
        "property_id": str(prop.get("id") or ""),
        "code": str(prop.get("code") or code).strip().upper(),
        "caption": caption,
        "image_urls": image_urls,
        "image_count": len(image_urls),
        "source": source,
        "used_generated": used_generated,
        "page_url": page_url,
        "post_url": post_url,
        "has_page_url": bool(page_url.startswith("http")),
        "warnings": warnings,
    }
