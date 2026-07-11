"""Generate customer-facing listing text (TH/EN) in Pantip Property agent voice.

Never paste raw owner posts. Rebuild from structured fields + cleaned highlights.
Always end with LINE / phone CTA.
"""

from __future__ import annotations

import re

from src.hub.parser import strip_contact

# Default public contact (agent brand — not owner)
LINE_ID = "@PTP.CONDO"
LINE_URL = "https://lin.ee/RnwP2cG"
PHONE_NUT = ("คุณนัท", "080-817-2532")
PHONE_PLENG = ("คุณเพลง", "064-646-2206")

OWNER_VOICE_PATTERNS = [
    r"\[?\s*owner\s*post\s*\]?",
    r"owner\s*post",
    r"เจ้าของปล่อย(?:เช่า|ขาย)?",
    r"เจ้าของห้อง",
    r"业主",
    r"ห้ามเอเจนท์",
    r"ห้ามเอเจนต์",
    r"รบกวนทัก\s*line\s*ก่อน",
    r"ทัก\s*line\s*ก่อน",
    r"ติดต่อ\s*:\s*[^\n]+",
    r"สนใจติดต่อ[^\n]*",
    r"รับ\s*agent[^\n]*",
    r"ยินดีรับเอเจนต์[^\n]*",
    r"ยินดีรับเอเจนท์[^\n]*",
]


def _has_price(v: str | None) -> bool:
    s = str(v or "").strip()
    return bool(s) and s not in {"-", "—", "0"}


def _offer_block(rent: str, sale: str, lang: str) -> list[str]:
    lines: list[str] = []
    if _has_price(rent):
        lines.append(
            f"💰 Rental : {rent} THB/month" if lang == "en" else f"💰 Rental : {rent} บาท/เดือน"
        )
    if _has_price(sale):
        lines.append(f"💰 Sale : {sale} THB" if lang == "en" else f"💰 Sale : {sale} บาท")
    return lines


def _beds_baths(bedrooms: str) -> tuple[str, str]:
    b = bedrooms or ""
    if re.search(r"studio", b, re.I):
        return "Studio", ""
    m = re.search(r"(\d+)\s*Bed\s*(\d+)\s*Bath", b, re.I)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"(\d+)\s*ห้องนอน.*?(\d+)\s*ห้องน้ำ", b)
    if m:
        return m.group(1), m.group(2)
    m = re.search(r"(\d+)", b)
    return (m.group(1) if m else b), ""


def _spec_block(data: dict, lang: str) -> list[str]:
    lines: list[str] = []
    beds, baths = _beds_baths(data.get("bedrooms") or "")
    size = data.get("size_sqm") or ""
    floor = data.get("floor") or ""
    ptype = data.get("property_type") or "Condo"

    if lang == "en":
        if beds.lower() == "studio":
            lines.append("🛏 Studio" + (f" | 🚿 {baths} Bath" if baths else ""))
        elif beds:
            bit = f"🛏 {beds} Bed"
            if baths:
                bit += f" | 🚿 {baths} Bath"
            lines.append(bit)
        detail = []
        if size:
            detail.append(f"📐 {size} sqm")
        if floor:
            detail.append(f"🏢 Floor {floor}")
        if detail:
            lines.append(" | ".join(detail))
        if ptype:
            lines.append(f"🏷 {ptype}")
        return lines

    if beds.lower() == "studio":
        lines.append("🛏 Studio" + (f" | 🚿 {baths} ห้องน้ำ" if baths else ""))
    elif beds:
        bit = f"🛏 {beds} ห้องนอน"
        if baths:
            bit += f" | 🚿 {baths} ห้องน้ำ"
        lines.append(bit)
    detail = []
    if size:
        detail.append(f"📐 {size} ตร.ม.")
    if floor:
        detail.append(f"🏢 ชั้น {floor}")
    if detail:
        lines.append(" | ".join(detail))
    return lines


def _sanitize_source(text: str) -> str:
    out = strip_contact(text or "")
    for pat in OWNER_VOICE_PATTERNS:
        out = re.sub(pat, " ", out, flags=re.I)
    out = re.sub(r"[🔥📌📍✅🎉😍❤️👇👉←→]+", "\n", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{2,}", "\n", out)
    return out.strip()


def _extract_highlights(data: dict, lang: str, limit: int = 5) -> list[str]:
    """Pull short feature bullets from cleaned source — never owner voice."""
    source = _sanitize_source(data.get("raw_text") or "")
    if not source:
        return []

    bullets: list[str] = []
    for ln in source.splitlines():
        ln = ln.strip(" -•*|")
        if len(ln) < 8 or len(ln) > 90:
            continue
        low = ln.lower()
        if any(
            x in low
            for x in (
                "owner",
                "เจ้าของ",
                "line",
                "โทร",
                "ติดต่อ",
                "pantip",
                "http",
                "agent",
                "เอเจน",
                "เอเจนต์",
                "บาท/เดือน",
                "for rent",
                "for sale",
                "ขาย/เช่า",
                "ให้เช่าคอนโด",
                "ประกาศ",
            )
        ):
            continue
        # skip marketing opener / project-title-only lines
        if re.match(r"^(ขาย|เช่า|ให้เช่า|พร้อมอยู่)", ln):
            continue
        if "แมนชั่น" in ln and "ห้อง" not in ln and len(ln) < 40:
            continue
        if re.fullmatch(r"[\d,.\s]+", ln):
            continue
        if ln not in bullets:
            bullets.append(ln)
        if len(bullets) >= limit:
            break

    # fallback structured highlights
    if not bullets:
        if lang == "en":
            if data.get("bedrooms"):
                bullets.append(f"{data['bedrooms']} — ready to move in")
            if data.get("size_sqm"):
                bullets.append(f"Size {data['size_sqm']} sqm")
        else:
            if data.get("bedrooms"):
                bullets.append(f"{data['bedrooms']} พร้อมเข้าอยู่")
            if data.get("size_sqm"):
                bullets.append(f"พื้นที่ {data['size_sqm']} ตร.ม.")
    return bullets[:limit]


def _nearby_block(transit: list[str], lang: str) -> list[str]:
    if not transit:
        return []
    lines = ["📍 Nearby" if lang == "en" else "📍 Nearby"]
    for t in transit[:5]:
        label = t.strip()
        if not label:
            continue
        if re.search(r"BTS|MRT|ARL|SRT", label, re.I):
            lines.append(f"🚆 {label}")
        else:
            lines.append(f"📍 {label}")
    return lines


def _hashtags(project: str) -> str:
    base = re.sub(r"\(.*?\)", "", project or "")
    # EN token
    en = re.sub(r"[^A-Za-z0-9]+", "", base)
    th = re.sub(r"[^ก-๙0-9]+", "", project or "")
    tags = []
    if en:
        tags.append(f"#{en}")
    if th and th != en:
        tags.append(f"#{th}")
    tags.append("#คอนโดให้เช่า")
    tags.append("#PantipProperty")
    return " ".join(t for t in tags if t)


def _contact_footer(lang: str) -> list[str]:
    if lang == "en":
        return [
            f"📲 LINE : {LINE_ID}  →  {LINE_URL}",
            f"📞 {PHONE_NUT[0]} : {PHONE_NUT[1]}",
            f"📞 {PHONE_PLENG[0]} : {PHONE_PLENG[1]}",
            "",
            "Add LINE for viewing / more info 🙏",
        ]
    return [
        f"📲 LINE : {LINE_ID} คลิก {LINE_URL}",
        f"📞 {PHONE_NUT[0]} : {PHONE_NUT[1]}",
        f"📞 {PHONE_PLENG[0]} : {PHONE_PLENG[1]}",
        "",
        "สนใจนัดชม / ขอรายละเอียด แอดไลน์ได้เลยครับ 🙏",
    ]


def _headline(data: dict, lang: str) -> str:
    project = (data.get("project_name") or "Condo").strip()
    rent = data.get("rent_price") or ""
    sale = data.get("sale_price") or ""
    if lang == "en":
        if _has_price(rent) and not _has_price(sale):
            return f"🌟 Ready to move in · For Rent"
        if _has_price(sale) and not _has_price(rent):
            return f"🌟 For Sale"
        return "🌟 For Rent / Sale"
    if _has_price(rent) and not _has_price(sale):
        return "🌟 พร้อมอยู่ · ให้เช่า"
    if _has_price(sale) and not _has_price(rent):
        return "🌟 ขาย"
    return "🌟 ให้เช่า / ขาย"


def generate_text(data: dict, lang: str = "th") -> str:
    project = (data.get("project_name") or "").strip() or "Condo"
    transit = data.get("transit_tags") or []
    code = (data.get("code") or "RXT????").strip()
    prefix = (data.get("code_prefix") or "RXT").strip().upper()
    highlights = _extract_highlights(data, lang)

    lines: list[str] = [
        f"🏢 {project}",
        _headline(data, lang),
    ]
    lines.extend(_offer_block(data.get("rent_price", ""), data.get("sale_price", ""), lang))
    lines.extend(_spec_block(data, lang))
    lines.append("🛋 Fully Furnished พร้อมเข้าอยู่" if lang != "en" else "🛋 Fully Furnished — ready to move in")

    if highlights:
        lines.append("")
        lines.append("✨ Highlights" if lang == "en" else "✨ Highlights")
        for h in highlights:
            lines.append(f"• {h}")

    nearby = _nearby_block(transit, lang)
    if nearby:
        lines.append("")
        lines.extend(nearby)

    lines.append("")
    lines.append("🤝 Co-Agent Welcome")
    lines.append(f"📌 Property Code : #{code}")
    if prefix == "COA":
        lines.append("🏷 Co-agent listing" if lang == "en" else "🏷 รายการโคเอเจนต์")

    lines.append("")
    lines.extend(_contact_footer(lang))
    lines.append("")
    lines.append(_hashtags(project))

    # safety: never leak owner-post wording
    text = "\n".join(ln for ln in lines if ln is not None)
    text = re.sub(r"(?i)owner\s*post", "", text)
    text = re.sub(r"เจ้าของปล่อย", "", text)
    return text.strip() + "\n"
