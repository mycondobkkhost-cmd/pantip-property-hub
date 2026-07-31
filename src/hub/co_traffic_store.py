"""Self-hosted Co-Agent (/co/) traffic events + analytics rollups."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent.parent
TRAFFIC_DIR = BASE_DIR / "data" / "co_traffic"
DAILY_PATH = TRAFFIC_DIR / "daily.json"
_LOCK = threading.Lock()
BANGKOK = ZoneInfo("Asia/Bangkok")
RETENTION_DAYS = 90
MAX_META_KEYS = 12
MAX_STR = 200
ALLOWED_EVENTS = frozenset(
    {
        "page_view",
        "tab_stock",
        "tab_match",
        "catalog_loaded",
        "filter_change",
        "match_submit",
        "match_result",
        "property_open",
        "line_click",
        "api_catalog",
        "api_match",
    }
)


def _now() -> datetime:
    return datetime.now(tz=BANGKOK)


def _today() -> date:
    return _now().date()


def _ip_salt() -> str:
    return (os.environ.get("HUB_SESSION_SECRET") or "local-dev-hub-session-secret").strip()


def _hash_ip(ip: str) -> str:
    raw = (ip or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(f"{_ip_salt()}|{raw}".encode("utf-8")).hexdigest()[:24]


def _clip(v: Any, n: int = MAX_STR) -> str:
    s = str(v or "").strip()
    if len(s) > n:
        return s[:n]
    return s


def _ref_host(referrer: str) -> str:
    ref = (referrer or "").strip()
    if not ref:
        return "(direct)"
    try:
        host = (urlparse(ref).hostname or "").lower()
        return host or "(direct)"
    except Exception:  # noqa: BLE001
        return "(direct)"


def _parse_ua(ua: str) -> tuple[str, str]:
    """Return (ua_family, device)."""
    s = (ua or "").lower()
    device = "desktop"
    if "ipad" in s or "tablet" in s:
        device = "tablet"
    elif "mobi" in s or "iphone" in s or "android" in s:
        device = "mobile"
    if "edg/" in s or "edgios" in s:
        family = "Edge"
    elif "chrome" in s and "chromium" not in s and "edg" not in s:
        family = "Chrome"
    elif "safari" in s and "chrome" not in s:
        family = "Safari"
    elif "firefox" in s:
        family = "Firefox"
    elif "line/" in s:
        family = "LINE"
    elif "facebook" in s or "fbav" in s:
        family = "Facebook"
    else:
        family = "Other"
    return family, device


def _ensure_dir() -> None:
    TRAFFIC_DIR.mkdir(parents=True, exist_ok=True)


def _events_path(d: date) -> Path:
    return TRAFFIC_DIR / f"events-{d.isoformat()}.jsonl"


def _prune_old_files() -> None:
    cutoff = _today() - timedelta(days=RETENTION_DAYS)
    if not TRAFFIC_DIR.is_dir():
        return
    for p in TRAFFIC_DIR.glob("events-*.jsonl"):
        m = re.match(r"events-(\d{4}-\d{2}-\d{2})\.jsonl$", p.name)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if d < cutoff:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def _load_daily() -> dict[str, Any]:
    if not DAILY_PATH.is_file():
        return {"days": {}}
    try:
        data = json.loads(DAILY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("days"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"days": {}}


def _save_daily(data: dict[str, Any]) -> None:
    _ensure_dir()
    tmp = DAILY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(DAILY_PATH)


def _bump_daily(day_key: str, event: str, device: str, ref_host: str, vid: str, sid: str) -> None:
    data = _load_daily()
    days = data.setdefault("days", {})
    row = days.get(day_key) or {
        "pageviews": 0,
        "events": 0,
        "line_clicks": 0,
        "matches": 0,
        "visitors": [],
        "sessions": [],
        "devices": {},
        "referrers": {},
    }
    row["events"] = int(row.get("events") or 0) + 1
    if event == "page_view":
        row["pageviews"] = int(row.get("pageviews") or 0) + 1
    if event == "line_click":
        row["line_clicks"] = int(row.get("line_clicks") or 0) + 1
    if event in {"match_submit", "api_match"}:
        row["matches"] = int(row.get("matches") or 0) + 1

    visitors = list(row.get("visitors") or [])
    sessions = list(row.get("sessions") or [])
    if vid and vid not in visitors:
        visitors.append(vid)
        if len(visitors) > 5000:
            visitors = visitors[-5000:]
    if sid and sid not in sessions:
        sessions.append(sid)
        if len(sessions) > 8000:
            sessions = sessions[-8000:]
    row["visitors"] = visitors
    row["sessions"] = sessions

    devices = dict(row.get("devices") or {})
    if device:
        devices[device] = int(devices.get(device) or 0) + 1
    row["devices"] = devices

    refs = dict(row.get("referrers") or {})
    if ref_host:
        refs[ref_host] = int(refs.get(ref_host) or 0) + 1
        if len(refs) > 200:
            # Keep top hosts
            top = sorted(refs.items(), key=lambda x: -x[1])[:150]
            refs = dict(top)
    row["referrers"] = refs

    days[day_key] = row
    # prune daily keys beyond retention
    cutoff = (_today() - timedelta(days=RETENTION_DAYS)).isoformat()
    for k in list(days.keys()):
        if k < cutoff:
            del days[k]
    _save_daily(data)


def record_event(
    *,
    event: str,
    vid: str = "",
    sid: str = "",
    path: str = "/co/",
    referrer: str = "",
    user_agent: str = "",
    ip: str = "",
    utm: dict[str, str] | None = None,
    meta: dict[str, Any] | None = None,
    screen: str = "",
    lang: str = "",
    tz: str = "",
) -> dict[str, Any]:
    """Append one event. Returns ok payload."""
    ev = _clip(event, 40).lower().replace(" ", "_")
    if ev not in ALLOWED_EVENTS:
        raise ValueError(f"unknown event: {ev}")

    ua_family, device = _parse_ua(user_agent)
    ref_host = _ref_host(referrer)
    now = _now()
    day_key = now.date().isoformat()
    utm_clean: dict[str, str] = {}
    if isinstance(utm, dict):
        for k in ("utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"):
            if utm.get(k):
                utm_clean[k] = _clip(utm.get(k), 80)

    meta_clean: dict[str, Any] = {}
    if isinstance(meta, dict):
        for i, (k, v) in enumerate(meta.items()):
            if i >= MAX_META_KEYS:
                break
            key = _clip(k, 40)
            if isinstance(v, (int, float, bool)):
                meta_clean[key] = v
            else:
                meta_clean[key] = _clip(v, 120)

    row = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": ev,
        "vid": _clip(vid, 64),
        "sid": _clip(sid, 64),
        "path": _clip(path or "/co/", 120),
        "ref_host": ref_host,
        "referrer": _clip(referrer, 240),
        "ua_family": ua_family,
        "device": device,
        "ip_hash": _hash_ip(ip),
        "utm": utm_clean,
        "meta": meta_clean,
        "screen": _clip(screen, 40),
        "lang": _clip(lang, 24),
        "tz": _clip(tz, 40),
    }

    with _LOCK:
        _ensure_dir()
        _prune_old_files()
        path_f = _events_path(now.date())
        with path_f.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        _bump_daily(day_key, ev, device, ref_host, row["vid"], row["sid"])
    return {"ok": True}


def _iter_events(start: date, end: date):
    d = start
    while d <= end:
        p = _events_path(d)
        if p.is_file():
            try:
                with p.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue
            except OSError:
                pass
        d += timedelta(days=1)


def _range_dates(range_key: str) -> tuple[date, date]:
    end = _today()
    key = (range_key or "7d").strip().lower()
    if key in {"today", "1d", "d"}:
        start = end
    elif key in {"30d", "30"}:
        start = end - timedelta(days=29)
    elif key in {"90d", "90"}:
        start = end - timedelta(days=89)
    else:
        start = end - timedelta(days=6)
    return start, end


def analytics_summary(range_key: str = "7d") -> dict[str, Any]:
    start, end = _range_dates(range_key)
    visitors: set[str] = set()
    sessions: set[str] = set()
    pageviews = 0
    line_clicks = 0
    matches = 0
    events_total = 0
    by_day: dict[str, dict[str, int]] = defaultdict(
        lambda: {"pageviews": 0, "visitors": 0, "sessions": 0, "events": 0, "line_clicks": 0, "matches": 0}
    )
    day_visitors: dict[str, set[str]] = defaultdict(set)
    day_sessions: dict[str, set[str]] = defaultdict(set)
    devices = Counter()
    browsers = Counter()
    referrers = Counter()
    hours = Counter()
    event_counts = Counter()
    utm_sources = Counter()
    langs = Counter()

    for row in _iter_events(start, end):
        events_total += 1
        ev = str(row.get("event") or "")
        event_counts[ev] += 1
        vid = str(row.get("vid") or "")
        sid = str(row.get("sid") or "")
        if vid:
            visitors.add(vid)
        if sid:
            sessions.add(sid)
        ts = str(row.get("ts") or "")
        day = ts[:10] if len(ts) >= 10 else ""
        if not day:
            continue
        by_day[day]["events"] += 1
        if vid:
            day_visitors[day].add(vid)
        if sid:
            day_sessions[day].add(sid)
        if ev == "page_view":
            pageviews += 1
            by_day[day]["pageviews"] += 1
        if ev == "line_click":
            line_clicks += 1
            by_day[day]["line_clicks"] += 1
        if ev in {"match_submit", "api_match"}:
            matches += 1
            by_day[day]["matches"] += 1
        devices[str(row.get("device") or "unknown")] += 1
        browsers[str(row.get("ua_family") or "Other")] += 1
        referrers[str(row.get("ref_host") or "(direct)")] += 1
        lang = str(row.get("lang") or "").split("-")[0] or "?"
        langs[lang] += 1
        # hour from ISO-ish ts
        try:
            if "T" in ts:
                hour = int(ts.split("T", 1)[1][:2])
                hours[hour] += 1
        except (ValueError, IndexError):
            pass
        utm = row.get("utm") or {}
        if isinstance(utm, dict) and utm.get("utm_source"):
            utm_sources[str(utm["utm_source"])] += 1

    series = []
    d = start
    while d <= end:
        key = d.isoformat()
        series.append(
            {
                "date": key,
                "pageviews": by_day[key]["pageviews"],
                "events": by_day[key]["events"],
                "line_clicks": by_day[key]["line_clicks"],
                "matches": by_day[key]["matches"],
                "visitors": len(day_visitors.get(key) or ()),
                "sessions": len(day_sessions.get(key) or ()),
            }
        )
        d += timedelta(days=1)

    def top_list(counter: Counter, n: int = 12) -> list[dict[str, Any]]:
        return [{"name": k, "count": int(v)} for k, v in counter.most_common(n)]

    return {
        "ok": True,
        "range": range_key,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "timezone": "Asia/Bangkok",
        "kpi": {
            "visitors": len(visitors),
            "sessions": len(sessions),
            "pageviews": pageviews,
            "events": events_total,
            "line_clicks": line_clicks,
            "matches": matches,
        },
        "series": series,
        "devices": top_list(devices),
        "browsers": top_list(browsers),
        "referrers": top_list(referrers),
        "hours": [{"hour": h, "count": int(hours.get(h, 0))} for h in range(24)],
        "events": top_list(event_counts),
        "utm_sources": top_list(utm_sources),
        "langs": top_list(langs),
        "empty": events_total == 0,
    }
