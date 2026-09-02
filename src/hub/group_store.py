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


def _parse_group_tags(raw: str | list[str] | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in re.split(r"[,|/\n]+", str(raw)) if x.strip()]


def _normalize_group_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if re.match(r"^https?://", u, re.I):
        return u
    if re.match(r"^(www\.|facebook\.com|fb\.com|m\.facebook\.com)", u, re.I):
        return "https://" + u
    return u


def _group_from_payload(payload: dict, *, base: dict | None = None) -> dict:
    g = dict(base or {})
    name = (payload.get("name") if "name" in payload else g.get("name") or "").strip()
    url = _normalize_group_url(
        payload.get("url") if "url" in payload else g.get("url") or ""
    )
    if not name:
        raise ValueError("กรุณาระบุชื่อกลุ่ม")
    if not url:
        raise ValueError("กรุณาระบุลิงก์กลุ่ม Facebook")
    g["name"] = name
    g["url"] = url
    if "notes" in payload:
        g["notes"] = (payload.get("notes") or "").strip()
    else:
        g.setdefault("notes", "")
    if "zone_tags" in payload:
        g["zone_tags"] = _parse_group_tags(payload.get("zone_tags"))
    if "offer_tags" in payload:
        g["offer_tags"] = _parse_group_tags(payload.get("offer_tags"))
    if "role_tags" in payload:
        g["role_tags"] = _parse_group_tags(payload.get("role_tags"))
    if "price_band" in payload:
        g["price_band"] = (payload.get("price_band") or "").strip()
    if "member_band" in payload:
        g["member_band"] = (payload.get("member_band") or "").strip()
    if "core_reach" in payload:
        g["core_reach"] = bool(payload.get("core_reach"))
    # Auto-fill empty tag fields from name/url; keep explicit user tags.
    return auto_tag_group(g, force=False)


def create_group(payload: dict) -> dict:
    """Append a Facebook group to facebook_groups.json."""
    groups = load_groups()
    group = _group_from_payload(payload)
    url = group["url"]
    if any((g.get("url") or "").strip() == url for g in groups):
        raise ValueError("มีกลุ่มนี้อยู่แล้ว (URL ซ้ำ)")
    groups.append(group)
    save_groups(groups)
    return group


def update_group(url: str, payload: dict) -> dict:
    """Update an existing group identified by current URL."""
    key = _normalize_group_url(url)
    if not key:
        raise ValueError("ไม่พบกลุ่ม")
    groups = load_groups()
    idx = next(
        (i for i, g in enumerate(groups) if (g.get("url") or "").strip() == key),
        None,
    )
    if idx is None:
        raise ValueError("ไม่พบกลุ่ม")
    group = _group_from_payload(payload, base=groups[idx])
    new_url = group["url"]
    if new_url != key and any(
        (g.get("url") or "").strip() == new_url for i, g in enumerate(groups) if i != idx
    ):
        raise ValueError("URL ใหม่ซ้ำกับกลุ่มอื่น")
    groups[idx] = group
    save_groups(groups)
    return group


def retag_all() -> dict:
    groups = load_groups(retag=True)
    save_groups(groups)
    tagged = sum(1 for g in groups if g.get("zone_tags") or g.get("offer_tags") or g.get("role_tags"))
    return {"total": len(groups), "tagged": tagged}


def infer_property_zones(prop: dict) -> list[str]:
    transit = prop.get("transit_tags") or prop.get("transit_from_sheet") or []
    if isinstance(transit, str):
        transit = [transit]
    parts = [
        prop.get("project_name") or "",
        prop.get("location_ref") or "",
        " ".join(str(x) for x in transit if x),
        prop.get("notes") or "",
        prop.get("raw_text") or "",
        prop.get("page_post_text") or "",
        prop.get("text_th") or "",
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


def _transit_match_keys(prop: dict) -> list[str]:
    """Station / transit phrases for ranking (BTS ทองหล่อ, MRT เพชรบุรี, …)."""
    raw = prop.get("transit_tags") or prop.get("transit_from_sheet") or []
    if isinstance(raw, str):
        raw = [raw]
    keys: list[str] = []
    for item in raw:
        n = _norm_match_text(str(item or ""))
        if not n:
            continue
        if n not in keys:
            keys.append(n)
        # drop carrier prefix → station name
        bare = re.sub(r"^(bts|mrt|arl|apl|srt)\s*", "", n).strip()
        if len(bare) >= 3 and bare not in keys:
            keys.append(bare)
    return keys[:12]


_OWNER_ONLY_NAME_RE = re.compile(
    r"เจ้าของห้อง|เจ้าของโพส|owner\s*only|owners?\s*only|by\s*owner|"
    r"condo\s*owner|ห้ามเอเจน|ห้ามนายหน้า|ห้ามเอเจนต์|业主|only\s*owner",
    re.I,
)


def _is_blocked_owner_group(g: dict) -> bool:
    """Never recommend owner-only groups for agent publish (ban risk)."""
    go = g.get("offer_tags") or []
    if "owner_only" in go:
        return True
    blob = _blob(g)
    if _OWNER_ONLY_NAME_RE.search(blob):
        return True
    return False


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


def _zone_location_tokens() -> set[str]:
    """Zone/area words that must NOT count as project-name matches."""
    out: set[str] = {"bangkok", "กรุงเทพ", "กทม"}
    for zid, pats in ZONE_PATTERNS:
        out.add(_norm_match_text(zid))
        for p in pats:
            lit = re.sub(r"\\[sb]|[\\^$.*+?{}\[\]|()]", " ", p)
            lit = _norm_match_text(lit)
            if len(lit) >= 3:
                out.add(lit)
            for w in lit.split():
                if len(w) >= 3:
                    out.add(w)
    return out


_ZONE_LOCATION_TOKENS = _zone_location_tokens()


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
    if len(raw) >= 4 and raw not in _ZONE_LOCATION_TOKENS:
        keys.append(raw)
    m = re.match(r"^([A-Za-z0-9][A-Za-z0-9\s\-']{2,})", name)
    if m:
        en = _norm_match_text(m.group(1))
        if len(en) >= 4 and en not in keys and en not in _ZONE_LOCATION_TOKENS:
            keys.append(en)
    for w in re.split(r"[\s/\-]+", raw):
        if len(w) < 5:
            continue
        if w in generic or w in _ZONE_LOCATION_TOKENS:
            continue
        if w not in keys:
            keys.append(w)
    # Drop keys that are only zone/area names (e.g. "ทองหล่อ", "thonglor")
    keys = [k for k in keys if k not in _ZONE_LOCATION_TOKENS]
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
    transit_keys: list[str] | None = None,
    is_luxury_prop: bool,
    history: list[dict],
) -> tuple[int, list[str], str]:
    """
    Score for relevance ranking.
    tier: project | transit | zone | large | fit | other
    """
    gz = g.get("zone_tags") or []
    go = g.get("offer_tags") or []
    roles = g.get("role_tags") or []
    blob = _blob(g)
    name_norm = _norm_match_text(g.get("name") or "")
    score = 0
    reasons: list[str] = []
    tier = "other"
    transit_keys = transit_keys or []

    # 1) Project name in group title — strongest
    project_hit = ""
    for key in project_keys:
        if not key:
            continue
        if key in name_norm or (len(key) >= 6 and key in blob):
            project_hit = key
            break
    if project_hit:
        full = _norm_match_text(project_name)
        if (full and project_hit == full) or len(project_hit) >= 10:
            score += 200
        elif len(project_hit) >= 6:
            score += 160
        else:
            score += 90
        reasons.append("ชื่อกลุ่มตรงโครงการ")
        tier = "project"

    # 2) Transit / station match
    transit_hits = []
    for key in transit_keys:
        if not key or len(key) < 3:
            continue
        if key in name_norm or key in blob:
            transit_hits.append(key)
    if transit_hits:
        score += 55 + 12 * (len(transit_hits) - 1)
        reasons.append("สถานี: " + ", ".join(transit_hits[:3]))
        if tier not in {"project"}:
            tier = "transit"

    prop_zones = [z for z in zones if z != "bangkok"]
    zone_hits = [z for z in prop_zones if z in gz]
    soft_zone = False
    if not zone_hits:
        for z in prop_zones:
            for _zid, pats in ZONE_PATTERNS:
                if _zid != z:
                    continue
                if any(re.search(p, blob, re.I) for p in pats):
                    soft_zone = True
                    zone_hits = [z]
                    break
            if soft_zone:
                break

    # 3) Zone / location
    if zone_hits:
        # Prefer primary zone (first) over parent-only (e.g. sukhumvit)
        primary = prop_zones[0] if prop_zones else ""
        if primary and primary in zone_hits:
            score += 70
        else:
            score += 42
        score += 8 * max(0, len(zone_hits) - 1)
        reasons.append("โซน: " + ", ".join(zone_hits))
        if tier not in {"project", "transit"}:
            tier = "zone"
    elif soft_zone:
        score += 32
        reasons.append("ชื่อกลุ่มมีทำเลทรัพย์")
        if tier not in {"project", "transit"}:
            tier = "zone"

    # Penalize clearly unrelated local zones (not citywide / not project)
    other_local = [z for z in gz if z not in {"bangkok"} and z not in prop_zones and z not in zone_hits]
    if other_local and not project_hit and not transit_hits and tier not in {"project", "transit"}:
        # e.g. Tao Poon / Bang Pho when listing is Thonglor
        if not zone_hits and "citywide" not in roles:
            score -= 50
            reasons.append("โซนไม่ตรงทรัพย์")

    # 4) Large / citywide — only as lower-priority filler
    mw = _member_weight(g)
    if mw:
        score += mw * 2
        band = (g.get("member_band") or "").upper() or "core"
        reasons.append(f"กลุ่มใหญ่ ({band})")
        if tier in {"other", "fit"}:
            tier = "large"
    if g.get("core_reach"):
        score += 10
        reasons.append("Core Reach")
        if tier in {"other", "fit"}:
            tier = "large"
    if "citywide" in roles or "bangkok" in gz:
        score += 8
        if "citywide" in roles:
            reasons.append("กลุ่มกว้าง กทม.")
        if tier in {"other", "fit"}:
            tier = "large"
    if "mass" in roles:
        score += 4

    # Without project/zone/transit, citywide gets weaker priority
    if not project_hit and not zone_hits and not transit_hits and tier == "large":
        score -= 15

    # 5) Offer fit
    offer_hits = [o for o in offers if o in go and o not in {"owner_only", "agent_ok"}]
    if offer_hits:
        score += 6 * len(offer_hits)
        reasons.append("ประเภท: " + ", ".join(offer_hits))
    if "condo" in offers and "condo" in go:
        score += 4

    if is_luxury_prop:
        if "luxury" in roles or re.search(r"luxury|หรู|พรีเมียม|premium", blob, re.I):
            score += 18
            reasons.append("Luxury ตรงทรัพย์")
    else:
        if "luxury" in roles and not zone_hits and not project_hit:
            score -= 8

    # Fatigue / rotation (light)
    pen, pen_reason = _fatigue_penalty(g.get("url") or "", history)
    if pen:
        score -= min(pen, 20)
        reasons.append(pen_reason)

    if score <= 0 and not project_hit and not zone_hits and not transit_hits:
        return 0, [], tier

    if tier == "other" and score > 0:
        tier = "fit"

    return score, reasons, tier


def recommend_groups(
    prop: dict,
    *,
    limit: int = 60,
    per_category: int | None = None,
    include_owner_only: bool = False,
) -> dict:
    """
    Ranked list: project → transit → zone → large/fit.
    Owner-only groups are always excluded for publish safety.
    """
    import time

    n = int(limit or 60)
    if n <= 0:
        n = 60
    n = min(max(n, 10), 120)

    groups = load_groups()
    groups = [auto_tag_group(g, force=False) for g in groups]
    for g in groups:
        if not g.get("role_tags"):
            g["role_tags"] = infer_role_tags(_blob(g), g.get("zone_tags") or [])

    zones = infer_property_zones(prop)
    offers = infer_property_offers(prop)
    project_keys = _project_match_keys(prop)
    transit_keys = _transit_match_keys(prop)
    rent_n = _parse_price_num(prop.get("rent_price"))
    sale_n = _parse_price_num(prop.get("sale_price"))
    is_luxury_prop = rent_n >= 35000 or sale_n >= 8000000
    history = _load_recommend_history()

    scored: list[dict] = []
    skipped_owner = 0
    for g in groups:
        if not include_owner_only and _is_blocked_owner_group(g):
            skipped_owner += 1
            continue
        score, reasons, tier = _score_group_flat(
            g,
            zones=zones,
            offers=offers,
            project_keys=project_keys,
            project_name=prop.get("project_name") or "",
            transit_keys=transit_keys,
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
                "offer_tags": g.get("offer_tags") or [],
                "role_tags": g.get("role_tags") or [],
                "member_band": g.get("member_band") or "",
                "core_reach": bool(g.get("core_reach")),
                "score": score,
                "reasons": reasons,
                "tier": tier,
                "notes": g.get("notes") or "",
            }
        )

    # Strict relevance order — no random exploration that buries project matches
    tier_rank = {"project": 0, "transit": 1, "zone": 2, "large": 3, "fit": 4, "other": 5}
    scored.sort(
        key=lambda x: (
            tier_rank.get(x.get("tier") or "other", 9),
            -int(x.get("score") or 0),
            (x.get("name") or "").lower(),
        )
    )
    picked = scored[:n]

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
        "transit_keys": transit_keys,
        "project_name": prop.get("project_name") or "",
        "code": code,
        "is_luxury_property": is_luxury_prop,
        "limit": n,
        "total_groups": len(groups),
        "matched": len(picked),
        "skipped_owner": skipped_owner,
        "groups": picked,
        "categories": [],
        "mode": "relevance_v3",
        "strategy": "project→transit→zone→large (no owner-only)",
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


def merge_joined_groups_from_account(
    items: list[dict],
    *,
    account_id: str = "",
    account_label: str = "",
) -> dict:
    """Merge groups scraped from FB joins into the book; mark membership_by_account."""
    groups = load_groups()
    by_url = {_normalize_group_url(str(g.get("url") or "")): g for g in groups}
    added = 0
    updated = 0
    aid = (account_id or account_label or "default").strip() or "default"
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        url = _normalize_group_url(str(raw.get("url") or ""))
        name = str(raw.get("name") or "").strip()
        if not url or "facebook.com/groups/" not in url:
            continue
        status = str(raw.get("membership") or raw.get("status") or "joined").strip() or "joined"
        if url in by_url:
            g = by_url[url]
            memb = g.get("membership_by_account")
            if not isinstance(memb, dict):
                memb = {}
            memb[aid] = status
            g["membership_by_account"] = memb
            if account_label:
                g["source_account"] = account_label
            if name and (not g.get("name") or g.get("name") in {"?", "กลุ่ม"}):
                g["name"] = name
            updated += 1
        else:
            g = auto_tag_group(
                {
                    "name": name or url.rstrip("/").split("/")[-1],
                    "url": url,
                    "notes": "",
                    "source_account": account_label or aid,
                    "membership_by_account": {aid: status},
                },
                force=True,
            )
            groups.append(g)
            by_url[url] = g
            added += 1
    save_groups(groups)
    return {
        "ok": True,
        "added": added,
        "updated": updated,
        "total": len(groups),
        "account_id": aid,
    }


def membership_for_account(group: dict, account_id: str) -> str:
    """Return joined|pending|unknown for a group x FB account."""
    memb = group.get("membership_by_account")
    if isinstance(memb, dict):
        v = str(memb.get(account_id) or memb.get("default") or "").strip()
        if v:
            return v
    src = str(group.get("source_account") or "").strip()
    if src and account_id and (src == account_id or account_id in src):
        return "joined"
    return "unknown"

