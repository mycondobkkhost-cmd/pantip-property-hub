"""PropertyHub project page client — name + nearbyZones (transit / landmarks)."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote

from src.hub.scraper import DESKTOP_UA, _http_get

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = BASE_DIR / "data" / "propertyhub_cache"

# English / romanized zone labels → Hub Thai chips
ZONE_EN_TO_TH: dict[str, str] = {
    "huai khwang": "ห้วยขวาง",
    "huaikhwang": "ห้วยขวาง",
    "watthana": "วัฒนา",
    "vadhana": "วัฒนา",
    "khlong toei": "คลองเตย",
    "klong toei": "คลองเตย",
    "pathum wan": "ปทุมวัน",
    "pathumwan": "ปทุมวัน",
    "bang rak": "บางรัก",
    "bangrak": "บางรัก",
    "sathon": "สาทร",
    "sathorn": "สาทร",
    "bang na": "บางนา",
    "bangna": "บางนา",
    "phra khanong": "พระโขนง",
    "phrakanong": "พระโขนง",
    "rat chathewi": "ราชเทวี",
    "ratchathewi": "ราชเทวี",
    "din daeng": "ดินแดง",
    "dindaeng": "ดินแดง",
    "chatuchak": "จตุจักร",
    "lat phrao": "ลาดพร้าว",
    "ladprao": "ลาดพร้าว",
    "bang sue": "บางซื่อ",
    "bangsue": "บางซื่อ",
    "thong lor": "ทองหล่อ",
    "thonglo": "ทองหล่อ",
    "thonglor": "ทองหล่อ",
    "ekkamai": "เอกมัย",
    "ekamai": "เอกมัย",
    "asoke": "อโศก",
    "asok": "อโศก",
    "rama 9": "พระราม 9",
    "rama9": "พระราม 9",
    "new petchburi": "เพชรบุรีตัดใหม่",
    "new phetchaburi": "เพชรบุรีตัดใหม่",
    "petchburi road": "เพชรบุรี",
    "phetchaburi road": "เพชรบุรี",
    "sukhumvit": "สุขุมวิท",
    "silom": "สีลม",
    "ari": "อารีย์",
    "arree": "อารีย์",
    "phaya thai": "พญาไท",
    "rca": "RCA",
}

LANDMARK_EN_TO_TH: dict[str, str] = {
    "bangkok hospital": "โรงพยาบาลกรุงเทพ",
    "phraram 9 hospital": "โรงพยาบาลพระราม 9",
    "rama 9 hospital": "โรงพยาบาลพระราม 9",
    "piyawet hospital": "โรงพยาบาลพญาไท",
    "piyavate hospital": "โรงพยาบาลพญาไท",
    "camillian hospital": "โรงพยาบาลคามิลเลียน",
    "srinakharinwirot university prasanmit campus": "มศว ประสานมิตร",
    "srinakharinwirot university": "มศว ประสานมิตร",
    "j avenue thonglor": "J Avenue",
    "j avenue": "J Avenue",
    "big c super center ekkamai": "Big C เอกมัย",
    "big c ekkamai": "Big C เอกมัย",
    "donki mall thonglor": "Donki Thonglor",
    "terminal 21": "Terminal 21",
    "central plaza rama 9": "เซ็นทรัล พระราม 9",
    "emquartier": "EmQuartier",
    "emporium": "Emporium",
    "emsphere": "EMSPHERE",
}


@dataclass
class PropertyHubLocation:
    name: str = ""
    name_english: str = ""
    address: str = ""
    slug: str = ""
    url: str = ""
    zones: list[str] = field(default_factory=list)
    transit: list[str] = field(default_factory=list)
    nearby_places: list[str] = field(default_factory=list)
    lat: float | None = None
    lng: float | None = None
    ok: bool = False
    error: str = ""
    raw_nearby_keys: list[str] = field(default_factory=list)


def slugify_project_name(name: str) -> str:
    """Best-effort PropertyHub slug from a display name."""
    s = (name or "").strip()
    # Drop Thai parenthetical
    s = re.sub(r"[（(][^)）]*[)）]", " ", s)
    s = s.lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def propertyhub_project_url(slug_or_name: str, *, lang: str = "en") -> str:
    slug = (slug_or_name or "").strip()
    if not slug:
        return ""
    if "propertyhub.in.th" in slug:
        return slug
    if "/" in slug and " " not in slug:
        path = slug.lstrip("/")
    else:
        path = f"projects/{slugify_project_name(slug)}"
    return f"https://propertyhub.in.th/{lang}/{path}"


def _cache_path(url: str) -> Path:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / f"{digest}.json"


def _load_cache(url: str, *, max_age_sec: int = 14 * 24 * 3600) -> dict | None:
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    ts = float(data.get("fetched_at") or 0)
    if ts and (time.time() - ts) > max_age_sec:
        return None
    return data


def _save_cache(url: str, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["fetched_at"] = time.time()
    payload["url"] = url
    _cache_path(url).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _decode_next_f_string(escaped: str) -> str:
    try:
        return escaped.encode("utf-8").decode("unicode_escape")
    except Exception:  # noqa: BLE001
        return escaped


def _extract_project_dict(html: str) -> dict[str, Any] | None:
    """Pull the RSC-embedded project object from a PropertyHub project page."""
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S | re.I)
    big = sorted(
        (s for s in scripts if '"project":{' in s or "\\\"project\\\":{" in s),
        key=len,
        reverse=True,
    )
    if not big:
        # Fallback: any script mentioning nearbyZones
        big = sorted((s for s in scripts if "nearbyZones" in s), key=len, reverse=True)
    if not big:
        return None

    blob = big[0]
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', blob)
    texts: list[str] = []
    if chunks:
        texts.extend(_decode_next_f_string(c) for c in chunks)
    texts.append(blob)

    for text in texts:
        idx = text.find('"project":{')
        if idx < 0:
            idx = text.find('"project": {')
        if idx < 0:
            continue
        start = text.find("{", idx)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        end = None
        for i, ch in enumerate(text[start:], start):
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            continue
        raw = text[start:end]
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and (obj.get("slug") or obj.get("nearbyZones") or obj.get("name")):
            return obj
    return None


def _norm_en(label: str) -> str:
    return re.sub(r"\s+", " ", (label or "").strip().lower())


def _thai_zone(label: str) -> str | None:
    n = _norm_en(label)
    if not n:
        return None
    if n in ZONE_EN_TO_TH:
        return ZONE_EN_TO_TH[n]
    # partial contains
    for en, th in ZONE_EN_TO_TH.items():
        if en in n or n in en:
            return th
    # already Thai
    if re.search(r"[ก-๙]", label):
        return re.sub(r"\s+", " ", label.strip())
    return None


def _thai_landmark(label: str) -> str:
    n = _norm_en(label)
    if n in LANDMARK_EN_TO_TH:
        return LANDMARK_EN_TO_TH[n]
    for en, th in LANDMARK_EN_TO_TH.items():
        if en in n:
            return th
    if re.search(r"[ก-๙]", label):
        return re.sub(r"\s+", " ", label.strip())
    # Keep short English landmark names
    return re.sub(r"\s+", " ", (label or "").strip())


def _station_from_ph(name: str) -> str | None:
    from src.hub.project_location_enrich import canonicalize_station

    raw = (name or "").strip()
    if not raw:
        return None
    canon = canonicalize_station(raw)
    if canon:
        return canon
    # "BTS Thong Lo (Thong Lor)" already handled by aliases; try stripping paren
    bare = re.sub(r"\([^)]*\)", " ", raw)
    bare = re.sub(r"\s+", " ", bare).strip()
    return canonicalize_station(bare)


def parse_propertyhub_project(html: str, *, url: str = "") -> PropertyHubLocation:
    out = PropertyHubLocation(url=url)
    proj = _extract_project_dict(html)
    if not proj:
        out.error = "no_project_payload"
        return out

    out.name = str(proj.get("name") or "").strip()
    out.name_english = str(proj.get("nameEnglish") or out.name).strip()
    out.address = str(proj.get("address") or "").strip()
    out.slug = str(proj.get("slug") or "").strip()
    loc = proj.get("location") or {}
    if isinstance(loc, dict):
        try:
            out.lat = float(loc["lat"]) if loc.get("lat") is not None else None
            out.lng = float(loc["lng"]) if loc.get("lng") is not None else None
        except (TypeError, ValueError):
            pass

    nearby = proj.get("nearbyZones") or {}
    if not isinstance(nearby, dict):
        nearby = {}
    out.raw_nearby_keys = sorted(nearby.keys())

    zones: list[str] = []
    transit: list[str] = []
    nearby_places: list[str] = []

    def add_zone(label: str | None) -> None:
        if not label:
            return
        if label not in zones:
            zones.append(label)

    def add_transit(label: str | None) -> None:
        if not label:
            return
        if label not in transit:
            transit.append(label)

    def add_nearby(label: str | None, *, max_n: int = 8) -> None:
        if not label or len(nearby_places) >= max_n:
            return
        if label not in nearby_places and label not in zones:
            nearby_places.append(label)

    # Districts / areas / roads → ทำเล
    for key in ("DISTRICT", "AREA", "ROAD"):
        for item in nearby.get(key) or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            # Skip piers / noisy AREA unless Thonglor-ish
            if key == "AREA" and "pier" in name.lower():
                continue
            z = _thai_zone(name)
            if z:
                add_zone(z)

    # Mass transit
    for item in nearby.get("MASS_TRANSIT") or []:
        if not isinstance(item, dict):
            continue
        add_transit(_station_from_ph(str(item.get("name") or "")))

    # Landmarks — hospitals / shopping within ~2.5km preferred
    for key in ("HOSPITAL", "SHOPPING"):
        items = list(nearby.get(key) or [])
        items.sort(
            key=lambda it: (
                it.get("distance") is None,
                float(it.get("distance") or 9_999_999),
            )
        )
        for item in items[:6]:
            if not isinstance(item, dict):
                continue
            dist = item.get("distance")
            if dist is not None:
                try:
                    if float(dist) > 2800:
                        continue
                except (TypeError, ValueError):
                    pass
            label = _thai_landmark(str(item.get("name") or ""))
            # Known hospital/university chips also go into ทำเล
            if any(x in label for x in ("โรงพยาบาลกรุงเทพ", "มศว", "RCA")):
                add_zone(label)
            add_nearby(label)

    # Address blob may contain district
    if out.address:
        for part in re.split(r"[,/|]", out.address):
            z = _thai_zone(part)
            if z:
                add_zone(z)

    out.zones = zones[:5]
    out.transit = transit[:3]
    out.nearby_places = nearby_places[:8]
    out.ok = bool(out.name or out.zones or out.transit or out.nearby_places)
    if not out.ok:
        out.error = "empty_location"
    return out


def fetch_propertyhub_location(
    url_or_slug: str,
    *,
    use_cache: bool = True,
    sleep_s: float = 0.55,
    lang: str = "en",
    retries: int = 2,
) -> PropertyHubLocation:
    url = propertyhub_project_url(url_or_slug, lang=lang)
    if not url:
        return PropertyHubLocation(error="empty_url")

    if use_cache:
        cached = _load_cache(url)
        if cached and "html" in cached:
            loc = parse_propertyhub_project(cached["html"], url=url)
            if loc.ok:
                return loc

    last_err = ""
    for attempt in range(max(1, retries + 1)):
        if sleep_s > 0:
            time.sleep(sleep_s if attempt == 0 else sleep_s * (attempt + 1))
        try:
            html = _http_get(url, DESKTOP_UA)
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue

        if not html or len(html) < 500:
            last_err = "empty_html"
            continue

        if use_cache:
            _save_cache(url, {"html": html, "final_url": url})

        loc = parse_propertyhub_project(html, url=url)
        if loc.ok:
            return loc
        last_err = loc.error or "parse_failed"

    return PropertyHubLocation(url=url, error=last_err or "fetch_failed")


def location_to_dict(loc: PropertyHubLocation) -> dict:
    return asdict(loc)
