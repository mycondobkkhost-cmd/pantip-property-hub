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
    m = re.search(r"^\s*(\d+)\s*/\s*(\d+)\s*$", b)
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
    """Customer-facing CTA (may include lin.ee link)."""
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


def _contact_footer_no_links(lang: str) -> list[str]:
    """CTA without URLs — customers screenshot LINE ID and add manually."""
    if lang == "en":
        return [
            f"📲 LINE ID : {LINE_ID}",
            f"📞 {PHONE_NUT_EN[0]} : {PHONE_NUT_EN[1]}",
            f"📞 {PHONE_PLENG_EN[0]} : {PHONE_PLENG_EN[1]}",
            "",
            "Add LINE from the ID above for viewing / more info 🙏",
        ]
    return [
        f"📲 LINE ID : {LINE_ID}",
        f"📞 {PHONE_NUT[0]} : {PHONE_NUT[1]}",
        f"📞 {PHONE_PLENG[0]} : {PHONE_PLENG[1]}",
        "",
        "สนใจนัดชม / ขอรายละเอียด แคปหน้าจอแล้วแอดไลน์ตามไอดีด้านบนได้เลยครับ 🙏",
    ]


def sanitize_no_urls(text: str) -> str:
    out = re.sub(r"https?://\S+|www\.\S+", "", text or "", flags=re.I)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def generate_text_no_links(data: dict, lang: str = "th", *, variant: int = 0) -> str:
    """SEO-oriented caption for group posts: images + text, no URL attachments."""
    project = _project_display(data.get("project_name") or "", lang)
    code = (data.get("code") or "RXT????").strip()
    # Reuse sell-first body; variant nudges opening pool via fake code suffix
    data_v = dict(data)
    if variant:
        data_v["code"] = f"{code}-v{int(variant)}"
    body = _build_sell_body_en(data_v) if lang == "en" else _build_sell_body_th(data_v)

    lines: list[str] = [
        body,
        "",
        f"📌 รหัสทรัพย์ : #{code}" if lang != "en" else f"📌 Property Code : #{code}",
        "",
    ]
    lines.extend(_contact_footer_no_links(lang))
    lines.append("")
    lines.append(_hashtags(data.get("project_name") or project, lang))

    text = "\n".join(ln for ln in lines if ln is not None)
    text = re.sub(r"(?i)owner\s*post", "", text)
    text = re.sub(r"เจ้าของปล่อย", "", text)
    return sanitize_no_urls(text)


def generate_caption_variants_no_links(data: dict, lang: str = "th", *, n: int = 4) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for i in range(max(1, min(int(n or 4), 8))):
        cap = generate_text_no_links(data, lang, variant=i)
        if cap and cap not in seen:
            seen.add(cap)
            out.append(cap)
    return out


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


def _variant_seed(data: dict) -> int:
    code = str(data.get("code") or data.get("project_name") or "x")
    return sum(ord(c) for c in code) % 97


def _parse_size_num(raw) -> float:
    s = re.sub(r"[^\d.]", "", str(raw or ""))
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _is_pet_friendly(data: dict) -> bool:
    v = data.get("pet_friendly")
    if v in (True, 1, "1", "Yes", "yes", "true", "TRUE"):
        return True
    blob = " ".join(
        str(x or "")
        for x in (data.get("notes"), data.get("raw_text"), data.get("project_name"))
    ).lower()
    if "ห้ามสัตว์" in blob or "no pet" in blob:
        return False
    return "pet friendly" in blob or "เลี้ยงสัตว์ได้" in blob or "สัตว์เลี้ยงได้" in blob


def _primary_angle(data: dict) -> str:
    """Pick the strongest selling angle for this listing."""
    transit = data.get("transit_tags") or []
    ptype = str(data.get("property_type") or "").lower()
    project = str(data.get("project_name") or "").lower()
    blob = " ".join(
        str(x or "")
        for x in (data.get("notes"), data.get("raw_text"), data.get("project_name"))
    ).lower()
    size_n = _parse_size_num(data.get("size_sqm"))

    if _is_pet_friendly(data):
        return "pet"
    if "home office" in project or "home office" in blob or "working space" in blob:
        return "wfh"
    if any(k in blob for k in ("international school", "นานาชาติ")):
        return "expat"
    if any(k in ptype for k in ("house", "town", "home", "บ้าน", "ทาวน์")) or "townhouse" in blob:
        return "family"
    if size_n >= 80:
        return "space"
    if transit:
        return "transit"
    if any(k in blob for k in ("luxury", "ลักซ์", "หรู", "penthouse")):
        return "luxury"
    if _has_price(data.get("rent_price")) and not _has_price(data.get("sale_price")):
        return "rent_ready"
    return "lifestyle"


def _amenity_bits(data: dict) -> list[str]:
    raw = _sanitize_source(data.get("raw_text") or "")
    low = raw.lower()
    bits: list[str] = []
    if any(k in low for k in ("fully furnished", "เฟอร์นิเจอร์ครบ", "ตกแต่งครบ", "furnished", "เฟอร์ครบ")):
        bits.append("เฟอร์ครบ")
    if "แอร์" in raw or re.search(r"\bair\b", low):
        bits.append("มีแอร์")
    if any(k in low for k in ("ซักผ้า", "washing")):
        bits.append("มีเครื่องซักผ้า")
    if any(k in low for k in ("ที่จอด", "parking")):
        bits.append("มีที่จอดรถ")
    if any(k in low for k in ("น้ำอุ่น", "น้ำร้อน", "water heater")):
        bits.append("มีน้ำอุ่น")
    if _is_pet_friendly(data):
        bits.append("เลี้ยงสัตว์ได้")
    return bits[:4]


def _spec_bits_th(data: dict) -> list[str]:
    bits: list[str] = []
    beds, baths = _beds_baths(data.get("bedrooms") or "")
    size_n = _parse_size_num(data.get("size_sqm"))
    floor = str(data.get("floor") or "").strip()
    if beds:
        if beds.lower() == "studio":
            bits.append("Studio")
        else:
            bits.append(f"{beds} นอน")
    if baths:
        bits.append(f"{baths} น้ำ")
    if size_n > 0:
        bits.append(f"{int(size_n) if size_n == int(size_n) else size_n} ตร.ม.")
    if floor:
        bits.append(f"ชั้น {floor}")
    return bits


def _hook_th(data: dict, angle: str, seed: int) -> str:
    """One short line a person would actually type — no ad slogans."""
    transit = [str(t).strip() for t in (data.get("transit_tags") or []) if str(t).strip()]
    t0 = transit[0] if transit else ""
    if angle == "pet":
        opts = ["เลี้ยงสัตว์ได้ค่ะ", "Pet friendly นะ", "เลี้ยงสัตว์ได้นะคะ"]
    elif angle == "wfh":
        opts = ["มีมุมทำงานที่บ้านได้", "Home office ได้", "ทำงานที่บ้านได้สบาย"]
    elif angle == "family":
        opts = ["บ้านหลังนี้น่าอยู่", "พื้นที่แบบบ้านเลย", "อยู่ด้วยกันหลายคนได้"]
    elif angle == "space":
        opts = ["ห้องกว้างดี", "พื้นที่เยอะอยู่สบาย", "โล่งดี"]
    elif angle == "expat":
        opts = ["ใกล้โรงเรียนนานาชาติ", "ทำเลส่งลูกเรียนสะดวก"]
    elif angle == "transit" and t0:
        opts = [f"ใกล้ {t0}", f"เดินถึง {t0} ได้", f"อยู่ใกล้ {t0}"]
    elif angle == "rent_ready":
        opts = ["พร้อมเข้าอยู่เลย", "ย้ายเข้าได้เลย", "พร้อมอยู่"]
    else:
        opts = ["พร้อมอยู่", "ทำเลดี", "น่าสนใจ"]
    return opts[seed % len(opts)]


def _deal_line_th(data: dict) -> str:
    rent = data.get("rent_price") or ""
    sale = data.get("sale_price") or ""
    if _has_price(rent) and _has_price(sale):
        return f"เช่า {rent} / ขาย {sale}"
    if _has_price(rent):
        return f"เช่า {rent}/เดือน"
    if _has_price(sale):
        return f"ขาย {sale}"
    return ""


def _build_sell_body_th(data: dict) -> str:
    """Thai FB post like an agent typed it — plain, short, no AI template."""
    project = _project_display(data.get("project_name") or "", "th")
    angle = _primary_angle(data)
    seed = _variant_seed(data)
    hook = _hook_th(data, angle, seed)
    specs = _spec_bits_th(data)
    amenities = _amenity_bits(data)
    deal = _deal_line_th(data)
    transit = [str(t).strip() for t in (data.get("transit_tags") or []) if str(t).strip()]
    zones = data.get("zone_tags") or data.get("zones") or []
    if isinstance(zones, str):
        zones = [z.strip() for z in zones.split(",") if z.strip()]

    layout = seed % 4
    lines: list[str] = []

    if layout == 0:
        # project → hook → specs → deal
        lines.append(project)
        lines.append("")
        lines.append(hook)
        if specs:
            lines.append("")
            lines.append(" ".join(specs))
        extra = []
        if transit and angle != "transit":
            extra.append(f"ใกล้ {transit[0]}")
        if amenities:
            extra.append(" ".join(amenities))
        if extra:
            lines.append(" / ".join(extra) if len(extra) > 1 else extra[0])
        if deal:
            lines.extend(["", deal])

    elif layout == 1:
        # hook first, then project + facts as chat lines
        lines.append(hook)
        lines.append("")
        lines.append(project)
        for s in specs:
            lines.append(s)
        if amenities:
            lines.append(" ".join(amenities))
        elif not amenities:
            lines.append("พร้อมอยู่")
        if deal:
            lines.extend(["", deal])

    elif layout == 2:
        # one short block, almost no bullets
        bits = [project]
        if specs:
            bits.append(" ".join(specs))
        if transit:
            bits.append(f"ใกล้ {transit[0]}")
        elif zones:
            bits.append(str(zones[0]))
        if amenities:
            bits.append(" ".join(amenities))
        lines.append(hook)
        lines.append("")
        lines.append("\n".join(bits))
        if deal:
            lines.extend(["", deal])

    else:
        # rent/sale lead (common agent habit)
        if deal:
            lines.append(deal)
            lines.append("")
        lines.append(project)
        lines.append(hook)
        if specs:
            lines.append("")
            lines.append(" · ".join(specs))
        if amenities:
            lines.append(" · ".join(amenities))
        if transit and "ใกล้" not in hook:
            lines.append(f"ใกล้ {transit[0]}")

    # strip empties at ends, keep single blank gaps
    out: list[str] = []
    for ln in lines:
        if ln == "" and (not out or out[-1] == ""):
            continue
        out.append(ln)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _build_sell_body_en(data: dict) -> str:
    """Short English agent-style note."""
    project = _project_display(data.get("project_name") or "", "en")
    transit = data.get("transit_tags") or []
    t0 = _romanize_places(str(transit[0])) if transit else ""
    angle = _primary_angle(data)
    seed = _variant_seed(data)
    beds, baths = _beds_baths(data.get("bedrooms") or "")
    size_n = _parse_size_num(data.get("size_sqm"))
    floor = str(data.get("floor") or "").strip()

    hooks = {
        "transit": f"Near {t0}" if t0 else "Good location",
        "pet": "Pet friendly",
        "family": "Feels more like a house",
        "space": "Spacious",
        "wfh": "Works for home office",
        "rent_ready": "Ready to move in",
        "expat": "Handy for school runs",
        "luxury": "Nice to live in",
    }
    hook = hooks.get(angle) or "Ready to move in"
    specs: list[str] = []
    if beds:
        specs.append("Studio" if beds.lower() == "studio" else f"{beds} bed")
    if baths:
        specs.append(f"{baths} bath")
    if size_n:
        specs.append(f"{int(size_n)} sqm")
    if floor:
        specs.append(f"floor {floor}")

    rent = data.get("rent_price") or ""
    sale = data.get("sale_price") or ""
    deal = ""
    if _has_price(rent) and _has_price(sale):
        deal = f"Rent {rent} / Sale {sale}"
    elif _has_price(rent):
        deal = f"Rent {rent}/mo"
    elif _has_price(sale):
        deal = f"Sale {sale}"

    amen = _amenity_bits(data)
    lines = [project, "", hook]
    if specs:
        lines.append(" · ".join(specs))
    if amen:
        lines.append(" · ".join(amen[:3]))
    if deal:
        lines.extend(["", deal])
    if seed % 2 and t0 and angle != "transit":
        lines.insert(2, f"Near {t0}")
    return "\n".join(lines).strip()


def generate_text(data: dict, lang: str = "th") -> str:
    """Customer-facing listing post. Local sell-first copy only (no paid AI)."""
    project = _project_display(data.get("project_name") or "", lang)
    code = (data.get("code") or "RXT????").strip()
    prefix = (data.get("code_prefix") or "RXT").strip().upper()

    body = _build_sell_body_en(data) if lang == "en" else _build_sell_body_th(data)
    lines: list[str] = [body, ""]

    lines.append("🤝 Co-Agent Welcome")
    if lang == "en":
        lines.append(f"📌 Property Code : #{code}")
    else:
        lines.append(f"📌 รหัสทรัพย์ : #{code}")
    if prefix == "COA":
        lines.append("🏷 Co-agent listing" if lang == "en" else "🏷 รายการโคเอเจนต์")

    lines.append("")
    footer_block = ""
    try:
        from src.hub.post_footer_store import (
            format_footer_with_code,
            get_latest_snippet,
            mark_snippet_used,
        )

        snip = get_latest_snippet()
        if snip and (snip.get("text") or "").strip():
            use_snip = True
            if lang == "en":
                label_l = str(snip.get("label") or "").lower()
                sid = str(snip.get("id") or "").lower()
                if "en" not in label_l and "en" not in sid and _thai_ratio(str(snip.get("text") or "")) >= 0.15:
                    use_snip = False
            if use_snip:
                footer_block = format_footer_with_code(str(snip.get("text") or ""), code)
                try:
                    mark_snippet_used(str(snip.get("id") or ""))
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        footer_block = ""

    if footer_block:
        lines.append(footer_block)
    else:
        lines.extend(_contact_footer(lang))
    lines.append("")
    lines.append(_hashtags(data.get("project_name") or project, lang))

    text = "\n".join(ln for ln in lines if ln is not None)
    text = re.sub(r"(?i)owner\s*post", "", text)
    text = re.sub(r"เจ้าของปล่อย", "", text)
    return text.strip() + "\n"
