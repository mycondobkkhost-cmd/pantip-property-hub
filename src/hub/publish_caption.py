"""Helpers to build no-link captions + image URL candidates for publish jobs."""

from __future__ import annotations

from typing import Any

from src.hub.group_post_publish_store import sanitize_caption_no_links
from src.hub.project_store import load_properties_cached
from src.hub.text_gen import generate_caption_variants_no_links, generate_text_no_links


def find_property_by_code(code: str) -> dict[str, Any] | None:
    want = (code or "").strip().upper()
    if not want:
        return None
    for p in load_properties_cached():
        if str(p.get("code") or "").strip().upper() == want:
            return p
    return None


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


def build_no_link_captions(code: str, *, lang: str = "th", n: int = 4) -> dict[str, Any]:
    prop = find_property_by_code(code)
    if not prop:
        return {"ok": False, "error": f"ไม่พบรหัส {code}"}
    data = property_to_text_data(prop)
    variants = generate_caption_variants_no_links(data, lang, n=n)
    if not variants:
        variants = [generate_text_no_links(data, lang, variant=0)]
    variants = [sanitize_caption_no_links(v) for v in variants if v]
    return {
        "ok": True,
        "code": data["code"],
        "caption": variants[0] if variants else "",
        "variants": variants,
        "line_cta": "LINE ID only (no URLs)",
    }


def resolve_image_urls_for_property(code: str, *, extra: list[str] | None = None) -> list[str]:
    """Prefer explicit URLs; else collect as many page photos as available (cap 12)."""
    out: list[str] = []
    for u in extra or []:
        s = str(u or "").strip()
        if s.startswith("http") and s not in out:
            out.append(s)
        elif s.startswith("/api/publish-uploads/") and s not in out:
            out.append(s)
    if out:
        return out[:12]

    prop = find_property_by_code(code)
    if not prop:
        return []
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
    # Fallback: soft newline / zero-width trailer
    trailers = ["", "\n", "\n\n", "\u200b", "\n\u200b"]
    return sanitize_caption_no_links(text + trailers[index % len(trailers)])
