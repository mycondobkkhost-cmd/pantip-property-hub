"""Facebook comment-agent status + credentials (managed from Hub UI)."""

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


def _now() -> datetime:
    return datetime.now().astimezone()


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")


def _default() -> dict[str, Any]:
    return {
        "email": "",
        "password": "",
        "agent_token": secrets.token_urlsafe(24),
        "login_requested": False,
        "fb_logged_in": False,
        "fb_checked_at": "",
        "agent_status": "offline",
        "agent_message": "",
        "agent_last_seen": "",
        "agent_hostname": "",
        "last_run": {
            "at": "",
            "done": 0,
            "failed": 0,
            "message": "",
        },
    }


def _load_raw() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return _default()
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default()
    if not isinstance(data, dict):
        return _default()
    out = _default()
    out.update({k: v for k, v in data.items() if k in out or k == "last_run"})
    if not isinstance(out.get("last_run"), dict):
        out["last_run"] = _default()["last_run"]
    if not str(out.get("agent_token") or "").strip():
        out["agent_token"] = secrets.token_urlsafe(24)
    return out


def _save_raw(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STORE_PATH)


def load() -> dict[str, Any]:
    with _LOCK:
        return _load_raw()


def save(data: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        _save_raw(data)
        return dict(data)


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


def is_agent_online(data: dict[str, Any] | None = None) -> bool:
    row = data or load()
    seen = _parse_ts(str(row.get("agent_last_seen") or ""))
    if not seen:
        return False
    return (_now() - seen) <= timedelta(seconds=ONLINE_WINDOW_SEC)


def public_status(*, include_token: bool = False) -> dict[str, Any]:
    """Status for Hub UI — never returns raw password."""
    row = load()
    online = is_agent_online(row)
    status = str(row.get("agent_status") or "offline")
    if not online:
        status = "offline"
    out: dict[str, Any] = {
        "ok": True,
        "email": str(row.get("email") or ""),
        "has_password": bool(str(row.get("password") or "").strip()),
        "login_requested": bool(row.get("login_requested")),
        "fb_logged_in": bool(row.get("fb_logged_in")),
        "fb_checked_at": str(row.get("fb_checked_at") or ""),
        "agent_online": online,
        "agent_status": status,
        "agent_message": str(row.get("agent_message") or ""),
        "agent_last_seen": str(row.get("agent_last_seen") or ""),
        "agent_hostname": str(row.get("agent_hostname") or ""),
        "last_run": dict(row.get("last_run") or {}),
        "online_window_sec": ONLINE_WINDOW_SEC,
    }
    if include_token:
        out["agent_token"] = str(row.get("agent_token") or "")
    return out


def set_credentials(*, email: str, password: str | None = None) -> dict[str, Any]:
    with _LOCK:
        row = _load_raw()
        row["email"] = (email or "").strip()
        if password is not None and str(password).strip() != "":
            row["password"] = str(password)
        _save_raw(row)
    return public_status(include_token=True)


def request_login() -> dict[str, Any]:
    with _LOCK:
        row = _load_raw()
        if not str(row.get("email") or "").strip():
            raise ValueError("กรุณาบันทึกอีเมลเฟสก่อน")
        if not str(row.get("password") or "").strip():
            raise ValueError("กรุณาบันทึกรหัสผ่านเฟสก่อน")
        row["login_requested"] = True
        row["agent_message"] = "รอเครื่อง Agent เปิดหน้าต่าง Facebook…"
        _save_raw(row)
    return public_status(include_token=True)


def rotate_agent_token() -> dict[str, Any]:
    with _LOCK:
        row = _load_raw()
        row["agent_token"] = secrets.token_urlsafe(24)
        _save_raw(row)
    return public_status(include_token=True)


def verify_agent_token(token: str) -> bool:
    expected = str(load().get("agent_token") or "").strip()
    got = (token or "").strip()
    return bool(expected) and bool(got) and secrets.compare_digest(expected, got)


def get_credentials_for_agent() -> dict[str, str]:
    row = load()
    return {
        "email": str(row.get("email") or ""),
        "password": str(row.get("password") or ""),
    }


def agent_pull() -> dict[str, Any]:
    """Payload for agent poll: credentials + flags (requires token auth at HTTP layer)."""
    row = load()
    return {
        "ok": True,
        "email": str(row.get("email") or ""),
        "password": str(row.get("password") or ""),
        "login_requested": bool(row.get("login_requested")),
        "fb_logged_in": bool(row.get("fb_logged_in")),
    }


def agent_heartbeat(
    *,
    status: str = "online",
    message: str = "",
    hostname: str = "",
    fb_logged_in: bool | None = None,
    clear_login_request: bool = False,
    last_run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _LOCK:
        row = _load_raw()
        row["agent_last_seen"] = _now_iso()
        row["agent_status"] = (status or "online").strip() or "online"
        if message is not None:
            row["agent_message"] = str(message)
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
        _save_raw(row)
    return public_status()
