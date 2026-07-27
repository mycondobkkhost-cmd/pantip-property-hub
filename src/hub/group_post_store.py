"""Group-comment queue store (property code -> up to 20 post links)."""

from __future__ import annotations

import json
import os
import random
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORE_PATH = BASE_DIR / "data" / "group_post_links.json"
CODE_STORE_PATH = BASE_DIR / "data" / "group_post_codes.json"
_LOCK = threading.RLock()
BANGKOK = ZoneInfo("Asia/Bangkok")

STATUS_PENDING = "pending"
STATUS_COMMENTED = "commented"
STATUS_FAILED = "failed"
STATUS_PAUSED = "paused"
STATUS_DONE = "done"

# Defaults — first comment ASAP; later rebump every few days until end_date
FIRST_DELAY_HOURS = (0, 0)
REBUMP_DAYS = (5, 8)
DEFAULT_MAX_COMMENTS = 999  # legacy field; stop condition is end_date + max_per_day
MAX_LINKS_PER_CODE = 20

FB_HOSTS = ("facebook.com", "fb.com", "fb.watch", "m.facebook.com")


def _now() -> datetime:
    return datetime.now(BANGKOK)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(raw: str | None) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[: len(fmt) + 8], fmt) if "T" in fmt else datetime.strptime(s[:19], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BANGKOK)
            return dt.astimezone(BANGKOK)
        except ValueError:
            continue
    return None


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load() -> dict:
    if not STORE_PATH.exists():
        return {"items": []}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"items": []}
    if isinstance(data, list):
        return {"items": data}
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return {"items": items}
    return {"items": []}


def _save(data: dict) -> None:
    _atomic_write(STORE_PATH, {"items": data.get("items") or []})


def _default_code_settings() -> dict:
    return {
        "min_delay_sec": 480,
        "max_delay_sec": 1200,
        "max_per_run": 3,
        "max_per_day": 10,
        "max_comments_per_link": DEFAULT_MAX_COMMENTS,  # unused in UI; kept for old data
        "first_delay_hour_min": 0,
        "first_delay_hour_max": 0,
        "rebump_day_min": 5,
        "rebump_day_max": 8,
        "total_days": 30,
        "end_date": "",
    }


def _load_codes() -> dict:
    if not CODE_STORE_PATH.exists():
        return {"codes": []}
    try:
        data = json.loads(CODE_STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"codes": []}
    if isinstance(data, dict) and isinstance(data.get("codes"), list):
        return {"codes": data["codes"]}
    if isinstance(data, list):
        return {"codes": data}
    return {"codes": []}


def _save_codes(data: dict) -> None:
    _atomic_write(CODE_STORE_PATH, {"codes": data.get("codes") or []})


def _norm_code(code: str) -> str:
    return str(code or "").strip().upper().replace(" ", "")


def _normalize_code_item(item: dict) -> dict | None:
    code = _norm_code(item.get("code") or item.get("property_code") or "")
    if not code:
        return None
    active = bool(item.get("active", True))
    s = _default_code_settings()
    raw = item.get("settings") if isinstance(item.get("settings"), dict) else {}
    for k, v in raw.items():
        if k not in s:
            continue
        try:
            s[k] = int(v)
        except (TypeError, ValueError):
            continue
    s["min_delay_sec"] = max(120, min(s["min_delay_sec"], 3600))
    s["max_delay_sec"] = max(s["min_delay_sec"], min(s["max_delay_sec"], 10800))
    s["max_per_run"] = max(1, min(s["max_per_run"], 10))
    s["max_per_day"] = max(1, min(s["max_per_day"], 100))
    # Keep legacy field clamped but do not surface in Hub UI
    s["max_comments_per_link"] = max(1, min(int(s.get("max_comments_per_link") or DEFAULT_MAX_COMMENTS), 999))
    s["first_delay_hour_min"] = max(0, min(s["first_delay_hour_min"], 72))
    s["first_delay_hour_max"] = max(s["first_delay_hour_min"], min(s["first_delay_hour_max"], 120))
    s["rebump_day_min"] = max(1, min(s["rebump_day_min"], 30))
    s["rebump_day_max"] = max(s["rebump_day_min"], min(s["rebump_day_max"], 60))
    s["total_days"] = max(1, min(int(s.get("total_days") or 30), 365))
    end_date = str(s.get("end_date") or "").strip()
    if end_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", end_date):
        end_date = ""
    s["end_date"] = end_date
    agent_id = str(item.get("agent_id") or "").strip() or "owner"
    return {
        "id": str(item.get("id") or "").strip() or str(uuid.uuid4()),
        "code": code,
        "active": active,
        "agent_id": agent_id,
        "settings": s,
        "created_at": str(item.get("created_at") or "").strip() or _now_iso(),
        "updated_at": str(item.get("updated_at") or "").strip() or _now_iso(),
    }


def normalize_post_url(raw: str) -> str:
    """Normalize Facebook post permalinks for dedupe."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("www.") or s.startswith("facebook.com") or s.startswith("m.facebook.com") or s.startswith("fb.com"):
        s = "https://" + s
    try:
        parsed = urlparse(s)
    except ValueError:
        return s
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    if host == "fb.com":
        host = "facebook.com"
    if not any(host.endswith(h) for h in FB_HOSTS):
        return s

    # Drop tracking noise; keep story_fbid / id / multi_permalinks
    qs = parse_qs(parsed.query, keep_blank_values=False)
    keep_keys = ("story_fbid", "id", "multi_permalinks", "set", "type", "comment_id")
    cleaned = {k: v[0] for k, v in qs.items() if k in keep_keys and v}
    path = parsed.path or ""
    # Collapse /groups/xxx/permalink/yyy/ style
    path = re.sub(r"/+$", "", path)
    query = urlencode(cleaned) if cleaned else ""
    return urlunparse(("https", "www.facebook.com", path, "", query, ""))


def _is_facebook_url(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return False
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") else host
    return any(host.endswith(h) for h in FB_HOSTS)


def _schedule_first_comment() -> str:
    lo, hi = FIRST_DELAY_HOURS
    hours = random.uniform(float(lo), float(hi))
    return (_now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _schedule_rebump() -> str:
    lo, hi = REBUMP_DAYS
    days = random.uniform(float(lo), float(hi))
    # Prefer daytime Bangkok 09:00–20:00
    base = _now() + timedelta(days=days)
    hour = random.randint(9, 19)
    minute = random.randint(0, 59)
    when = base.replace(hour=hour, minute=minute, second=random.randint(0, 59))
    return when.strftime("%Y-%m-%d %H:%M:%S")


def _schedule_first_comment_with(settings: dict | None = None) -> str:
    s = settings or _default_code_settings()
    lo = int(s.get("first_delay_hour_min") or FIRST_DELAY_HOURS[0])
    hi = int(s.get("first_delay_hour_max") or FIRST_DELAY_HOURS[1])
    hours = random.uniform(float(lo), float(max(lo, hi)))
    return (_now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _schedule_rebump_with(settings: dict | None = None) -> str:
    s = settings or _default_code_settings()
    lo = int(s.get("rebump_day_min") or REBUMP_DAYS[0])
    hi = int(s.get("rebump_day_max") or REBUMP_DAYS[1])
    days = random.uniform(float(lo), float(max(lo, hi)))
    base = _now() + timedelta(days=days)
    hour = random.randint(9, 19)
    minute = random.randint(0, 59)
    when = base.replace(hour=hour, minute=minute, second=random.randint(0, 59))
    return when.strftime("%Y-%m-%d %H:%M:%S")


def _normalize_item(item: dict) -> dict | None:
    post_url = normalize_post_url(item.get("post_url") or "")
    if not post_url or not _is_facebook_url(post_url):
        return None
    status = (item.get("status") or STATUS_PENDING).strip().lower()
    if status not in {
        STATUS_PENDING,
        STATUS_COMMENTED,
        STATUS_FAILED,
        STATUS_PAUSED,
        STATUS_DONE,
    }:
        status = STATUS_PENDING
    try:
        max_comments = int(item.get("max_comments") or DEFAULT_MAX_COMMENTS)
    except (TypeError, ValueError):
        max_comments = DEFAULT_MAX_COMMENTS
    max_comments = max(1, min(max_comments, 10))
    try:
        comment_count = int(item.get("comment_count") or 0)
    except (TypeError, ValueError):
        comment_count = 0
    return {
        "id": str(item.get("id") or "").strip() or str(uuid.uuid4()),
        "property_code": str(item.get("property_code") or item.get("code") or "").strip().upper(),
        "group_url": str(item.get("group_url") or "").strip(),
        "group_name": str(item.get("group_name") or "").strip(),
        "post_url": post_url,
        "status": status,
        "comment_count": max(0, comment_count),
        "max_comments": max_comments,
        "next_comment_at": str(item.get("next_comment_at") or "").strip(),
        "last_commented_at": str(item.get("last_commented_at") or "").strip(),
        "last_comment_text": str(item.get("last_comment_text") or "").strip(),
        "last_comment_kind": str(item.get("last_comment_kind") or "").strip(),
        "last_error": str(item.get("last_error") or "").strip(),
        "last_action": str(item.get("last_action") or "").strip(),
        "last_result_detail": str(item.get("last_result_detail") or "").strip(),
        "join_status": str(item.get("join_status") or "").strip(),
        "join_requested_at": str(item.get("join_requested_at") or "").strip(),
        "history": item.get("history") if isinstance(item.get("history"), list) else [],
        "created_at": str(item.get("created_at") or "").strip() or _now_iso(),
        "updated_at": str(item.get("updated_at") or "").strip() or _now_iso(),
    }


def list_items(
    *,
    status: str | None = None,
    property_code: str | None = None,
    limit: int = 500,
) -> list[dict]:
    with _LOCK:
        items = [_normalize_item(x) for x in _load().get("items") or [] if isinstance(x, dict)]
    items = [x for x in items if x]
    code = (property_code or "").strip().upper()
    if code:
        items = [x for x in items if x["property_code"] == code]
    if status:
        want = status.strip().lower()
        items = [x for x in items if x["status"] == want]
    items.sort(key=lambda x: x.get("next_comment_at") or x.get("created_at") or "", reverse=False)
    return items[: max(1, min(int(limit or 500), 2000))]


def stats() -> dict:
    items = list_items(limit=5000)
    due = len(list_due(limit=5000))
    by_status: dict[str, int] = {}
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1
    return {
        "total": len(items),
        "due": due,
        "by_status": by_status,
    }


def list_due(*, limit: int = 20, now: datetime | None = None, agent_id: str | None = None) -> list[dict]:
    """Items ready to comment (pending/commented/failed with next_comment_at <= now).

    If agent_id is provided, only include links whose property code is assigned to that agent.
    """
    now = now or _now()
    want_agent = str(agent_id).strip() if agent_id is not None else None
    out: list[dict] = []
    code_map = {x["code"]: x for x in list_codes(limit=5000)}
    for it in list_items(limit=5000):
        code_cfg = code_map.get(_norm_code(it.get("property_code") or ""))
        if want_agent is not None:
            code_agent = str((code_cfg or {}).get("agent_id") or "owner")
            if code_agent != want_agent:
                continue
        if code_cfg and not code_cfg.get("active", True):
            continue
        if code_cfg:
            end_date = str(((code_cfg.get("settings") or {}).get("end_date") or "")).strip()
            if end_date and _now().date().isoformat() > end_date:
                continue
        if it["status"] in {STATUS_PAUSED, STATUS_DONE}:
            continue
        # Stop condition is code end_date (checked above), not per-link max
        nxt = _parse_ts(it.get("next_comment_at"))
        # First comment on a link: start ASAP (pending or after a failed first try)
        if int(it.get("comment_count") or 0) == 0 and it["status"] in {
            STATUS_PENDING,
            STATUS_FAILED,
        }:
            out.append(it)
            continue
        if nxt is None:
            # treat missing schedule as due
            out.append(it)
            continue
        if nxt <= now:
            out.append(it)
    out.sort(key=lambda x: x.get("next_comment_at") or "")
    return out[: max(1, min(int(limit or 20), 100))]


def list_upcoming(*, limit: int = 20, now: datetime | None = None) -> list[dict]:
    """Next scheduled comments (due first, then future) for Hub schedule view."""
    now = now or _now()
    out: list[dict] = []
    code_map = {x["code"]: x for x in list_codes(limit=5000)}
    for it in list_items(limit=5000):
        code_cfg = code_map.get(_norm_code(it.get("property_code") or ""))
        if code_cfg and not code_cfg.get("active", True):
            continue
        if code_cfg:
            end_date = str(((code_cfg.get("settings") or {}).get("end_date") or "")).strip()
            if end_date and _now().date().isoformat() > end_date:
                continue
        if it["status"] in {STATUS_PAUSED, STATUS_DONE}:
            continue
        nxt = _parse_ts(it.get("next_comment_at"))
        row = dict(it)
        first_asap = int(it.get("comment_count") or 0) == 0 and it["status"] in {
            STATUS_PENDING,
            STATUS_FAILED,
        }
        if first_asap or nxt is None or nxt <= now:
            row["schedule_label"] = "ถึงคิวแล้ว — รอ Agent คอมเมนต์"
            row["is_due"] = True
        else:
            row["schedule_label"] = f"นัดไว้ {it.get('next_comment_at')}"
            row["is_due"] = False
        out.append(row)
    out.sort(key=lambda x: (0 if x.get("is_due") else 1, x.get("next_comment_at") or ""))
    return out[: max(1, min(int(limit or 20), 50))]


def get_item(item_id: str) -> dict | None:
    iid = (item_id or "").strip()
    for it in list_items(limit=5000):
        if it["id"] == iid:
            return it
    return None


def add_post_link(
    *,
    post_url: str,
    property_code: str = "",
    group_url: str = "",
    group_name: str = "",
    max_comments: int | None = None,
    comment_immediately: bool = True,
) -> dict:
    """Register a group post permalink. Dedupes by normalized post_url."""
    normalized = normalize_post_url(post_url)
    if not normalized or not _is_facebook_url(normalized):
        raise ValueError("ต้องเป็นลิงก์โพสต์ Facebook ที่เปิดได้")

    with _LOCK:
        data = _load()
        items = data.get("items") or []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            existing = _normalize_item(raw)
            if existing and existing["post_url"] == normalized:
                # Refresh metadata if provided
                if property_code:
                    raw["property_code"] = property_code.strip().upper()
                if group_url:
                    raw["group_url"] = group_url.strip()
                if group_name:
                    raw["group_name"] = group_name.strip()
                raw["updated_at"] = _now_iso()
                _save(data)
                return _normalize_item(raw)  # type: ignore[return-value]

        code = _norm_code(property_code)
        code_item = ensure_code(code) if code else None
        settings = code_item.get("settings") if isinstance(code_item, dict) else None
        next_at = _now_iso() if comment_immediately else _schedule_first_comment_with(settings)
        item = {
            "id": str(uuid.uuid4()),
            "property_code": code,
            "group_url": (group_url or "").strip(),
            "group_name": (group_name or "").strip(),
            "post_url": normalized,
            "status": STATUS_PENDING,
            "comment_count": 0,
            "max_comments": int(max_comments or (settings or {}).get("max_comments_per_link") or DEFAULT_MAX_COMMENTS),
            "next_comment_at": next_at,
            "last_commented_at": "",
            "last_comment_text": "",
            "last_comment_kind": "",
            "last_error": "",
            "last_action": "",
            "last_result_detail": "",
            "join_status": "",
            "join_requested_at": "",
            "history": [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        items.append(item)
        data["items"] = items
        _save(data)
        return _normalize_item(item)  # type: ignore[return-value]


def update_item(item_id: str, patch: dict) -> dict:
    iid = (item_id or "").strip()
    if not iid:
        raise ValueError("ต้องระบุ id")
    with _LOCK:
        data = _load()
        for i, raw in enumerate(data.get("items") or []):
            if not isinstance(raw, dict) or str(raw.get("id") or "") != iid:
                continue
            if "post_url" in patch and patch["post_url"]:
                raw["post_url"] = normalize_post_url(str(patch["post_url"]))
            for key in ("property_code", "group_url", "group_name", "status", "next_comment_at"):
                if key in patch and patch[key] is not None:
                    val = str(patch[key]).strip()
                    if key == "property_code":
                        val = val.upper()
                    if key == "status":
                        val = val.lower()
                    raw[key] = val
            if "max_comments" in patch and patch["max_comments"] is not None:
                raw["max_comments"] = max(1, min(int(patch["max_comments"]), 10))
            if "paused" in patch:
                raw["status"] = STATUS_PAUSED if patch["paused"] else STATUS_PENDING
            raw["updated_at"] = _now_iso()
            data["items"][i] = raw
            _save(data)
            out = _normalize_item(raw)
            if not out:
                raise ValueError("ลิงก์โพสต์ไม่ถูกต้อง")
            return out
    raise ValueError("ไม่พบรายการ")


def delete_item(item_id: str) -> bool:
    iid = (item_id or "").strip()
    with _LOCK:
        data = _load()
        before = len(data.get("items") or [])
        data["items"] = [
            x for x in (data.get("items") or []) if not (isinstance(x, dict) and str(x.get("id") or "") == iid)
        ]
        if len(data["items"]) == before:
            return False
        _save(data)
        return True


def mark_comment_success(
    item_id: str,
    *,
    comment_text: str,
    comment_kind: str = "text",
) -> dict:
    with _LOCK:
        data = _load()
        for i, raw in enumerate(data.get("items") or []):
            if not isinstance(raw, dict) or str(raw.get("id") or "") != iid_safe(item_id):
                continue
            count = int(raw.get("comment_count") or 0) + 1
            history = raw.get("history") if isinstance(raw.get("history"), list) else []
            history.append(
                {
                    "ts": _now_iso(),
                    "text": (comment_text or "")[:240],
                    "kind": comment_kind,
                }
            )
            raw["history"] = history[-20:]
            raw["comment_count"] = count
            raw["last_commented_at"] = _now_iso()
            raw["last_comment_text"] = (comment_text or "")[:500]
            raw["last_comment_kind"] = comment_kind
            raw["last_error"] = ""
            raw["last_action"] = "commented"
            raw["last_result_detail"] = "คอมเมนต์สำเร็จ"
            raw["updated_at"] = _now_iso()
            code_cfg = get_code_by_code(raw.get("property_code") or "")
            end_date = str(((code_cfg or {}).get("settings") or {}).get("end_date") or "").strip()
            if end_date and _now().date().isoformat() > end_date:
                raw["status"] = STATUS_DONE
                raw["next_comment_at"] = ""
            else:
                # Keep commenting on this link until end_date; daily cap is max_per_day
                raw["status"] = STATUS_COMMENTED
                raw["next_comment_at"] = _schedule_rebump_with((code_cfg or {}).get("settings"))
            data["items"][i] = raw
            _save(data)
            return _normalize_item(raw)  # type: ignore[return-value]
    raise ValueError("ไม่พบรายการ")


def mark_comment_failed(
    item_id: str,
    error: str,
    *,
    action: str = "",
    detail: str = "",
    join_status: str = "",
) -> dict:
    with _LOCK:
        data = _load()
        for i, raw in enumerate(data.get("items") or []):
            if not isinstance(raw, dict) or str(raw.get("id") or "") != iid_safe(item_id):
                continue
            err_text = (error or "")[:500]
            raw["status"] = STATUS_FAILED
            raw["last_error"] = err_text
            raw["last_action"] = str(action or "").strip()
            raw["last_result_detail"] = str(detail or "").strip()[:500]
            if join_status != "":
                raw["join_status"] = str(join_status).strip()
            history = raw.get("history") if isinstance(raw.get("history"), list) else []
            history.append(
                {
                    "ts": _now_iso(),
                    "kind": "error",
                    "text": err_text,
                    "action": str(action or "").strip(),
                    "detail": str(detail or "").strip()[:500],
                }
            )
            raw["history"] = history[-20:]
            # Retry later same day (2–5 hours)
            raw["next_comment_at"] = (_now() + timedelta(hours=random.uniform(2, 5))).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            raw["updated_at"] = _now_iso()
            data["items"][i] = raw
            _save(data)
            return _normalize_item(raw)  # type: ignore[return-value]
    raise ValueError("ไม่พบรายการ")


def iid_safe(item_id: str) -> str:
    return (item_id or "").strip()


def comments_today_count() -> int:
    """How many successful comments were made today (Bangkok)."""
    today = _now().date().isoformat()
    n = 0
    for it in list_items(limit=5000):
        for h in it.get("history") or []:
            if isinstance(h, dict) and str(h.get("ts") or "").startswith(today):
                n += 1
    return n


def comments_today_count_for_code(code: str) -> int:
    want = _norm_code(code)
    if not want:
        return 0
    today = _now().date().isoformat()
    n = 0
    for it in list_items(property_code=want, limit=5000):
        for h in it.get("history") or []:
            if isinstance(h, dict) and str(h.get("ts") or "").startswith(today):
                n += 1
    return n


def _link_summary(row: dict) -> dict:
    return {
        "id": str(row.get("id") or ""),
        "post_url": str(row.get("post_url") or ""),
        "group_name": str(row.get("group_name") or ""),
        "group_url": str(row.get("group_url") or ""),
        "status": str(row.get("status") or ""),
        "next_comment_at": str(row.get("next_comment_at") or ""),
        "comment_count": int(row.get("comment_count") or 0),
        "max_comments": int(row.get("max_comments") or DEFAULT_MAX_COMMENTS),
        "last_error": str(row.get("last_error") or ""),
        "last_action": str(row.get("last_action") or ""),
        "last_result_detail": str(row.get("last_result_detail") or ""),
        "join_status": str(row.get("join_status") or ""),
    }


def list_codes(*, limit: int = 500) -> list[dict]:
    with _LOCK:
        raw = _load_codes().get("codes") or []
        codes = [_normalize_code_item(x) for x in raw if isinstance(x, dict)]
    codes = [x for x in codes if x]
    links = list_items(limit=5000)
    by_code: dict[str, list[dict]] = {}
    for it in links:
        code = _norm_code(it.get("property_code") or "")
        if not code:
            continue
        by_code.setdefault(code, []).append(it)
    now = _now()
    out: list[dict] = []
    for item in codes:
        code = item["code"]
        rows = by_code.get(code, [])
        due = 0
        upcoming: list[datetime] = []
        for r in rows:
            nxt = _parse_ts(r.get("next_comment_at"))
            first_asap = int(r.get("comment_count") or 0) == 0 and r.get("status") in {
                STATUS_PENDING,
                STATUS_FAILED,
            }
            if r.get("status") in {STATUS_PENDING, STATUS_COMMENTED, STATUS_FAILED} and (
                first_asap or nxt is None or nxt <= now
            ):
                due += 1
            if r.get("status") not in {STATUS_DONE, STATUS_PAUSED}:
                if first_asap:
                    upcoming.append(now)
                elif nxt is not None:
                    upcoming.append(nxt)
        next_comment_at = ""
        next_in_sec: int | None = None
        if upcoming:
            earliest = min(upcoming)
            next_comment_at = earliest.strftime("%Y-%m-%d %H:%M:%S")
            delta = (earliest - now).total_seconds()
            next_in_sec = 0 if delta <= 0 else int(delta)
        out.append(
            {
                **item,
                "agent_id": str(item.get("agent_id") or "owner"),
                "link_count": len(rows),
                "due_count": due,
                "active_links": len([r for r in rows if r.get("status") != STATUS_DONE]),
                "links": [_link_summary(r) for r in rows],
                "next_comment_at": next_comment_at,
                "next_in_sec": next_in_sec,
            }
        )
    out.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return out[: max(1, min(int(limit or 500), 2000))]


def get_code_by_code(code: str) -> dict | None:
    want = _norm_code(code)
    if not want:
        return None
    for item in list_codes(limit=5000):
        if item["code"] == want:
            return item
    return None


def ensure_code(code: str) -> dict:
    want = _norm_code(code)
    if not want:
        raise ValueError("ต้องระบุรหัสทรัพย์")
    found = get_code_by_code(want)
    if found:
        return found
    with _LOCK:
        data = _load_codes()
        created = _now()
        item = {
            "id": str(uuid.uuid4()),
            "code": want,
            "active": True,
            "agent_id": "owner",
            "settings": _default_code_settings(),
            "created_at": created.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": created.strftime("%Y-%m-%d %H:%M:%S"),
        }
        item["settings"]["end_date"] = (created + timedelta(days=int(item["settings"]["total_days"]))).date().isoformat()
        data["codes"] = (data.get("codes") or []) + [item]
        _save_codes(data)
    return get_code_by_code(want) or _normalize_code_item(item)  # type: ignore[return-value]


def add_code(code: str) -> dict:
    return ensure_code(code)


def update_code(code: str, patch: dict) -> dict:
    want = _norm_code(code)
    if not want:
        raise ValueError("ต้องระบุรหัสทรัพย์")
    with _LOCK:
        data = _load_codes()
        rows = data.get("codes") or []
        for i, raw in enumerate(rows):
            norm = _normalize_code_item(raw) if isinstance(raw, dict) else None
            if not norm or norm["code"] != want:
                continue
            if "active" in patch:
                raw["active"] = bool(patch["active"])
            if "agent_id" in patch and patch["agent_id"] is not None:
                raw["agent_id"] = str(patch["agent_id"]).strip() or "owner"
            if "settings" in patch and isinstance(patch["settings"], dict):
                cur = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
                cur.update(patch["settings"])
                # if caller sets total_days but no explicit end_date, roll from today
                if "total_days" in patch["settings"] and "end_date" not in patch["settings"]:
                    try:
                        days = int(patch["settings"]["total_days"])
                    except (TypeError, ValueError):
                        days = 30
                    cur["end_date"] = (_now() + timedelta(days=max(1, min(days, 365)))).date().isoformat()
                raw["settings"] = cur
            raw["updated_at"] = _now_iso()
            rows[i] = raw
            data["codes"] = rows
            _save_codes(data)
            return get_code_by_code(want) or norm
    raise ValueError("ไม่พบรหัสทรัพย์")


def delete_code(code: str) -> bool:
    want = _norm_code(code)
    with _LOCK:
        data = _load_codes()
        before = len(data.get("codes") or [])
        data["codes"] = [
            x
            for x in (data.get("codes") or [])
            if not (isinstance(x, dict) and _norm_code(x.get("code") or "") == want)
        ]
        if len(data["codes"]) == before:
            return False
        _save_codes(data)
        links = _load()
        links["items"] = [
            x
            for x in (links.get("items") or [])
            if not (isinstance(x, dict) and _norm_code(x.get("property_code") or "") == want)
        ]
        _save(links)
        return True


def get_code_detail(code: str) -> dict:
    row = get_code_by_code(code)
    if not row:
        raise ValueError("ไม่พบรหัสทรัพย์")
    links = list_items(property_code=row["code"], limit=MAX_LINKS_PER_CODE + 200)
    return {
        "code": row,
        "links": links,
        "max_links": MAX_LINKS_PER_CODE,
    }


def add_link_for_code(
    code: str,
    *,
    post_url: str,
    group_url: str = "",
    group_name: str = "",
    comment_immediately: bool = True,
) -> dict:
    row = ensure_code(code)
    links = list_items(property_code=row["code"], limit=MAX_LINKS_PER_CODE + 10)
    if len(links) >= MAX_LINKS_PER_CODE:
        raise ValueError(f"1 รหัสเพิ่มได้สูงสุด {MAX_LINKS_PER_CODE} ลิงก์")
    if not group_name:
        group_name = infer_group_name_from_link(post_url)
    return add_post_link(
        post_url=post_url,
        property_code=row["code"],
        group_url=group_url,
        group_name=group_name,
        max_comments=DEFAULT_MAX_COMMENTS,
        comment_immediately=comment_immediately,
    )


def infer_group_name_from_link(post_url: str) -> str:
    """Best-effort group name from URL slug/id."""
    s = normalize_post_url(post_url)
    try:
        p = urlparse(s)
    except ValueError:
        return ""
    parts = [x for x in (p.path or "").split("/") if x]
    # /groups/<slug_or_id>/...
    if len(parts) >= 2 and parts[0].lower() == "groups":
        slug = parts[1]
        slug = slug.replace("-", " ").replace("_", " ").strip()
        if slug:
            return slug[:120]
    return ""
