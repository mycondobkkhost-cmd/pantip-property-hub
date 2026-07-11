"""Extract property fields from Thai/English listing text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


CO_AGENT_PATTERNS = [
    r"co[\s-]?agent",
    r"โค[\s-]?เอ[\s-]?เจ",
    r"รับฝาก",
    r"หาเช่าให้",
    r"commission\s*share",
    r"ฝากขาย",
    r"ฝากเช่า",
]

CONTACT_PATTERNS = [
    r"(?:line|ไลน์)\s*[:\-]?\s*@?\s*[a-z0-9._-]{4,}",
    r"(?:tel|โทร|ติดต่อ)\s*[:\-]?\s*0\d[\d\s-]{7,}",
    r"\b0\d[\d\s-]{8,}\b",
    r"https?://(?:www\.)?(?:facebook|fb)\.com/[^\s]+",
    r"https?://(?:line\.me|lin\.ee)/[^\s]+",
    r"@[a-z0-9._]{4,}",
]


@dataclass
class OwnerContact:
    phones: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    facebook_urls: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)


@dataclass
class ParsedListing:
    project_name: str = ""
    property_type: str = ""
    bedrooms: str = ""
    size_sqm: str = ""
    floor: str = ""
    rent_price: str = ""
    sale_price: str = ""
    transit_tags: list[str] = field(default_factory=list)
    notes: str = ""
    raw_text: str = ""
    owner_phones: list[str] = field(default_factory=list)
    owner_lines: list[str] = field(default_factory=list)
    owner_facebook: list[str] = field(default_factory=list)
    owner_contact_other: list[str] = field(default_factory=list)
    is_co_agent: bool = False
    warnings: list[str] = field(default_factory=list)


def _digits(s: str) -> str:
    thai = "๐๑๒๓๔๕๖๗๘๙"
    out = []
    for ch in s or "":
        if ch in thai:
            out.append(str(thai.index(ch)))
        elif ch.isdigit():
            out.append(ch)
    return "".join(out)


def _fmt_price(num: str) -> str:
    d = _digits(num)
    if not d:
        return ""
    return f"{int(d):,}"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


def detect_co_agent(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low, re.I) for p in CO_AGENT_PATTERNS)


def _normalize_contact_text(text: str) -> str:
    """Normalize FB quirks so phone/Line regex can match."""
    # unicode dashes / minus → ASCII hyphen
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212", "\ufe58", "\ufe63", "\uff0d"):
        text = text.replace(ch, "-")
    # Thai digits → Arabic
    thai = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
    text = text.translate(thai)
    # space before emoji stuck to phone: 095-4966362📌
    text = re.sub(r"(\d)([^\d\s,./|+\-])", r"\1 \2", text)
    return text


def extract_contact(text: str) -> OwnerContact:
    """Pull owner contact from text — kept in storage, not deleted from raw."""
    contact = OwnerContact()
    if not text:
        return contact

    text = _normalize_contact_text(text)

    for m in re.finditer(
        r"(?:line|ไลน์|add\s*line)\s*[:\-]?\s*@?([a-z0-9._-]{4,})",
        text,
        re.I,
    ):
        contact.lines.append(m.group(1).lstrip("@"))

    for m in re.finditer(r"(?:^|\n)\s*@([a-z0-9._-]{4,})\s*(?:\n|$)", text, re.I | re.M):
        contact.lines.append(m.group(1))

    # ติดต่อ : ชื่อ 095-...  (allow name between label and number)
    for m in re.finditer(
        r"(?:tel|โทร|ติดต่อ|call|เบอร์)\s*[:\-]?\s*[^\d\n]{0,40}?(0\d[\d\s\-]{7,14}\d)",
        text,
        re.I,
    ):
        phone = re.sub(r"[\s\-]+", "-", m.group(1)).strip("-")
        phone = re.sub(r"(?<=\d)-(?=\d)", "-", phone)
        if len(_digits(phone)) >= 9:
            contact.phones.append(re.sub(r"\s+", "", m.group(1)))

    # General Thai mobile / landline — allow emoji/punct after number
    # covers 095-4966362, 095-496-6362, 0954966362
    for m in re.finditer(
        r"(?<!\d)(0\d{1,2}(?:[-\s]?\d{3,4}){2})(?!\d)",
        text,
    ):
        phone = re.sub(r"\s+", "", m.group(1))
        if len(_digits(phone)) >= 9:
            contact.phones.append(phone)

    for m in re.finditer(
        r"https?://(?:www\.)?(?:facebook|fb)\.com/[^\s]+",
        text,
        re.I,
    ):
        contact.facebook_urls.append(m.group(0))

    for m in re.finditer(r"https?://(?:line\.me|lin\.ee)/[^\s]+", text, re.I):
        contact.other.append(m.group(0))

    contact.phones = _unique(contact.phones)
    contact.lines = _unique(contact.lines)
    contact.facebook_urls = _unique(contact.facebook_urls)
    contact.other = _unique(contact.other)
    return contact


def strip_contact(text: str) -> str:
    """Remove contact info — use ONLY when generating customer-facing text."""
    out = text
    for pat in CONTACT_PATTERNS:
        out = re.sub(pat, "", out, flags=re.I)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def parse_listing_text(text: str) -> ParsedListing:
    raw = (text or "").strip()
    result = ParsedListing(raw_text=raw)
    if not raw:
        result.warnings.append("ไม่มีข้อความให้วิเคราะห์")
        return result

    result.is_co_agent = detect_co_agent(raw)
    low = raw.lower()

    contact = extract_contact(raw)
    result.owner_phones = contact.phones
    result.owner_lines = contact.lines
    result.owner_facebook = contact.facebook_urls
    result.owner_contact_other = contact.other

    # Property type
    if re.search(r"\bcondo\b|คอนโด", low):
        result.property_type = "Condo"
    elif re.search(r"\bhouse\b|บ้าน|ทาวน์", low):
        result.property_type = "House"
    elif re.search(r"ออฟฟิศ|office", low):
        result.property_type = "Office"

    # Bedrooms
    bed_bath = re.search(
        r"(\d+)\s*(?:bed|br)\s*(\d+)\s*(?:bath|ห้องน้ำ)|"
        r"(\d+)\s*ห้องนอน\s*(\d+)\s*ห้องน้ำ",
        raw,
        re.I,
    )
    if re.search(r"\bstudio\b", low):
        result.bedrooms = "Studio"
    elif bed_bath:
        b1, b2, b3, b4 = bed_bath.groups()
        beds = b1 or b3
        baths = b2 or b4
        result.bedrooms = f"{beds} Bed {baths} Bath"
    else:
        m = re.search(
            r"(\d+)\s*(?:bed|br|ห้องนอน)|(?:ห้องนอน)\s*(\d+)",
            raw,
            re.I,
        )
        if m:
            n = m.group(1) or m.group(2)
            baths = re.search(r"(\d+)\s*(?:bath|ห้องน้ำ)", raw, re.I)
            result.bedrooms = f"{n} Bed" + (f" {baths.group(1)} Bath" if baths else "")

    # Size — 33.5 ตร.ม. or 33.5 sqm, also after pipe
    m = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:ตร\.?\s*ม\.?|sq\.?\s*m\.?|sqm)\b",
        raw,
        re.I,
    )
    if m:
        result.size_sqm = m.group(1)

    # Floor — ชั้น 17 or | ชั้น 17
    m = re.search(r"(?:ชั้น|floor|fl\.?)\s*(\d+)", raw, re.I)
    if m:
        result.floor = m.group(1)

    # Rent
    for pat in [
        r"🔥\s*ราคา\s*([\d,]+)",
        r"(?:ร(?:า)?(?:ค)?(?:า)?เช่า|ค่าเช่า|เช่า|rent)\s*[:\s]*([\d,]+)",
        r"([\d,]+)\s*(?:บาท|baht)?\s*/\s*(?:เดือน|month)",
    ]:
        m = re.search(pat, raw, re.I)
        if m:
            result.rent_price = _fmt_price(m.group(1))
            break

    # Sale
    for pat in [
        r"(?:ร(?:า)?(?:ค)?(?:า)?ขาย|ขาย|sale)\s*[:\s]*([\d,]+(?:\.\d+)?)\s*(?:ล้าน|m)?",
        r"([\d,]+)\s*(?:ล้าน|million)",
    ]:
        m = re.search(pat, raw, re.I)
        if m:
            val = m.group(1)
            if "ล้าน" in m.group(0).lower() or "million" in m.group(0).lower():
                try:
                    result.sale_price = _fmt_price(
                        str(int(float(val.replace(",", "")) * 1_000_000))
                    )
                except ValueError:
                    result.sale_price = _fmt_price(val)
            else:
                result.sale_price = _fmt_price(val)
            break

    # Transit — 📍 lines + BTS/MRT tags
    for m in re.finditer(r"📍\s*([^\n]+)", raw):
        line = m.group(1).strip()
        for tm in re.finditer(r"(?:BTS|MRT|ARL|Airport\s*Link|SRT)\s+[^\n,;|🚇]{2,40}", line, re.I):
            tag = tm.group(0).strip().rstrip(".")
            tag = re.sub(r"\s*🚇.*$", "", tag).strip()
            if tag not in result.transit_tags:
                result.transit_tags.append(tag)
    for m in re.finditer(
        r"(?:BTS|MRT|ARL|Airport\s*Link|SRT)\s+[^\n,;|]{2,40}",
        raw,
        re.I,
    ):
        tag = m.group(0).strip().rstrip(".")
        if tag not in result.transit_tags:
            result.transit_tags.append(tag)
    result.transit_tags = result.transit_tags[:8]

    # Project name — prefer condo/project patterns, reject FB page titles
    reject_project = re.compile(
        r"owner\s*post|thru\s*thonglor|ประกาศ|รับ\s*agent|ติดต่อ|บาท|เดือน|"
        r"for\s*rent|for\s*sale|ให้เช่า|ขาย\s*คอนโด|业主|ปล่อยเช่าคอนโด",
        re.I,
    )

    def _clean_project_candidate(name: str) -> str:
        name = re.sub(r"[🔥📌📍✅🎉😍❤️]+", " ", name)
        name = re.sub(r"\s+", " ", name).strip(" -\t|")
        # "คอนโด Life @ ลาดพร้าว 18 ชั้น 8" → cut at ชั้น/ขนาด
        name = re.split(r"\s*(?:ชั้น|floor|ขนาด|ตร\.?\s*ม|ห้องนอน|bed)", name, flags=re.I)[0].strip()
        name = re.sub(r"^(?:คอนโด|condo)\s+", "", name, flags=re.I).strip()
        return name[:120]

    def _ok_project(name: str) -> bool:
        if not name or len(name) < 4:
            return False
        if reject_project.search(name):
            return False
        if re.fullmatch(r"[\d,.\s]+", name):
            return False
        if name.count("http"):
            return False
        return bool(re.search(r"[A-Za-zก-๙]{3,}", name))

    project_patterns = [
        # 📌 Life @ลาดพร้าว 18🎉 / คอนโด Life @ ลาดพร้าว 18 ชั้น 8
        r"(?:📌\s*)?(?:คอนโด\s+)?(Life\s*@?\s*ลาดพร้าว\s*\d+)",
        r"(?:📌\s*)?(?:คอนโด\s+)?(Life\s*@?\s*Ladprao\s*\d+)",
        r"(?:📌\s*)?(?:คอนโด\s+)?(Life\s*@?\s*[A-Za-zก-๙][A-Za-zก-๙\s\-]{1,30}?\d{1,3})",
        r"(?:For\s+Rent|For\s+Sale|ให้เช่า|ขาย)\s*:\s*([^\n|🔥📌📍✅🎉]{6,80})",
        r"✅\s*(?:For\s+Rent|For\s+Sale|ให้เช่า|ขาย)\s*:\s*([^\n|🔥📌📍]{6,80})",
        r"คอนโด\s+([A-Za-zก-๙][A-Za-z0-9ก-๙@\s\-\.]{3,50}?)\s*(?=ชั้น|floor|ขนาด|ตร)",
        r"(?:โครงการ|Project)\s*[:：]?\s*([^\n]{4,80})",
    ]
    for pat in project_patterns:
        m = re.search(pat, raw, re.I)
        if not m:
            continue
        name = _clean_project_candidate(m.group(1))
        if _ok_project(name):
            result.project_name = name
            break

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not result.project_name:
        for ln in lines[:10]:
            if len(ln) < 6 or re.match(r"^(?:#|http)", ln):
                continue
            cand = _clean_project_candidate(ln)
            # skip price-only / contact lines
            if re.search(r"(?:เช่า|ขาย|rent|sale|line|โทร|ติดต่อ|ราคา|บาท)", cand, re.I):
                # still allow "Life ... ประกาศเช่า" style if Life/Ideo/etc present
                if not re.search(r"(?:Life|Ideo|Niche|Asoke|Rhythm|Chapter|Whizdom|Supalai|Noble)", cand, re.I):
                    continue
                cand = re.split(r"(?:ประกาศ|ให้เช่า|for\s*rent)", cand, flags=re.I)[0].strip()
            if _ok_project(cand):
                result.project_name = cand[:120]
                break

    # notes = ข้อความต้นฉบับทั้งหมด (เก็บครบ ไม่ตัด contact)
    result.notes = raw

    if not result.rent_price and not result.sale_price:
        result.warnings.append("ไม่พบราคาเช่า/ขาย — กรอกเอง")
    if not result.project_name:
        result.warnings.append("ไม่พบชื่อโครงการ — กรอกเอง")
    if not contact.phones and not contact.lines:
        result.warnings.append("ไม่พบเบอร์/Line เจ้าของ — กรอกเองถ้ามี")

    return result


def parsed_to_dict(p: ParsedListing) -> dict:
    return {
        "project_name": p.project_name,
        "property_type": p.property_type,
        "bedrooms": p.bedrooms,
        "size_sqm": p.size_sqm,
        "floor": p.floor,
        "rent_price": p.rent_price,
        "sale_price": p.sale_price,
        "transit_tags": p.transit_tags,
        "notes": p.notes,
        "raw_text": p.raw_text,
        "owner_phones": p.owner_phones,
        "owner_lines": p.owner_lines,
        "owner_facebook": p.owner_facebook,
        "owner_contact_other": p.owner_contact_other,
        "is_co_agent": p.is_co_agent,
        "code_prefix": "COA" if p.is_co_agent else "RXT",
        "warnings": p.warnings,
    }
