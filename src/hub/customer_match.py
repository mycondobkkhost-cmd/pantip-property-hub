"""Match Hub properties to a customer follow-up case brief."""

from __future__ import annotations

import re
from typing import Any

from src.hub.project_store import (
    load_projects,
    load_properties,
    project_transit_display,
    project_zone_display,
)

BED_ALIASES = {
    "studio": "studio",
    "สตูดิโอ": "studio",
    "0": "studio",
    "1": "1",
    "1bed": "1",
    "1br": "1",
    "2": "2",
    "2bed": "2",
    "2br": "2",
    "3": "3",
    "3bed": "3",
    "3br": "3",
    "4": "4+",
    "4+": "4+",
    "duplex": "duplex",
    "ดูเพล็กซ์": "duplex",
    "ดูเพลกซ์": "duplex",
    "penthouse": "penthouse",
    "เพนต์เฮาส์": "penthouse",
}


def _parse_price(s: Any) -> int:
    digits = re.sub(r"[^\d]", "", str(s or ""))
    return int(digits) if digits else 0


def _has_price(s: Any) -> bool:
    v = str(s or "").strip()
    return bool(v) and v not in {"-", "—", "0"}


def bed_category(beds: Any) -> str:
    b = str(beds or "").lower()
    if re.search(r"duplex|ดูเพล[็กซ์]?", b):
        return "duplex"
    if re.search(r"pent\s*house|penthouse|เพนต์\s*เฮาส์|เพนท์เฮาส์", b):
        return "penthouse"
    if re.search(r"studio|สตูดิโอ|สตู\b", b):
        return "studio"
    m = re.search(r"(\d+)\s*(?:bed|br|นอน|ห้องนอน)?", b)
    if m:
        n = int(m.group(1))
        if n >= 4:
            return "4+"
        if n >= 1:
            return str(n)
    return ""


def _norm_bed_want(raw: str) -> str:
    k = re.sub(r"[\s_\-]", "", str(raw or "").lower())
    return BED_ALIASES.get(k) or BED_ALIASES.get(raw.strip().lower()) or raw.strip().lower()


def _norm_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^\wก-๙]+", "", s, flags=re.UNICODE)
    return s


def _transit_blob(prop: dict, proj: dict) -> str:
    bits: list[str] = []
    bits.extend(project_transit_display(proj) or [])
    bits.extend(prop.get("transit_from_sheet") or [])
    return " ".join(str(x) for x in bits)


def _zone_blob(prop: dict, proj: dict) -> str:
    bits: list[str] = []
    bits.extend(project_zone_display(proj) or [])
    if prop.get("location_ref"):
        bits.append(str(prop["location_ref"]))
    if prop.get("project_name"):
        bits.append(str(prop["project_name"]))
    if proj.get("canonical_name"):
        bits.append(str(proj["canonical_name"]))
    return " ".join(bits)


def _match_transit(want: str, blob: str) -> bool:
    w = _norm_text(want)
    b = _norm_text(blob)
    if not w or not b:
        return False
    # strip line prefixes for fuzzy
    w2 = re.sub(r"^(bts|mrt|arl|srt)", "", w)
    if w in b or (w2 and w2 in b):
        return True
    # token overlap on Thai station names
    return len(w2) >= 4 and w2 in b


def _match_location(want: str, blob: str) -> bool:
    w = _norm_text(want)
    b = _norm_text(blob)
    if not w or not b:
        return False
    if w in b or b in w:
        return True
    # partial: any chunk >= 3 chars
    for i in range(0, max(0, len(w) - 2)):
        chunk = w[i : i + 3]
        if chunk in b:
            return True
    return False


def score_property_for_case(
    prop: dict,
    case: dict,
    proj: dict,
    *,
    exclude_codes: set[str] | None = None,
) -> tuple[int, list[str]] | None:
    """Return (score, reasons) or None if hard-filtered out."""
    code = str(prop.get("code") or "").upper()
    if exclude_codes and code in exclude_codes:
        return None

    status = (prop.get("import_status") or "").strip()
    if status and status not in {"active", "needs_review", ""}:
        # skip archived / removed by default
        if status == "archived":
            return None

    deal = (case.get("deal_type") or "rent").lower()
    rent = _parse_price(prop.get("rent_price")) if _has_price(prop.get("rent_price")) else 0
    sale = _parse_price(prop.get("sale_price")) if _has_price(prop.get("sale_price")) else 0

    if deal == "rent" and not rent:
        return None
    if deal == "sale" and not sale:
        return None
    if deal == "both" and not rent and not sale:
        return None

    bmin = int(case.get("budget_min") or 0)
    bmax = int(case.get("budget_max") or 0)
    price = rent if deal != "sale" else sale
    if deal == "both":
        # prefer the side that has a budget band; default rent if both
        price = rent or sale
    if bmin and price and price < bmin:
        return None
    if bmax and price and price > bmax:
        return None

    types = [str(t).strip() for t in (case.get("property_types") or []) if str(t).strip()]
    if types:
        pt = str(prop.get("property_type") or "").strip()
        # Condo / คอนโด soft match
        ok = False
        for t in types:
            if t.lower() == pt.lower():
                ok = True
                break
            if "condo" in t.lower() and "condo" in pt.lower():
                ok = True
                break
            if "บ้าน" in t or "house" in t.lower():
                if "house" in pt.lower() or "บ้าน" in pt:
                    ok = True
                    break
        if not ok:
            return None

    want_beds = [_norm_bed_want(x) for x in (case.get("bedrooms") or []) if str(x).strip()]
    want_beds = [x for x in want_beds if x]
    cat = bed_category(prop.get("bedrooms"))
    if want_beds and cat and cat not in want_beds:
        return None

    transit_blob = _transit_blob(prop, proj)
    zone_blob = _zone_blob(prop, proj)
    want_transits = [str(t).strip() for t in (case.get("transits") or []) if str(t).strip()]
    loc_raw = str(case.get("locations") or "").strip()
    loc_parts = [x.strip() for x in re.split(r"[,，|/]+", loc_raw) if x.strip()]
    brief = str(case.get("brief") or "").strip()

    score = 10
    reasons: list[str] = []

    if want_transits:
        hits = [t for t in want_transits if _match_transit(t, transit_blob + " " + zone_blob)]
        if not hits and not loc_parts:
            return None
        if hits:
            score += 40 + 5 * len(hits)
            reasons.append("สถานี: " + ", ".join(hits[:3]))
        elif loc_parts:
            # transit miss but may still match location below
            score -= 5

    if loc_parts:
        loc_hits = [x for x in loc_parts if _match_location(x, zone_blob + " " + transit_blob)]
        if not loc_hits and not want_transits:
            return None
        if not loc_hits and want_transits and not any(
            _match_transit(t, transit_blob + " " + zone_blob) for t in want_transits
        ):
            return None
        if loc_hits:
            score += 25 + 3 * len(loc_hits)
            reasons.append("ทำเล: " + ", ".join(loc_hits[:3]))

    # Free-text brief soft boost (ไม่ hard-filter)
    if brief:
        blob = _norm_text(zone_blob + " " + transit_blob + " " + str(prop.get("project_name") or ""))
        for token in re.findall(r"[A-Za-zก-๙]{3,}", brief):
            if _norm_text(token) in blob:
                score += 4
                reasons.append(f"โจทย์มี «{token}»")
                break

    if cat and want_beds:
        score += 15
        reasons.append(f"ห้อง {cat}")
    if types:
        score += 8
        reasons.append(prop.get("property_type") or "ประเภทตรง")

    if bmin or bmax:
        score += 12
        if deal == "sale":
            reasons.append(f"ขาย {sale:,}")
        else:
            reasons.append(f"เช่า {rent:,}")

    # Prefer fresher listings lightly
    listed = str(prop.get("last_listed_at") or "")
    if listed:
        score += 2

    if not reasons:
        reasons.append("ตรงเงื่อนไขพื้นฐาน")

    return score, reasons


def recommend_for_case(
    case: dict,
    *,
    limit: int = 20,
    exclude_offered: bool = True,
    exclude_viewing: bool = False,
) -> dict:
    projects = {p.get("id"): p for p in load_projects()}
    props = load_properties()

    exclude: set[str] = set()
    if exclude_offered:
        exclude.update(str(c).upper() for c in (case.get("offered_codes") or []))
    if exclude_viewing:
        exclude.update(str(c).upper() for c in (case.get("viewing_codes") or []))

    scored: list[dict] = []
    for prop in props:
        proj = projects.get(prop.get("project_id")) or {}
        result = score_property_for_case(prop, case, proj, exclude_codes=exclude)
        if not result:
            continue
        score, reasons = result
        scored.append(
            {
                "code": prop.get("code") or "",
                "id": prop.get("id") or "",
                "project_id": prop.get("project_id") or "",
                "project_name": prop.get("project_name")
                or proj.get("canonical_name")
                or "",
                "property_type": prop.get("property_type") or "",
                "bedrooms": prop.get("bedrooms") or "",
                "size_sqm": prop.get("size_sqm") or "",
                "floor": prop.get("floor") or "",
                "rent_price": prop.get("rent_price") or "",
                "sale_price": prop.get("sale_price") or "",
                "location_ref": prop.get("location_ref") or "",
                "transit": project_transit_display(proj)[:4],
                "import_status": prop.get("import_status") or "",
                "last_listed_at": prop.get("last_listed_at") or "",
                "source_url": prop.get("source_url") or prop.get("post_url") or "",
                "score": score,
                "reasons": reasons,
            }
        )

    scored.sort(key=lambda x: (-x["score"], x.get("code") or ""))
    top = scored[: max(1, int(limit or 20))]

    # ดันรหัสที่ลูกค้าทักมาไว้บนสุด (ถ้ายังอยู่ในผล / หรือดึงแยก)
    inquiry = {str(c).upper() for c in (case.get("inquiry_codes") or []) if c}
    if inquiry:
        by_code = {str(x.get("code") or "").upper(): x for x in scored}
        pinned = []
        for code in (case.get("inquiry_codes") or []):
            c = str(code).upper()
            if c in by_code:
                item = dict(by_code[c])
                item["reasons"] = ["ห้องที่ลูกค้าทักมา"] + list(item.get("reasons") or [])
                item["score"] = max(int(item.get("score") or 0), 999)
                pinned.append(item)
        rest = [x for x in top if str(x.get("code") or "").upper() not in inquiry]
        top = (pinned + rest)[: max(1, int(limit or 20))]

    return {
        "ok": True,
        "count": len(top),
        "scanned": len(props),
        "matched": len(scored),
        "items": top,
        "case_id": case.get("id") or "",
        "case_code": case.get("case_code") or "",
    }
