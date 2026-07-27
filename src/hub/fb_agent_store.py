"""Facebook comment-agent status + credentials (multi-agent, Hub-managed)."""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORE_PATH = BASE_DIR / "data" / "fb_agent.json"
_LOCK = threading.Lock()

# Agent considered offline if no heartbeat within this window
ONLINE_WINDOW_SEC = 90

DEFAULT_AGENT_ID = "owner"
DEFAULT_AGENT_DEFS: tuple[dict[str, str], ...] = (
    {"id": "owner", "label": "เจ้าของ (Mac)"},
    {"id": "admin", "label": "แอดมิน (Windows)"},
)

_AGENT_FIELDS = (
    "id",
    "label",
    "email",
    "password",
    "agent_token",
    "login_requested",
    "work_paused",
    "fb_logged_in",
    "fb_checked_at",
    "agent_status",
    "agent_message",
    "agent_last_seen",
    "agent_hostname",
    "activity_log",
    "last_run",
    "chrome_profiles",
    "chrome_profile_dir",
    "chrome_profile_name",
    "fb_accounts",
)


def _now() -> datetime:
    return datetime.now().astimezone()


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")


def _default_last_run() -> dict[str, Any]:
    return {"at": "", "done": 0, "failed": 0, "message": ""}


def _default_agent(agent_id: str, label: str = "") -> dict[str, Any]:
    aid = (agent_id or "").strip() or DEFAULT_AGENT_ID
    lbl = (label or "").strip()
    if not lbl:
        for d in DEFAULT_AGENT_DEFS:
            if d["id"] == aid:
                lbl = d["label"]
                break
        if not lbl:
            lbl = aid
    return {
        "id": aid,
        "label": lbl,
        "email": "",
        "password": "",
        "agent_token": secrets.token_urlsafe(24),
        "login_requested": False,
        "work_paused": False,
        "fb_logged_in": False,
        "fb_checked_at": "",
        "agent_status": "offline",
        "agent_message": "",
        "agent_last_seen": "",
        "agent_hostname": "",
        "activity_log": [],
        "last_run": _default_last_run(),
        "chrome_profiles": [],
        "chrome_profile_dir": "",
        "chrome_profile_name": "",
        "fb_accounts": [],
    }


def _default_store() -> dict[str, Any]:
    agents = {d["id"]: _default_agent(d["id"], d["label"]) for d in DEFAULT_AGENT_DEFS}
    return {
        "default_agent_id": DEFAULT_AGENT_ID,
        "agents": agents,
    }


def _normalize_agent(raw: dict[str, Any], *, agent_id: str = "", label: str = "") -> dict[str, Any]:
    aid = str(agent_id or raw.get("id") or "").strip() or DEFAULT_AGENT_ID
    base = _default_agent(aid, label or str(raw.get("label") or ""))
    for k in _AGENT_FIELDS:
        if k in ("id", "label"):
            continue
        if k not in raw:
            continue
        base[k] = raw[k]
    base["id"] = aid
    if str(raw.get("label") or "").strip():
        base["label"] = str(raw["label"]).strip()
    if not isinstance(base.get("last_run"), dict):
        base["last_run"] = _default_last_run()
    else:
        lr = _default_last_run()
        lr.update({k: base["last_run"][k] for k in lr if k in base["last_run"]})
        base["last_run"] = lr
    if not isinstance(base.get("activity_log"), list):
        base["activity_log"] = []
    if not isinstance(base.get("chrome_profiles"), list):
        base["chrome_profiles"] = []
    else:
        cleaned = []
        for item in base["chrome_profiles"]:
            if not isinstance(item, dict):
                continue
            d = str(item.get("dir") or "").strip()
            if not d:
                continue
            cleaned.append(
                {
                    "dir": d,
                    "name": str(item.get("name") or d).strip() or d,
                    "email": str(item.get("email") or "").strip(),
                }
            )
        base["chrome_profiles"] = cleaned
    base["chrome_profile_dir"] = str(base.get("chrome_profile_dir") or "").strip()
    base["chrome_profile_name"] = str(base.get("chrome_profile_name") or "").strip()
    base["fb_accounts"] = _normalize_fb_accounts(base.get("fb_accounts"))
    if not str(base.get("agent_token") or "").strip():
        base["agent_token"] = secrets.token_urlsafe(24)
    base["login_requested"] = bool(base.get("login_requested"))
    base["work_paused"] = bool(base.get("work_paused"))
    base["fb_logged_in"] = bool(base.get("fb_logged_in"))
    return base


def _normalize_fb_accounts(raw: Any) -> list[dict[str, Any]]:
    from src.hub import publish_policy as policy

    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("id") or "").strip()
        label = str(item.get("label") or item.get("name") or "").strip()
        switch_name = str(item.get("switch_name") or label).strip()
        if not aid:
            aid = secrets.token_hex(4)
        if not label:
            label = switch_name or aid
        if not switch_name:
            switch_name = label
        try:
            daily_cap = int(item.get("daily_cap") or policy.DEFAULT_DAILY_CAP)
        except (TypeError, ValueError):
            daily_cap = policy.DEFAULT_DAILY_CAP
        daily_cap = max(1, min(daily_cap, policy.DEFAULT_DAILY_CAP_MAX))
        out.append(
            {
                "id": aid,
                "label": label,
                "switch_name": switch_name,
                "daily_cap": daily_cap,
                "min_delay_sec": int(item.get("min_delay_sec") or policy.MIN_DELAY_SEC),
                "max_delay_sec": int(item.get("max_delay_sec") or policy.MAX_DELAY_SEC),
                "work_start_hour": int(item.get("work_start_hour") or policy.WORK_START_HOUR),
                "work_end_hour": int(item.get("work_end_hour") or policy.WORK_END_HOUR),
                "paused": bool(item.get("paused")),
                "paused_until": str(item.get("paused_until") or "").strip(),
                "posts_today": int(item.get("posts_today") or 0),
                "last_post_at": str(item.get("last_post_at") or "").strip(),
            }
        )
    return out[:8]


def _is_legacy_flat(data: dict[str, Any]) -> bool:
    if isinstance(data.get("agents"), dict):
        return False
    # Old single-agent flat keys
    return any(k in data for k in ("email", "password", "agent_token", "login_requested", "fb_logged_in"))


def _migrate_legacy(data: dict[str, Any]) -> dict[str, Any]:
    store = _default_store()
    owner = _normalize_agent(data, agent_id=DEFAULT_AGENT_ID, label="เจ้าของ (Mac)")
    store["agents"][DEFAULT_AGENT_ID] = owner
    return store


def _ensure_defaults(store: dict[str, Any]) -> dict[str, Any]:
    agents = store.get("agents")
    if not isinstance(agents, dict):
        agents = {}
    out_agents: dict[str, Any] = {}
    for d in DEFAULT_AGENT_DEFS:
        raw = agents.get(d["id"]) if isinstance(agents.get(d["id"]), dict) else {}
        out_agents[d["id"]] = _normalize_agent(raw, agent_id=d["id"], label=d["label"])
    for aid, raw in agents.items():
        key = str(aid or "").strip()
        if not key or key in out_agents or not isinstance(raw, dict):
            continue
        out_agents[key] = _normalize_agent(raw, agent_id=key)
    default_id = str(store.get("default_agent_id") or DEFAULT_AGENT_ID).strip() or DEFAULT_AGENT_ID
    if default_id not in out_agents:
        default_id = DEFAULT_AGENT_ID
    return {"default_agent_id": default_id, "agents": out_agents}


def _load_raw() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return _default_store()
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_store()
    if not isinstance(data, dict):
        return _default_store()
    if _is_legacy_flat(data):
        return _ensure_defaults(_migrate_legacy(data))
    return _ensure_defaults(data)


def _save_raw(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STORE_PATH)


def _append_activity(row: dict[str, Any], message: str) -> None:
    text = (message or "").strip()
    if not text:
        return
    log = [x for x in (row.get("activity_log") or []) if isinstance(x, dict)]
    if log and str(log[0].get("message") or "") == text:
        log[0]["at"] = _now_iso()
    else:
        log.insert(0, {"at": _now_iso(), "message": text})
    row["activity_log"] = log[:40]


def _parse_ts(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(text.replace("Z", "+0000"), fmt)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=_now().tzinfo)
            return dt
        except ValueError:
            continue
    return None


def _resolve_agent_id(store: dict[str, Any], agent_id: str | None) -> str:
    agents = store.get("agents") if isinstance(store.get("agents"), dict) else {}
    if agent_id is not None and str(agent_id).strip():
        aid = str(agent_id).strip()
        if aid not in agents:
            raise ValueError(f"ไม่พบ agent: {aid}")
        return aid
    default_id = str(store.get("default_agent_id") or DEFAULT_AGENT_ID).strip() or DEFAULT_AGENT_ID
    if default_id in agents:
        return default_id
    if DEFAULT_AGENT_ID in agents:
        return DEFAULT_AGENT_ID
    if agents:
        return next(iter(agents))
    raise ValueError("ไม่พบ agent")


def _get_agent(store: dict[str, Any], agent_id: str | None = None) -> dict[str, Any]:
    aid = _resolve_agent_id(store, agent_id)
    return store["agents"][aid]


def is_agent_online(data: dict[str, Any] | None = None) -> bool:
    """True if the given agent row (or default agent from store) is within the online window."""
    if data is None:
        store = load()
        row = _get_agent(store)
    elif isinstance(data.get("agents"), dict):
        row = _get_agent(data)
    else:
        row = data
    seen = _parse_ts(str(row.get("agent_last_seen") or ""))
    if not seen:
        return False
    return (_now() - seen) <= timedelta(seconds=ONLINE_WINDOW_SEC)


def _public_one(row: dict[str, Any], *, include_token: bool = False) -> dict[str, Any]:
    online = is_agent_online(row)
    status = str(row.get("agent_status") or "offline")
    if not online:
        status = "offline"
    elif bool(row.get("work_paused")) and status not in {"error", "logging_in"}:
        status = "paused"
    out: dict[str, Any] = {
        "id": str(row.get("id") or ""),
        "label": str(row.get("label") or ""),
        "email": str(row.get("email") or ""),
        "has_password": bool(str(row.get("password") or "").strip()),
        "login_requested": bool(row.get("login_requested")),
        "work_paused": bool(row.get("work_paused")),
        "fb_logged_in": bool(row.get("fb_logged_in")),
        "fb_checked_at": str(row.get("fb_checked_at") or ""),
        "agent_online": online,
        "agent_status": status,
        "agent_message": str(row.get("agent_message") or ""),
        "agent_last_seen": str(row.get("agent_last_seen") or ""),
        "agent_hostname": str(row.get("agent_hostname") or ""),
        "last_run": dict(row.get("last_run") or {}),
        "activity_log": [
            {"at": str(x.get("at") or ""), "message": str(x.get("message") or "")}
            for x in (row.get("activity_log") or [])
            if isinstance(x, dict)
        ][:20],
        "chrome_profiles": [
            {
                "dir": str(x.get("dir") or ""),
                "name": str(x.get("name") or ""),
                "email": str(x.get("email") or ""),
            }
            for x in (row.get("chrome_profiles") or [])
            if isinstance(x, dict) and str(x.get("dir") or "").strip()
        ],
        "chrome_profile_dir": str(row.get("chrome_profile_dir") or ""),
        "chrome_profile_name": str(row.get("chrome_profile_name") or ""),
        "fb_accounts": _normalize_fb_accounts(row.get("fb_accounts")),
        "online_window_sec": ONLINE_WINDOW_SEC,
    }
    if include_token:
        out["agent_token"] = str(row.get("agent_token") or "")
    return out


def load() -> dict[str, Any]:
    with _LOCK:
        return _load_raw()


def save(data: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        store = _ensure_defaults(data if isinstance(data, dict) else _default_store())
        _save_raw(store)
        return dict(store)


def ensure_agents() -> dict[str, Any]:
    """Ensure default owner + admin agents exist; persist migrated/normalized store."""
    with _LOCK:
        store = _load_raw()
        _save_raw(store)
        return store


def list_agents(*, include_token: bool = False) -> list[dict[str, Any]]:
    store = load()
    agents = store.get("agents") if isinstance(store.get("agents"), dict) else {}
    order = [d["id"] for d in DEFAULT_AGENT_DEFS]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for aid in order:
        if aid in agents:
            out.append(_public_one(agents[aid], include_token=include_token))
            seen.add(aid)
    for aid, row in agents.items():
        if aid in seen or not isinstance(row, dict):
            continue
        out.append(_public_one(row, include_token=include_token))
    return out


def public_status(*, include_token: bool = False, agent_id: str | None = None) -> dict[str, Any]:
    """Status for Hub UI — never returns raw password.

    If agent_id is None: multi-agent payload with default agent fields flattened at top level
    for backward compatibility with older Hub/UI callers.
    """
    store = load()
    if agent_id is not None and str(agent_id).strip():
        row = _get_agent(store, agent_id)
        out = _public_one(row, include_token=include_token)
        out["ok"] = True
        out["default_agent_id"] = str(store.get("default_agent_id") or DEFAULT_AGENT_ID)
        return out

    default_id = str(store.get("default_agent_id") or DEFAULT_AGENT_ID)
    default_row = _get_agent(store, default_id)
    flat = _public_one(default_row, include_token=include_token)
    return {
        "ok": True,
        "agents": list_agents(include_token=include_token),
        "default_agent_id": default_id,
        **flat,
    }


def set_credentials(
    *,
    email: str,
    password: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    with _LOCK:
        store = _load_raw()
        row = _get_agent(store, agent_id)
        row["email"] = (email or "").strip()
        if password is not None and str(password).strip() != "":
            row["password"] = str(password)
        store["agents"][row["id"]] = row
        _save_raw(store)
        aid = row["id"]
    return public_status(include_token=True, agent_id=aid)


def request_login(agent_id: str | None = None) -> dict[str, Any]:
    """Ask the PC agent to open a visible Facebook window for manual login.

    No longer requires email/password to be set first.
    """
    with _LOCK:
        store = _load_raw()
        row = _get_agent(store, agent_id)
        row["login_requested"] = True
        row["agent_message"] = "รอเครื่อง Agent เปิดหน้าต่าง Facebook…"
        store["agents"][row["id"]] = row
        _save_raw(store)
        aid = row["id"]
    return public_status(include_token=True, agent_id=aid)


def set_work_paused(paused: bool, agent_id: str | None = None) -> dict[str, Any]:
    """Emergency pause / resume for comment work on this agent."""
    with _LOCK:
        store = _load_raw()
        row = _get_agent(store, agent_id)
        row["work_paused"] = bool(paused)
        if paused:
            row["login_requested"] = False
            row["agent_message"] = "⏸ หยุดงานฉุกเฉิน — ไม่คอมเมนต์จนกว่าจะกดทำงานต่อ"
            _append_activity(row, "สั่งหยุดงานฉุกเฉินจาก Hub")
        else:
            row["agent_message"] = "▶ ทำงานต่อแล้ว — รอคิวคอมเมนต์"
            _append_activity(row, "สั่งทำงานต่อจาก Hub")
        store["agents"][row["id"]] = row
        _save_raw(store)
        aid = row["id"]
    return public_status(include_token=True, agent_id=aid)


def is_work_paused(agent_id: str | None = None) -> bool:
    store = load()
    row = _get_agent(store, agent_id)
    return bool(row.get("work_paused"))


def set_chrome_profiles(
    profiles: list[dict[str, Any]],
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Agent uploads discovered Chrome profiles from the PC."""
    cleaned: list[dict[str, str]] = []
    for item in profiles or []:
        if not isinstance(item, dict):
            continue
        d = str(item.get("dir") or "").strip()
        if not d:
            continue
        cleaned.append(
            {
                "dir": d,
                "name": str(item.get("name") or d).strip() or d,
                "email": str(item.get("email") or "").strip(),
            }
        )
    with _LOCK:
        store = _load_raw()
        row = _get_agent(store, agent_id)
        row["chrome_profiles"] = cleaned
        # Keep selection if still present; otherwise clear
        selected = str(row.get("chrome_profile_dir") or "").strip()
        dirs = {p["dir"] for p in cleaned}
        if selected and selected not in dirs:
            row["chrome_profile_dir"] = ""
            row["chrome_profile_name"] = ""
        elif selected:
            for p in cleaned:
                if p["dir"] == selected:
                    row["chrome_profile_name"] = p["name"]
                    break
        store["agents"][row["id"]] = row
        _save_raw(store)
        aid = row["id"]
    return public_status(include_token=False, agent_id=aid)


def set_chrome_profile(
    profile_dir: str,
    *,
    profile_name: str = "",
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Hub admin selects which Chrome profile the Agent should use."""
    d = (profile_dir or "").strip()
    with _LOCK:
        store = _load_raw()
        row = _get_agent(store, agent_id)
        name = (profile_name or "").strip()
        if d:
            for p in row.get("chrome_profiles") or []:
                if isinstance(p, dict) and str(p.get("dir") or "") == d:
                    if not name:
                        name = str(p.get("name") or d)
                    break
            if not name:
                name = d
            row["chrome_profile_dir"] = d
            row["chrome_profile_name"] = name
            row["agent_message"] = f"เลือกโปรไฟล์ Chrome แล้ว: {name}"
            _append_activity(row, f"เลือกโปรไฟล์ Chrome: {name} ({d})")
        else:
            row["chrome_profile_dir"] = ""
            row["chrome_profile_name"] = ""
            row["agent_message"] = "ล้างการเลือกโปรไฟล์ Chrome แล้ว"
            _append_activity(row, "ล้างการเลือกโปรไฟล์ Chrome")
        store["agents"][row["id"]] = row
        _save_raw(store)
        aid = row["id"]
    return public_status(include_token=True, agent_id=aid)


def set_fb_accounts(
    accounts: list[dict[str, Any]],
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Replace FB account slots used for auto switch inside one Chrome profile."""
    cleaned = _normalize_fb_accounts(accounts)
    with _LOCK:
        store = _load_raw()
        row = _get_agent(store, agent_id)
        row["fb_accounts"] = cleaned
        row["agent_message"] = f"บันทึกบัญชีเฟส {len(cleaned)} บัญชีสำหรับสลับอัตโนมัติ"
        _append_activity(row, f"อัปเดต fb_accounts · {len(cleaned)} บัญชี")
        store["agents"][row["id"]] = row
        _save_raw(store)
        aid = row["id"]
    return public_status(include_token=True, agent_id=aid)


def pause_fb_account(
    account_id: str,
    *,
    paused: bool = True,
    hours: int | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    from src.hub import publish_policy as policy

    want = (account_id or "").strip()
    with _LOCK:
        store = _load_raw()
        row = _get_agent(store, agent_id)
        accounts = _normalize_fb_accounts(row.get("fb_accounts"))
        found = False
        for acc in accounts:
            if acc["id"] != want and acc.get("switch_name") != want and acc.get("label") != want:
                continue
            found = True
            acc["paused"] = bool(paused)
            if paused:
                if hours is not None:
                    acc["paused_until"] = policy.restriction_pause_until(hours=int(hours))
                elif not acc.get("paused_until"):
                    acc["paused_until"] = policy.restriction_pause_until()
            else:
                acc["paused_until"] = ""
            break
        if not found:
            raise ValueError("ไม่พบบัญชีเฟส")
        row["fb_accounts"] = accounts
        store["agents"][row["id"]] = row
        _save_raw(store)
        aid = row["id"]
    return public_status(include_token=True, agent_id=aid)


def rotate_agent_token(agent_id: str | None = None) -> dict[str, Any]:
    with _LOCK:
        store = _load_raw()
        row = _get_agent(store, agent_id)
        row["agent_token"] = secrets.token_urlsafe(24)
        store["agents"][row["id"]] = row
        _save_raw(store)
        aid = row["id"]
    return public_status(include_token=True, agent_id=aid)


def resolve_agent_id_by_token(token: str) -> str | None:
    got = (token or "").strip()
    if not got:
        return None
    store = load()
    agents = store.get("agents") if isinstance(store.get("agents"), dict) else {}
    for aid, row in agents.items():
        if not isinstance(row, dict):
            continue
        expected = str(row.get("agent_token") or "").strip()
        if expected and secrets.compare_digest(expected, got):
            return str(aid)
    return None


def verify_agent_token(token: str) -> bool:
    return resolve_agent_id_by_token(token) is not None


def get_credentials_for_agent(agent_id: str | None = None) -> dict[str, str]:
    store = load()
    row = _get_agent(store, agent_id)
    return {
        "email": str(row.get("email") or ""),
        "password": str(row.get("password") or ""),
        "agent_id": str(row.get("id") or ""),
    }


def agent_pull(agent_id: str | None = None) -> dict[str, Any]:
    """Payload for agent poll: credentials + flags (requires token auth at HTTP layer)."""
    store = load()
    # Prefer resolving by agent_id; callers that only know the token should pass agent_id
    # from resolve_agent_id_by_token at the HTTP layer.
    row = _get_agent(store, agent_id)
    return {
        "ok": True,
        "agent_id": str(row.get("id") or ""),
        "email": str(row.get("email") or ""),
        "password": str(row.get("password") or ""),
        "login_requested": bool(row.get("login_requested")),
        "work_paused": bool(row.get("work_paused")),
        "fb_logged_in": bool(row.get("fb_logged_in")),
        "chrome_profile_dir": str(row.get("chrome_profile_dir") or ""),
        "chrome_profile_name": str(row.get("chrome_profile_name") or ""),
        "fb_accounts": _normalize_fb_accounts(row.get("fb_accounts")),
    }


def agent_heartbeat(
    *,
    status: str = "online",
    message: str = "",
    hostname: str = "",
    fb_logged_in: bool | None = None,
    clear_login_request: bool = False,
    last_run: dict[str, Any] | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    with _LOCK:
        store = _load_raw()
        row = _get_agent(store, agent_id)
        row["agent_last_seen"] = _now_iso()
        row["agent_status"] = (status or "online").strip() or "online"
        if message is not None:
            row["agent_message"] = str(message)
            if str(message).strip():
                _append_activity(row, str(message))
        if hostname:
            row["agent_hostname"] = str(hostname).strip()
        if fb_logged_in is not None:
            row["fb_logged_in"] = bool(fb_logged_in)
            row["fb_checked_at"] = _now_iso()
        if clear_login_request:
            row["login_requested"] = False
        if isinstance(last_run, dict):
            prev = dict(row.get("last_run") or {})
            prev.update({k: last_run[k] for k in ("at", "done", "failed", "message") if k in last_run})
            if not prev.get("at"):
                prev["at"] = _now_iso()
            row["last_run"] = prev
            if prev.get("message"):
                _append_activity(row, str(prev.get("message")))
        store["agents"][row["id"]] = row
        _save_raw(store)
        aid = row["id"]
    return public_status(agent_id=aid)
