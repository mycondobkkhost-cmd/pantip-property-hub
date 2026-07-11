"""Facebook group book — auto-tag + recommend groups for a listing."""

from __future__ import annotations

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
GROUPS_JSON = BASE_DIR / "data" / "facebook_groups.json"

# (zone_id, patterns matched against name+url blob)
ZONE_PATTERNS: list[tuple[str, list[str]]] = [
    ("ladprao", [r"ladprao", r"ladphra", r"lardprao", r"ลาดพร้าว"]),
    ("rama9", [r"rama\s*9", r"rama9", r"พระราม\s*9", r"พระราม9"]),
    ("asoke", [r"asoke", r"asok", r"อโศก"]),
    ("thonglor", [r"thonglor", r"thong\s*lo", r"ทองหล่อ"]),
    ("ekamai", [r"ekamai", r"ekkamai", r"เอกมัย"]),
    ("onnut", [r"onnut", r"on\s*nut", r"อ่อนนุช"]),
    ("huaikhwang", [r"huaikhwang", r"huai\s*khwang", r"ห้วยขวาง", r"sutthisan", r"สุทธิสาร"]),
    ("ratchada", [r"ratchada", r"รัชดา"]),
    ("sukhumvit", [r"sukhumvit", r"สุขุมวิท"]),
    ("ramkhamhaeng", [r"ramkhamhaeng", r"รามคำแหง"]),
    ("silom", [r"silom", r"สีลม", r"sathorn", r"สาทร", r"chidlom", r"ชิดลม"]),
    ("bangna", [r"bangna", r"บางนา", r"bearing", r"แบริ่ง", r"lasalle", r"ลาซาล", r"udomsuk", r"อุดมสุข"]),
    ("thonburi", [r"thonburi", r"ธนบุรี", r"charoennakhon", r"เจริญนคร"]),
    ("phayathai", [r"phayathai", r"พญาไท", r"ari\b", r"อารีย์"]),
    ("ngamwongwan", [r"ngamwongwan", r"งามวงศ์"]),
]

OFFER_PATTERNS: list[tuple[str, list[str]]] = [
    ("rent", [r"rent", r"เช่า", r"for\s*rent", r"ให้เช่า", r"出租"]),
    ("sale", [r"sale", r"ขาย", r"for\s*sale", r"出售", r"ซื้อขาย"]),
    ("condo", [r"condo", r"คอนโด", r"apartment"]),
    ("house", [r"house", r"บ้าน", r"townhome", r"ทาวน์"]),
    ("office", [r"office", r"ออฟฟิศ"]),
    ("expat", [r"expat", r"foreigner", r"外国人"]),
    ("owner_only", [r"owner\s*post", r"condo\s*owner", r"เจ้าของห้อง", r"ห้ามเอเจนท์", r"ห้ามเอเจนต์", r"业主"]),
    ("agent_ok", [r"owneragent", r"agent\s*post", r"เอเจนท์", r"นายหน้า"]),
]


def _blob(group: dict) -> str:
    return f"{group.get('name') or ''} {group.get('url') or ''}".lower()


# Strong signals — enough alone
REAL_ESTATE_STRONG = [
    r"condo",
    r"คอนโด",
    r"apartment",
    r"อพาร์ท",
    r"property",
    r"อสังหา",
    r"real\s*estate",
    r"baanchao",
    r"owner\s*post",
    r"ปล่อยเช่า",
    r"นายหน้า",
    r"เอเจนท์?\s*อสังหา",
    r"bts\s*condo",
    r"ห้องชุด",
    r"แมนชั่น",
    r"mansion",
    r"ทาวน์โฮม",
    r"townhome",
    r"townhouse",
    r"ที่ดิน",
    r"หอพัก",
    r"office\s*for\s*rent",
    r"ออฟฟิศ.*เช่า",
    r"เช่า.*ออฟฟิศ",
]

# Need strong OR (weak + zone/property context)
REAL_ESTATE_WEAK = [
    r"บ้าน",
    r"\bhouse\b",
    r"เช่า",
    r"\brent\b",
    r"ขาย",
    r"\bsale\b",
    r"for\s*rent",
    r"for\s*sale",
    r"เจ้าของ",
    r"agent",
    r"เอเจน",
]

REAL_ESTATE_ZONEISH = [
    r"ลาดพร้าว",
    r"ladprao",
    r"sukhumvit",
    r"สุขุมวิท",
    r"ทองหล่อ",
    r"thonglor",
    r"พระราม",
    r"rama\s*\d",
    r"รัชดา",
    r"ratchada",
    r"อ่อนนุช",
    r"onnut",
    r"เอกมัย",
    r"ekamai",
    r"bangna",
    r"บางนา",
    r"สีลม",
    r"silom",
    r"สาทร",
    r"sathorn",
    r"ห้วยขวาง",
    r"กรุงเทพ",
    r"bangkok",
    r"\bbts\b",
    r"\bmrt\b",
]

REAL_ESTATE_NEGATIVE = [
    r"เกม",
    r"\bgame\b",
    r"ฟุตบอล",
    r"football",
    r"คริปโต",
    r"crypto",
    r"bitcoin",
    r"หุ้น",
    r"forex",
    r"แต่งงาน",
    r"wedding",
    r"แม่และเด็ก",
    r"อาหาร",
    r"\bfood\b",
    r"ท่องเที่ยว",
    r"travel",
    r"รถมือสอง",
    r"car\s*sale",
    r"มอไซค์",
    r"job\s*vacancy",
    r"หางาน",
    r"รับสมัครงาน",
    r"มือสองทั่วไป",
    r"ของมือสอง",
]


def is_real_estate_group(group: dict) -> bool:
    """True if group name/url looks like property / condo / rent-sale related."""
    blob = _blob(group)
    if not blob.strip():
        return False

    strong = any(re.search(p, blob, re.I) for p in REAL_ESTATE_STRONG)
    if any(re.search(p, blob, re.I) for p in REAL_ESTATE_NEGATIVE) and not strong:
        return False
    if strong:
        return True

    weak = any(re.search(p, blob, re.I) for p in REAL_ESTATE_WEAK)
    zone = any(re.search(p, blob, re.I) for p in REAL_ESTATE_ZONEISH)
    if weak and zone:
        return True
    # บ้าน + เช่า/ขาย
    if re.search(r"บ้าน", blob) and re.search(r"เช่า|ขาย|rent|sale", blob, re.I):
        return True

    offers = group.get("offer_tags") or []
    if any(o in offers for o in ("rent", "sale", "condo", "house", "office")):
        return True
    return False


def filter_real_estate_groups(groups: list[dict]) -> tuple[list[dict], list[dict]]:
    kept, dropped = [], []
    for g in groups:
        (kept if is_real_estate_group(g) else dropped).append(g)
    return kept, dropped


def infer_role_tags(blob: str, zones: list[str]) -> list[str]:
    """Classify group posting role: zone / citywide / luxury / expat / mass."""
    roles: list[str] = []
    if re.search(
        r"luxury|พรีเมียม|premium|double\s*volume|big\s*size|high[\s-]*end|"
        r"หรู|ลักซ์|penthouse|super\s*luxury",
        blob,
        re.I,
    ):
        roles.append("luxury")
    if re.search(r"expat|foreigner|外国人|english\s*speaking", blob, re.I):
        roles.append("expat")
    if re.search(
        r"กรุงเทพ|bangkok|ปริมณฑล|ทั่วกรุงเทพ|ทั่วประเทศ|thailand|"
        r"baanchao(?!.*(lad|onnut|huai))|"
        r"condo\s*(market|hub|exchange)|condomarket|btscondo|"
        r"ซื้อ\s*ขาย\s*เช่า\s*คอนโด(?!.*bts|.*mrt|.*สุขุม|.*อโศก)",
        blob,
        re.I,
    ):
        roles.append("citywide")
    # specific zone in name → zone role
    if zones and any(z != "bangkok" for z in zones):
        roles.append("zone")
    elif re.search(
        r"อโศก|asoke|ทองหล่อ|thonglor|เอกมัย|ekamai|ลาดพร้าว|ladprao|"
        r"พระราม\s*9|rama\s*9|รัชดา|ratchada|อ่อนนุช|onnut|สุขุมวิท|sukhumvit|"
        r"สีลม|silom|สาทร|sathorn|ห้วยขวาง|บางนา|bangna",
        blob,
        re.I,
    ):
        roles.append("zone")
    # broad condo marketplace without tight zone
    if not roles or (roles == ["citywide"]):
        if re.search(r"condo|คอนโด|property|อสังหา|เช่า|ขาย|rent|sale", blob, re.I):
            if "citywide" not in roles and "zone" not in roles:
                roles.append("mass")
            elif "citywide" in roles and "mass" not in roles:
                roles.append("mass")
    if not roles:
        roles.append("mass")
    # dedupe preserve order
    out: list[str] = []
    for r in roles:
        if r not in out:
            out.append(r)
    return out


def infer_tags_from_blob(blob: str) -> tuple[list[str], list[str]]:
    zones: list[str] = []
    for zid, pats in ZONE_PATTERNS:
        if any(re.search(p, blob, re.I) for p in pats):
            zones.append(zid)
    offers: list[str] = []
    for oid, pats in OFFER_PATTERNS:
        if any(re.search(p, blob, re.I) for p in pats):
            offers.append(oid)
    # default condo/rent-sale book if name is generic bangkok condo
    if not offers and re.search(r"condo|คอนโด|baanchao|property|อสังหา", blob, re.I):
        offers.extend(["condo", "rent", "sale"])
    if "owner_only" in offers and "agent_ok" not in offers:
        # keep owner_only; agent should skip unless forced
        pass
    return zones, offers


def auto_tag_group(group: dict, *, force: bool = False) -> dict:
    """Fill zone_tags / offer_tags / role_tags from name+url when empty (or force)."""
    g = dict(group)
    blob = _blob(g)
    zones, offers = infer_tags_from_blob(blob)
    if force or not g.get("zone_tags"):
        g["zone_tags"] = zones
    if force or not g.get("offer_tags"):
        g["offer_tags"] = offers
    # general bangkok catch-all
    if not g["zone_tags"] and re.search(
        r"bangkok|กรุงเทพ|baanchao|btscondo|condomarket|condoth|ปริมณฑล", blob, re.I
    ):
        if "bangkok" not in g["zone_tags"]:
            g["zone_tags"] = list(g["zone_tags"]) + ["bangkok"]
    roles = infer_role_tags(blob, g.get("zone_tags") or [])
    if force or not g.get("role_tags"):
        g["role_tags"] = roles
    g.setdefault("price_band", g.get("price_band") or "")
    g.setdefault("notes", g.get("notes") or "")
    g.setdefault("member_band", g.get("member_band") or "")  # S/M/L/XL — manual later
    g.setdefault("core_reach", bool(g.get("core_reach")))
    return g


def load_groups(*, retag: bool = False) -> list[dict]:
    if not GROUPS_JSON.exists():
        return []
    raw = json.loads(GROUPS_JSON.read_text(encoding="utf-8"))
    groups = raw.get("groups") if isinstance(raw, dict) else raw
    out = [auto_tag_group(g, force=retag) for g in (groups or [])]
    return out


def save_groups(groups: list[dict]) -> None:
    GROUPS_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "count": len(groups),
        "source": "facebook_groups_joins",
        "groups": groups,
    }
    GROUPS_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def retag_all() -> dict:
    groups = load_groups(retag=True)
    save_groups(groups)
    tagged = sum(1 for g in groups if g.get("zone_tags") or g.get("offer_tags") or g.get("role_tags"))
    return {"total": len(groups), "tagged": tagged}


def infer_property_zones(prop: dict) -> list[str]:
    parts = [
        prop.get("project_name") or "",
        prop.get("location_ref") or "",
        " ".join(prop.get("transit_tags") or []),
        prop.get("notes") or "",
        prop.get("raw_text") or "",
    ]
    blob = " ".join(parts).lower()
    zones, _ = infer_tags_from_blob(blob)
    extras = []
    if re.search(r"ladprao|ลาดพร้าว", blob):
        extras.append("ladprao")
    if re.search(r"rama\s*9|พระราม\s*9", blob):
        extras.append("rama9")
    for z in extras:
        if z not in zones:
            zones.append(z)
    # โซนย่อย → โซนแม่ (ช่วยแมตช์กลุ่มที่แท็กกว้างกว่า)
    related = {
        "ekamai": ["sukhumvit"],
        "thonglor": ["sukhumvit"],
        "asoke": ["sukhumvit"],
        "onnut": ["sukhumvit"],
        "huaikhwang": ["ratchada"],
        "phayathai": ["rama9"],
    }
    for z in list(zones):
        for parent in related.get(z, []):
            if parent not in zones:
                zones.append(parent)
    if not zones:
        zones = ["bangkok"]
    return zones


def infer_property_offers(prop: dict) -> list[str]:
    offers = ["condo"] if (prop.get("property_type") or "Condo").lower().startswith("condo") else []
    rent = str(prop.get("rent_price") or "").strip()
    sale = str(prop.get("sale_price") or "").strip()

    def has_price(v: str) -> bool:
        return bool(v) and v not in {"-", "—", "0"}

    if has_price(rent):
        offers.append("rent")
    if has_price(sale):
        offers.append("sale")
    if not offers:
        offers = ["rent", "sale", "condo"]
    return offers


def _parse_price_num(v: str | None) -> int:
    try:
        return int(re.sub(r"[^\d]", "", str(v or "")) or "0")
    except ValueError:
        return 0


def _member_weight(group: dict) -> int:
    band = (group.get("member_band") or "").upper()
    return {"XL": 8, "L": 5, "M": 2, "S": 0}.get(band, 1 if group.get("core_reach") else 0)


def _norm_match_text(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[()（）\[\]【】]", " ", s)
    s = re.sub(r"[^a-z0-9ก-๙\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _project_match_keys(prop: dict) -> list[str]:
    """Tokens/phrases from project name for matching group titles."""
    name = (prop.get("project_name") or "").strip()
    if not name:
        return []
    # Shared brand fragments that alone match too many other projects
    generic = {
        "life", "ideo", "chapter", "condo", "residence", "residences",
        "tower", "park", "place", "house", "the", "and", "phase", "by", "of",
        "บ้าน", "โครงการ", "คอนโด", "แอท", "at",
    }
    keys: list[str] = []
    raw = _norm_match_text(name)
    if len(raw) >= 4:
        keys.append(raw)
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9\s\-']{2,})", name)
    if m:
        en = _norm_match_text(m.group(1))
        if len(en) >= 4 and en not in keys:
            keys.append(en)
    for w in re.split(r"[\s/\-]+", raw):
        if len(w) < 5:
            continue
        if w in generic:
            continue
        if w not in keys:
            keys.append(w)
    keys.sort(key=len, reverse=True)
    return keys[:8]


HISTORY_PATH = BASE_DIR / "data" / "group_recommend_history.json"


def _load_recommend_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("items") or []
    except Exception:  # noqa: BLE001
        return []


def _save_recommend_history(items: list[dict]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    # keep last 500
    HISTORY_PATH.write_text(
        json.dumps(items[-500:], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _fatigue_penalty(url: str, history: list[dict], *, hours: int = 72) -> tuple[int, str]:
    """Recently recommended/copied groups get a score penalty so lists rotate."""
    import time

    if not url:
        return 0, ""
    now = time.time()
    cutoff = now - hours * 3600
    hits = 0
    for h in history:
        if (h.get("url") or "") != url:
            continue
        ts = float(h.get("ts") or 0)
        if ts >= cutoff:
            hits += 1
    if hits <= 0:
        return 0, ""
    # heavier if used/copied
    used = sum(1 for h in history if (h.get("url") or "") == url and h.get("used") and float(h.get("ts") or 0) >= cutoff)
    pen = min(35, hits * 4 + used * 8)
    reason = f"หมุนเวียน (−{pen}: เพิ่งแนะนำ {hits} ครั้ง"
    if used:
        reason += f" · ใช้แล้ว {used}"
    reason += ")"
    return pen, reason


def mark_group_used(url: str, *, property_code: str = "") -> None:
    """Record that admin copied/opened a group (for rotation)."""
    import time

    url = (url or "").strip()
    if not url:
        return
    items = _load_recommend_history()
    items.append(
        {
            "url": url,
            "ts": time.time(),
            "used": True,
            "code": property_code or "",
        }
    )
    _save_recommend_history(items)


def _score_group_flat(
    g: dict,
    *,
    zones: list[str],
    offers: list[str],
    project_keys: list[str],
    project_name: str = "",
    is_luxury_prop: bool,
    history: list[dict],
) -> tuple[int, list[str], str]:
    """
    Single score for flat ranking.
    tier: project | zone | large | fit | other
    """
    gz = g.get("zone_tags") or []
    go = g.get("offer_tags") or []
    roles = g.get("role_tags") or []
    blob = _blob(g)
    name_norm = _norm_match_text(g.get("name") or "")
    score = 0
    reasons: list[str] = []
    tier = "other"

    # 1) Project name in group title — strongest (prefer longest / specific keys)
    project_hit = ""
    for key in project_keys:
        if not key:
            continue
        if key in name_norm or (len(key) >= 6 and key in blob):
            project_hit = key
            break
    if project_hit:
        # Full/long phrase >> single token
        full = _norm_match_text(project_name)
        if (full and project_hit == full) or len(project_hit) >= 10:
            score += 120
        elif len(project_hit) >= 6:
            score += 100
        else:
            score += 55
        reasons.append("ชื่อกลุ่มตรงโครงการ")
        tier = "project"

    zone_hits = [z for z in zones if z in gz and z != "bangkok"]
    # soft zone from name text
    soft_zone = False
    if not zone_hits:
        for z in zones:
            if z == "bangkok":
                continue
            for _zid, pats in ZONE_PATTERNS:
                if _zid != z:
                    continue
                if any(re.search(p, blob, re.I) for p in pats):
                    soft_zone = True
                    zone_hits = [z]
                    break

    # 2) Zone / location
    if zone_hits:
        score += 40 + 8 * (len(zone_hits) - 1)
        reasons.append("โซน: " + ", ".join(zone_hits))
        if tier != "project":
            tier = "zone"
    elif soft_zone:
        score += 28
        reasons.append("ชื่อกลุ่มมีทำเลทรัพย์")
        if tier != "project":
            tier = "zone"

    # 3) Large / citywide reach
    mw = _member_weight(g)
    if mw:
        score += mw * 3
        band = (g.get("member_band") or "").upper() or "core"
        reasons.append(f"กลุ่มใหญ่ ({band})")
        if tier in {"other", "fit"}:
            tier = "large"
    if g.get("core_reach"):
        score += 18
        reasons.append("Core Reach")
        if tier in {"other", "fit"}:
            tier = "large"
    if "citywide" in roles or "bangkok" in gz:
        score += 16
        if "citywide" in roles:
            reasons.append("กลุ่มกว้าง กทม.")
        if tier in {"other", "fit"}:
            tier = "large"
    if "mass" in roles:
        score += 10

    # 4) Offer / price-audience fit
    offer_hits = [o for o in offers if o in go and o not in {"owner_only", "agent_ok"}]
    if offer_hits:
        score += 6 * len(offer_hits)
        reasons.append("ประเภท: " + ", ".join(offer_hits))
    if "condo" in offers and "condo" in go:
        score += 4

    if is_luxury_prop:
        if "luxury" in roles or re.search(r"luxury|หรู|พรีเมียม|premium", blob, re.I):
            score += 22
            reasons.append("Luxury ตรงทรัพย์")
        if "expat" in roles:
            score += 10
            reasons.append("Expat")
    else:
        if "luxury" in roles and not zone_hits and not project_hit:
            score -= 8  # de-prioritize pure luxury for mass listings
        if "mass" in roles or "citywide" in roles:
            score += 6

    if "expat" in roles and not is_luxury_prop:
        score += 4

    # Fatigue / rotation
    pen, pen_reason = _fatigue_penalty(g.get("url") or "", history)
    if pen:
        score -= pen
        reasons.append(pen_reason)

    if score <= 0 and not project_hit and not zone_hits:
        return 0, [], tier

    if tier == "other" and score > 0:
        tier = "fit"

    return score, reasons, tier


def recommend_groups(
    prop: dict,
    *,
    limit: int = 30,
    per_category: int | None = None,
    include_owner_only: bool = False,
) -> dict:
    """
    Flat ranked list (default 30).
    Priority: project-name match → zone → large/citywide → fit,
    with diversification + light exploration + rotation.
    """
    import random
    import time

    # per_category kept for API compat but ignored for flat list size
    n = int(limit or 30)
    if per_category is not None and limit == 30:
        # old clients sent per_category=15 — treat as total if they only pass that
        pass
    if n <= 0:
        n = 30

    groups = load_groups()
    groups = [auto_tag_group(g, force=False) for g in groups]
    for g in groups:
        if not g.get("role_tags"):
            g["role_tags"] = infer_role_tags(_blob(g), g.get("zone_tags") or [])

    zones = infer_property_zones(prop)
    offers = infer_property_offers(prop)
    project_keys = _project_match_keys(prop)
    rent_n = _parse_price_num(prop.get("rent_price"))
    sale_n = _parse_price_num(prop.get("sale_price"))
    is_luxury_prop = rent_n >= 35000 or sale_n >= 8000000
    history = _load_recommend_history()

    scored: list[dict] = []
    for g in groups:
        go = g.get("offer_tags") or []
        if "owner_only" in go and "agent_ok" not in go and not include_owner_only:
            continue
        score, reasons, tier = _score_group_flat(
            g,
            zones=zones,
            offers=offers,
            project_keys=project_keys,
            project_name=prop.get("project_name") or "",
            is_luxury_prop=is_luxury_prop,
            history=history,
        )
        if score <= 0:
            continue
        scored.append(
            {
                "name": g.get("name") or "",
                "url": g.get("url") or "",
                "zone_tags": g.get("zone_tags") or [],
                "offer_tags": go,
                "role_tags": g.get("role_tags") or [],
                "member_band": g.get("member_band") or "",
                "core_reach": bool(g.get("core_reach")),
                "score": score,
                "reasons": reasons,
                "tier": tier,
                "notes": g.get("notes") or "",
            }
        )

    scored.sort(key=lambda x: (-x["score"], x["name"].lower()))

    # Diversified pick into flat 30, then re-sort by score for display
    quotas = {
        "project": max(6, n // 4),
        "zone": max(8, n // 3),
        "large": max(6, n // 4),
        "fit": max(4, n // 6),
        "other": 2,
    }
    explore_slots = max(3, n // 10)  # ~10% exploration
    picked: list[dict] = []
    seen: set[str] = set()
    counts = {k: 0 for k in quotas}

    def _take(item: dict, *, relax: bool = False) -> bool:
        u = item["url"] or item["name"]
        if u in seen:
            return False
        t = item.get("tier") or "other"
        if not relax and counts.get(t, 0) >= quotas.get(t, 99):
            return False
        seen.add(u)
        counts[t] = counts.get(t, 0) + 1
        picked.append(item)
        return True

    # Pass 1: fill by tier priority (respect quotas for diversity)
    for tier_name in ("project", "zone", "large", "fit", "other"):
        for item in scored:
            if len(picked) >= n - explore_slots:
                break
            if item.get("tier") != tier_name:
                continue
            _take(item, relax=False)
        if len(picked) >= n - explore_slots:
            break

    # Pass 2: fill remaining with next best (ignore quotas)
    for item in scored:
        if len(picked) >= n - explore_slots:
            break
        _take(item, relax=True)

    # Pass 3: exploration — sample from mid-tier candidates not yet picked
    pool = [x for x in scored[10:120] if (x["url"] or x["name"]) not in seen]
    if pool and len(picked) < n:
        random.shuffle(pool)
        for item in pool:
            if len(picked) >= n:
                break
            item = dict(item)
            item["reasons"] = list(item.get("reasons") or []) + ["สำรวจกลุ่มใหม่"]
            item["score"] = max(1, int(item["score"]) - 5)
            _take(item, relax=True)

    # Final display order: score high → low
    picked.sort(key=lambda x: (-x["score"], x["name"].lower()))
    picked = picked[:n]

    # Record recommendation history for rotation
    now = time.time()
    code = (prop.get("code") or "").strip()
    for item in picked:
        if item.get("url"):
            history.append({"url": item["url"], "ts": now, "used": False, "code": code})
    _save_recommend_history(history)

    return {
        "zones": zones,
        "offers": offers,
        "project_keys": project_keys,
        "is_luxury_property": is_luxury_prop,
        "limit": n,
        "total_groups": len(groups),
        "matched": len(picked),
        "groups": picked,
        # empty categories for old UI safety
        "categories": [],
        "mode": "flat_v2",
        "strategy": "project→zone→large + diversify/explore/rotate",
    }


def list_groups_summary() -> dict:
    groups = load_groups()
    by_zone: dict[str, int] = {}
    for g in groups:
        for z in g.get("zone_tags") or ["(ยังไม่แท็ก)"]:
            by_zone[z] = by_zone.get(z, 0) + 1
    return {
        "total": len(groups),
        "by_zone": dict(sorted(by_zone.items(), key=lambda x: -x[1])),
        "groups": groups,
    }
