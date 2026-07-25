"""Livinginsider listing/project client — sole authority for BTS + ทำเล."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlsplit, urlunsplit

from src.hub.scraper import DESKTOP_UA, _http_get

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = BASE_DIR / "data" / "living_cache"


def encode_living_url(url: str) -> str:
    """Percent-encode non-ASCII path segments (Living project slugs are Thai)."""
    parts = urlsplit((url or "").strip())
    if not parts.scheme or not parts.netloc:
        return url
    return urlunsplit(
        (parts.scheme, parts.netloc, quote(parts.path, safe="/%"), parts.query, parts.fragment)
    )

# Map markers / titles that look like rail stations
_STATION_TITLE_RE = re.compile(
    r"^(?:BTS|MRT|ARL|APL|Airport\s*Link|สถานี)\s*.{1,40}$",
    re.I,
)
_NAV_NOISE = re.compile(
    r"สถานีอื่นๆ|เลือกสถานี|คอนโดแนว|บ้านแนว|ทำเลยอดนิยม|ใกล้รถไฟฟ้า$",
    re.I,
)


@dataclass
class LivingLocation:
    zone: str = ""
    stations: list[str] = field(default_factory=list)
    project_name: str = ""
    project_url: str = ""
    source_url: str = ""
    ok: bool = False
    error: str = ""


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


def _uniq(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        label = re.sub(r"\s+", " ", (raw or "").strip())
        if not label:
            continue
        key = re.sub(r"[^a-z0-9ก-๙]", "", label.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def living_project_stations_trusted(stations: list[str], *, zone: str) -> bool:
    """Reject Living *project* page map pins that are known SEO pollution."""
    if not stations:
        return True
    blob_n = re.sub(r"[^a-z0-9ก-๙]", "", f"{zone}".lower())
    station_n = re.sub(r"[^a-z0-9ก-๙]", "", " ".join(stations).lower())
    inland = any(
        x in blob_n
        for x in (
            "ทองหล่อ",
            "thonglo",
            "เอกมัย",
            "ekkamai",
            "พระราม9",
            "rama9",
            "เพชรบุรี",
            "phetchaburi",
            "อโศก",
            "asok",
            "รัชดา",
            "ratchada",
            "ห้วยขวาง",
        )
    )
    riverside = any(x in station_n for x in ("เจริญนคร", "กรุงธนบุรี", "wongwian", "วงเวียน"))
    if inland and riverside:
        return False
    return True


def canonicalize_living_station(raw: str) -> str | None:
    """Normalize Living map titles → canonical BTS/MRT/ARL labels."""
    t = re.sub(r"\s+", " ", (raw or "").strip())
    if not t or _NAV_NOISE.search(t):
        return None
    t = re.sub(r"^สถานี\s+", "", t, flags=re.I)
    t = re.sub(r"^airport\s*link\s+", "ARL ", t, flags=re.I)
    t = re.sub(r"^APL\s+", "ARL ", t, flags=re.I)
    # Living sometimes emits "BTS  ทองหล่อ"
    t = re.sub(r"^(BTS|MRT|ARL)\s+", lambda m: m.group(1).upper() + " ", t, flags=re.I)

    try:
        from src.hub.project_location_enrich import canonicalize_station

        canon = canonicalize_station(t)
        if canon:
            return canon
    except Exception:  # noqa: BLE001
        pass

    if re.match(r"^(BTS|MRT|ARL)\s+\S", t, re.I):
        return t[:50]
    # bare Thai station name from map (e.g. after stripping สถานี)
    if re.match(r"^[ก-๙A-Za-z0-9 .]+$", t) and 2 <= len(t) <= 40:
        try:
            from src.hub.project_location_enrich import canonicalize_station

            for prefix in ("BTS ", "MRT ", "ARL "):
                canon = canonicalize_station(prefix + t)
                if canon:
                    return canon
        except Exception:  # noqa: BLE001
            pass
    return None


def parse_living_html(html: str, *, source_url: str = "") -> LivingLocation:
    """Extract Living zone (breadcrumb) + nearest stations (map markers)."""
    loc = LivingLocation(source_url=source_url)

    # BreadcrumbList → living_zone + living_project
    for m in re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    ):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict) or data.get("@type") != "BreadcrumbList":
            continue
        for item in data.get("itemListElement") or []:
            if not isinstance(item, dict):
                continue
            name = unescape(str(item.get("name") or "")).strip()
            href = str(item.get("item") or "")
            if "living_zone" in href and name:
                loc.zone = name
            if "living_project" in href and name:
                loc.project_name = name
                loc.project_url = href

    # Nearby transit map markers (authoritative nearest stations)
    titles: list[str] = []
    for m in re.finditer(
        r'data-imgloc="transit-pin[^"]*"[^>]*title="([^"]+)"|'
        r'title="([^"]+)"[^>]*data-imgloc="transit-pin',
        html,
        re.I,
    ):
        titles.append(unescape(m.group(1) or m.group(2) or ""))

    # Fallback: any title that looks like a station near nrList / living_transit
    if not titles:
        for m in re.finditer(r'title="((?:BTS|MRT|ARL|Airport\s*Link|APL|สถานี)[^"]{1,40})"', html, re.I):
            titles.append(unescape(m.group(1)))

    stations: list[str] = []
    for title in titles:
        if not _STATION_TITLE_RE.match(title.strip()) and not title.strip().upper().startswith(
            ("BTS", "MRT", "ARL", "APL", "AIRPORT")
        ):
            # allow bare "สถานี Xxx"
            if not title.strip().startswith("สถานี"):
                continue
        canon = canonicalize_living_station(title)
        if canon:
            stations.append(canon)

    loc.stations = _uniq(stations)[:5]
    loc.ok = bool(loc.zone or loc.stations)
    if not loc.ok:
        loc.error = "no_zone_or_stations"
    return loc


def fetch_living_location(
    url: str,
    *,
    use_cache: bool = True,
    sleep_s: float = 0.0,
) -> LivingLocation:
    """Fetch one Living listing page and parse zone + stations."""
    url = (url or "").strip()
    if not url.startswith("http") or "livinginsider" not in urlparse(url).netloc.lower():
        return LivingLocation(source_url=url, error="not_living_url")

    if use_cache:
        cached = _load_cache(url)
        if cached and cached.get("parsed"):
            p = cached["parsed"]
            return LivingLocation(
                zone=p.get("zone") or "",
                stations=list(p.get("stations") or []),
                project_name=p.get("project_name") or "",
                project_url=p.get("project_url") or "",
                source_url=url,
                ok=bool(p.get("ok")),
                error=p.get("error") or "",
            )

    if sleep_s > 0:
        time.sleep(sleep_s)

    fetch_url = encode_living_url(url)
    try:
        html = _http_get(fetch_url, DESKTOP_UA)
    except HTTPError as exc:
        return LivingLocation(source_url=url, error=f"http_{exc.code}")
    except URLError as exc:
        return LivingLocation(source_url=url, error=f"url:{exc.reason}")
    except Exception as exc:  # noqa: BLE001
        return LivingLocation(source_url=url, error=str(exc)[:120])

    loc = parse_living_html(html, source_url=url)
    # Project list pages often pin far SEO stations (เจริญนคร/กรุงธนบุรี on
    # Thonglor/Rama9 projects). Prefer listing pages for transit; keep zone.
    if "/living_project/" in urlparse(url).path.lower() and loc.stations:
        if not living_project_stations_trusted(loc.stations, zone=loc.zone):
            loc.stations = []
    if use_cache:
        _save_cache(
            url,
            {
                "parsed": asdict(loc),
                "html_len": len(html),
            },
        )
    return loc


def consensus_location(samples: list[LivingLocation]) -> LivingLocation:
    """Vote across listing samples for one project."""
    from collections import Counter

    ok_samples = [s for s in samples if s.ok]
    if not ok_samples:
        err = samples[0].error if samples else "no_samples"
        return LivingLocation(error=err)

    zone_counts: Counter[str] = Counter()
    station_counts: Counter[str] = Counter()
    project_name = ""
    project_url = ""
    for s in ok_samples:
        if s.zone:
            zone_counts[s.zone] += 1
        for st in s.stations:
            station_counts[st] += 1
        if s.project_name and not project_name:
            project_name = s.project_name
            project_url = s.project_url

    zone = zone_counts.most_common(1)[0][0] if zone_counts else ""
    # Keep stations that appear on ≥1 sample; order by frequency, max 3
    stations = [s for s, _ in station_counts.most_common(3)]
    return LivingLocation(
        zone=zone,
        stations=stations,
        project_name=project_name,
        project_url=project_url,
        ok=bool(zone or stations),
        source_url=ok_samples[0].source_url,
    )
