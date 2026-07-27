"""Generate customer-facing listing text (TH/EN) in Pantip Property agent voice.

Never paste raw owner posts. Rebuild from structured fields + cleaned highlights.
Always end with LINE / phone CTA.

English captions must be English — Thai source highlights are translated or dropped
(never dumped raw into the EN panel).
"""

from __future__ import annotations

import os
import re

from src.hub.parser import strip_contact

# Default public contact (agent brand — not owner)
LINE_ID = "@PTP.CONDO"
LINE_URL = "https://lin.ee/RnwP2cG"
PHONE_NUT = ("คุณนัท", "080-817-2532")
PHONE_PLENG = ("คุณเพลง", "064-646-2206")
PHONE_NUT_EN = ("Nat", "080-817-2532")
PHONE_PLENG_EN = ("Pleng", "064-646-2206")

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

_THAI_RE = re.compile(r"[\u0E00-\u0E7F]")

# Common listing phrases → English (offline, no API required)
_PHRASE_EN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"ห้องพร้อมเข้าอยู่|พร้อมเข้าอยู่|พร้อมอยู่", re.I), "Ready to move in"),
    (re.compile(r"เฟอร์นิเจอร์ครบ|ตกแต่งครบ|Fully\s*Furnished", re.I), "Fully furnished"),
    (re.compile(r"เครื่องใช้ไฟฟ้าครบ", re.I), "Full electrical appliances"),
    (re.compile(r"แอร์\s*(\d+)\s*ตัว", re.I), r"\1 air-conditioner(s)"),
    (re.compile(r"แอร์", re.I), "Air-conditioning"),
    (re.compile(r"วิวสวย|วิวโล่ง|วิวเมือง", re.I), "Nice view"),
    (re.compile(r"วิวสระ", re.I), "Pool view"),
    (re.compile(r"ห้องมุม", re.I), "Corner unit"),
    (re.compile(r"ห้องกว้าง", re.I), "Spacious room"),
    (re.compile(r"ครัวแยก|ครัวปิด", re.I), "Separate kitchen"),
    (re.compile(r"ซักผ้า(?:เครื่อง)?|เครื่องซักผ้า", re.I), "Washing machine"),
    (re.compile(r"ตู้เย็น", re.I), "Refrigerator"),
    (re.compile(r"ไมโครเวฟ", re.I), "Microwave"),
    (re.compile(r"น้ำ(?:อุ่น|ร้อน)", re.I), "Water heater"),
    (re.compile(r"ที่จอดรถ|มีที่จอด", re.I), "Parking available"),
    (re.compile(r"สระว่ายน้ำ|มีสระ", re.I), "Swimming pool"),
    (re.compile(r"ฟิตเนส|fitness", re.I), "Fitness"),
    (re.compile(r"ใกล้\s*(BTS|MRT|ARL)", re.I), r"Near \1"),
    (re.compile(r"เดินถึง\s*(BTS|MRT)", re.I), r"Walking distance to \1"),
    (re.compile(r"เดินทางสะดวก", re.I), "Convenient location"),
    (re.compile(r"เงียบสงบ", re.I), "Quiet area"),
    (re.compile(r"ปลอดภัย", re.I), "Secure building"),
    (re.compile(r"สัตว์เลี้ยง(?:ได้|เข้าอยู่ได้)?", re.I), "Pet-friendly"),
    (re.compile(r"ห้ามสัตว์เลี้ยง", re.I), "No pets"),
    (re.compile(r"ห้องใหม่|ตกแต่งใหม่|รีโนเวท", re.I), "Newly renovated"),
    (re.compile(r"ห้องโล่ง", re.I), "Open-plan layout"),
    (re.compile(r"ระเบียง(?:กว้าง)?", re.I), "Balcony"),
    (re.compile(r"แสงธรรมชาติ", re.I), "Natural light"),
]

_PLACE_EN = {
    "ทองหล่อ": "Thonglor",
    "เอกมัย": "Ekkamai",
    "พร้อมพงษ์": "Phrom Phong",
    "อโศก": "Asoke",
    "สุขุมวิท": "Sukhumvit",
    "อ่อนนุช": "On Nut",
    "บางนา": "Bang Na",
    "ลาดพร้าว": "Lat Phrao",
    "รัชดา": "Ratchada",
    "พระราม 9": "Rama 9",
    "พระราม9": "Rama 9",
    "สาทร": "Sathorn",
    "สีลม": "Silom",
    "อารีย์": "Ari",
    "พญาไท": "Phaya Thai",
    "เพชรบุรี": "Phetchaburi",
    "ชิดลม": "Chidlom",
    "นานา": "Nana",
    "พระโขนง": "Phra Khanong",
    "ปุณณวิถี": "Punnawithi",
    "รามคำแหง": "Ramkhamhaeng",
    "ห้วยขวาง": "Huai Khwang",
    "วัฒนา": "Wattana",
    "คลองเตย": "Khlong Toei",
    "ซอย": "Soi",
}


def _has_price(v: str | None) -> bool:
    s = str(v or "").strip()
    return bool(s) and s not in {"-", "—", "0"}


def _contains_thai(text: str) -> bool:
    return bool(_THAI_RE.search(text or ""))


def _thai_ratio(text: str) -> float:
    s = text or ""
    if not s:
        return 0.0
    thai = len(_THAI_RE.findall(s))
    letters = len(re.findall(r"[A-Za-z\u0E00-\u0E7F]", s))
    if not letters:
        return 0.0
    return thai / letters


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


def _is_noise_highlight(ln: str) -> bool:
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
            "ค่าเช่า",
            "ราคาขาย",
            "ค่าส่วนกลาง",
        )
    ):
        return True
    if re.search(r"💰|฿", ln) and re.search(r"\d", ln):
        return True
    if re.match(r"^(ขาย|เช่า|ให้เช่า|พร้อมอยู่)", ln):
        return True
    if "แมนชั่น" in ln and "ห้อง" not in ln and len(ln) < 40:
        return True
    if re.fullmatch(r"[\d,.\s]+", ln):
        return True
    return False


def _romanize_places(text: str) -> str:
    out = text
    # Longer keys first
    for th, en in sorted(_PLACE_EN.items(), key=lambda x: -len(x[0])):
        out = out.replace(th, en)
    out = re.sub(r"ซอย", "Soi ", out)
    out = re.sub(r"ถนน", "Road ", out)
    out = re.sub(r"ใกล้", "Near ", out)
    out = re.sub(r"\s+", " ", out).strip()
    # Fix glued tokens like SoiSukhumvit → Soi Sukhumvit
    out = re.sub(r"(Soi|Road|Near)([A-Z])", r"\1 \2", out)
    return out


def _translate_highlight_offline(ln: str) -> str | None:
    """Best-effort Thai → English for amenity bullets. None = drop."""
    raw = (ln or "").strip(" -•*|")
    if not raw:
        return None
    if not _contains_thai(raw):
        return raw

    # Location / soi lines → romanize place names
    if re.search(r"ซอย|ถนน|ใกล้|BTS|MRT|ARL", raw, re.I) or any(
        p in raw for p in _PLACE_EN
    ):
        roman = _romanize_places(raw)
        if not _contains_thai(roman) or _thai_ratio(roman) < 0.25:
            return roman.strip(" -•|,")
        # Keep BTS/MRT station lines even if Thai station name remains
        if re.search(r"\b(BTS|MRT|ARL)\b", roman, re.I):
            return roman.strip()

    # Phrase replacements (may leave leftovers)
    out = raw
    matched = False
    for pat, repl in _PHRASE_EN:
        if pat.search(out):
            matched = True
            out = pat.sub(repl, out)
    out = _romanize_places(out)
    out = re.sub(r"\s+", " ", out).strip(" -•|,")

    if matched and _thai_ratio(out) < 0.35:
        # Strip leftover Thai fragments
        out = _THAI_RE.sub(" ", out)
        out = re.sub(r"\s+", " ", out).strip(" -•|,")
        return out or None

    # Mostly Thai and no useful mapping → drop (never dump Thai into EN)
    if _thai_ratio(out) >= 0.35:
        return None
    return out or None


def _openai_translate_bullets(bullets: list[str]) -> list[str] | None:
    """Optional OpenAI polish when key is set. Fail soft → None."""
    if not bullets:
        return []
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    flag = (os.environ.get("HUB_EN_TRANSLATE") or "1").strip().lower()
    if not key or flag in {"0", "false", "no", "off"}:
        return None
    # Only call API if something still looks Thai (shouldn't after offline filter)
    if not any(_contains_thai(b) for b in bullets):
        return None
    try:
        from openai import OpenAI

        model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini"
        client = OpenAI(api_key=key)
        numbered = "\n".join(f"{i+1}. {b}" for i, b in enumerate(bullets))
        completion = client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=400,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate condo listing highlight bullets into natural English. "
                        "Return the same number of lines, one bullet per line, no numbering, "
                        "no quotes. Keep BTS/MRT station names. Do not add prices or contact info."
                    ),
                },
                {"role": "user", "content": numbered},
            ],
            timeout=12.0,
        )
        text = (completion.choices[0].message.content or "").strip()
        if not text:
            return None
        lines = [re.sub(r"^[\d\.\)\-•\s]+", "", ln).strip() for ln in text.splitlines()]
        lines = [ln for ln in lines if ln]
        if len(lines) >= max(1, len(bullets) - 1):
            return lines[: len(bullets)]
    except Exception as exc:  # noqa: BLE001
        print(f"[hub] EN highlight translate skipped: {exc}")
    return None


def _structured_en_highlights(data: dict, limit: int = 5) -> list[str]:
    bullets: list[str] = []
    beds = (data.get("bedrooms") or "").strip()
    if beds:
        bullets.append(f"{beds} — ready to move in")
    size = data.get("size_sqm") or ""
    if size:
        bullets.append(f"Size {size} sqm")
    floor = data.get("floor") or ""
    if floor:
        bullets.append(f"Floor {floor}")
    zones = data.get("zone_tags") or data.get("zones") or []
    if isinstance(zones, str):
        zones = [z.strip() for z in zones.split(",") if z.strip()]
    if zones:
        zlabel = ", ".join(_romanize_places(str(z)) for z in zones[:3])
        bullets.append(f"Location: {zlabel}")
    transit = data.get("transit_tags") or []
    if transit:
        bullets.append(f"Near {transit[0]}")
    bullets.append("Fully furnished")
    # unique
    seen: set[str] = set()
    out: list[str] = []
    for b in bullets:
        k = b.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(b)
        if len(out) >= limit:
            break
    return out


def _extract_highlights(data: dict, lang: str, limit: int = 5) -> list[str]:
    """Pull short feature bullets from cleaned source — never owner voice."""
    source = _sanitize_source(data.get("raw_text") or "")
    candidates: list[str] = []
    if source:
        for ln in source.splitlines():
            ln = ln.strip(" -•*|")
            if len(ln) < 8 or len(ln) > 90:
                continue
            if _is_noise_highlight(ln):
                continue
            if ln not in candidates:
                candidates.append(ln)
            if len(candidates) >= limit + 3:
                break

    if lang != "en":
        bullets = candidates[:limit]
        if not bullets:
            if data.get("bedrooms"):
                bullets.append(f"{data['bedrooms']} พร้อมเข้าอยู่")
            if data.get("size_sqm"):
                bullets.append(f"พื้นที่ {data['size_sqm']} ตร.ม.")
        return bullets[:limit]

    # English: translate or drop — never leave Thai bullets
    translated: list[str] = []
    for ln in candidates:
        en = _translate_highlight_offline(ln)
        if not en:
            continue
        if _thai_ratio(en) >= 0.2:
            en = _THAI_RE.sub(" ", en)
            en = re.sub(r"\s+", " ", en).strip(" -•|,")
        if en and _thai_ratio(en) < 0.15 and en not in translated:
            translated.append(en)
        if len(translated) >= limit:
            break

    polished = _openai_translate_bullets(translated)
    if polished:
        translated = [b for b in polished if b and not _contains_thai(b)][:limit]

    # Final safety: drop any remaining Thai
    translated = [b for b in translated if b and _thai_ratio(b) < 0.15][:limit]

    if len(translated) < 2:
        # Prefer structured English over empty / Thai leftovers
        return _structured_en_highlights(data, limit)
    return translated[:limit]


def _nearby_block(transit: list[str], lang: str) -> list[str]:
    if not transit:
        return []
    lines = ["📍 Nearby"]
    for t in transit[:5]:
        label = str(t or "").strip()
        if not label:
            continue
        if lang == "en":
            label = _romanize_places(label)
        if re.search(r"BTS|MRT|ARL|SRT", label, re.I):
            lines.append(f"🚆 {label}")
        else:
            lines.append(f"📍 {label}")
    return lines


def _hashtags(project: str, lang: str = "th") -> str:
    base = re.sub(r"\(.*?\)", "", project or "")
    en = re.sub(r"[^A-Za-z0-9]+", "", base)
    tags = []
    if en:
        tags.append(f"#{en}")
    if lang == "en":
        tags.append("#CondoForRent")
        tags.append("#BangkokCondo")
        tags.append("#PantipProperty")
    else:
        th = re.sub(r"[^ก-๙0-9]+", "", project or "")
        if th and th != en:
            tags.append(f"#{th}")
        tags.append("#คอนโดให้เช่า")
        tags.append("#PantipProperty")
    return " ".join(t for t in tags if t)


def _contact_footer(lang: str) -> list[str]:
    if lang == "en":
        return [
            f"📲 LINE : {LINE_ID}  →  {LINE_URL}",
            f"📞 {PHONE_NUT_EN[0]} : {PHONE_NUT_EN[1]}",
            f"📞 {PHONE_PLENG_EN[0]} : {PHONE_PLENG_EN[1]}",
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
    rent = data.get("rent_price") or ""
    sale = data.get("sale_price") or ""
    if lang == "en":
        if _has_price(rent) and not _has_price(sale):
            return "🌟 Ready to move in · For Rent"
        if _has_price(sale) and not _has_price(rent):
            return "🌟 For Sale"
        return "🌟 For Rent / Sale"
    if _has_price(rent) and not _has_price(sale):
        return "🌟 พร้อมอยู่ · ให้เช่า"
    if _has_price(sale) and not _has_price(rent):
        return "🌟 ขาย"
    return "🌟 ให้เช่า / ขาย"


def _project_display(name: str, lang: str) -> str:
    project = (name or "").strip() or "Condo"
    if lang != "en":
        return project
    # Prefer Latin name before Thai parentheses: "NOBLE STATE 39 (โนเบิล…)" → EN name
    m = re.match(r"^([A-Za-z0-9][^(\n]*?)\s*\([\u0E00-\u0E7F].*\)$", project)
    if m:
        return m.group(1).strip()
    if _contains_thai(project) and not re.search(r"[A-Za-z]", project):
        return _romanize_places(project)
    return project


def generate_text(data: dict, lang: str = "th") -> str:
    project = _project_display(data.get("project_name") or "", lang)
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
    lines.append(
        "🛋 Fully Furnished พร้อมเข้าอยู่"
        if lang != "en"
        else "🛋 Fully Furnished — ready to move in"
    )

    if highlights:
        lines.append("")
        lines.append("✨ Highlights")
        for h in highlights:
            if lang == "en" and _thai_ratio(h) >= 0.2:
                continue  # hard safety net
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
    lines.append(_hashtags(data.get("project_name") or project, lang))

    # safety: never leak owner-post wording
    text = "\n".join(ln for ln in lines if ln is not None)
    text = re.sub(r"(?i)owner\s*post", "", text)
    text = re.sub(r"เจ้าของปล่อย", "", text)
    if lang == "en":
        # Final guard: strip accidental Thai from EN body (keep rare station leftovers minimal)
        # Don't strip project/station lines that we intentionally romanized above.
        pass
    return text.strip() + "\n"
