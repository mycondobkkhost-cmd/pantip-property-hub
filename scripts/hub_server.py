#!/usr/bin/env python3
"""Property Hub local server — Phase 2 scrape API + static preview."""

from __future__ import annotations

import json
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
HUB_DIR = BASE_DIR / "hub"
sys.path.insert(0, str(BASE_DIR))

# Local `.env` must override stale shell exports (wrong Sheet ID / CSV URL).
from src.hub.env_load import load_hub_env  # noqa: E402

load_hub_env()

from src.hub.parser import parse_listing_text, parsed_to_dict  # noqa: E402
from src.hub.codes import next_hub_code  # noqa: E402
from src.hub.group_store import (  # noqa: E402
    create_group,
    list_groups_summary,
    mark_group_used,
    recommend_groups,
    retag_all,
    update_group,
)
from src.hub.caption_variant import (  # noqa: E402
    list_caption_history,
    prepare_group_caption,
)
from src.hub.project_store import (  # noqa: E402
    PREVIEW_JS,
    PREVIEW_META,
    create_project,
    ensure_preview_js,
    load_properties,
    project_location_label,
    project_transit_display,
    project_zone_display,
    save_new_property,
    update_project_standard,
    update_project_transit,
    update_property,
    update_property_links,
)
from src.hub.queue_store import (  # noqa: E402
    add_job,
    add_links,
    delete_item,
    import_from_sheet_csv,
    list_queue,
    queue_stats,
    update_item,
)
from src.hub.customer_store import (  # noqa: E402
    STATUS_LABELS,
    add_case,
    append_codes,
    case_stats,
    delete_case,
    get_case,
    list_cases,
    mark_contacted,
    update_case,
    write_followup_export_csv,
)
from src.hub.focus_store import (  # noqa: E402
    add_focus_codes,
    focus_stats,
    list_focus,
    remove_focus_ref,
    toggle_focus,
)
from src.hub.customer_match import recommend_for_case  # noqa: E402
from src.hub.co_catalog import build_co_catalog, match_co_brief  # noqa: E402
from src.hub.scraper import scrape_url, fetch_preview_image, fetch_image_bytes  # noqa: E402
from src.hub.sheet_sync import (  # noqa: E402
    refresh_main_sheet,
    refresh_wait_post_sheet,
    remote_sheet_source_configured,
)
from src.hub.sheet_write import (  # noqa: E402
    OVERVIEW_EXPORT_CSV,
    push_hub_properties_to_sheet,
    write_overview_export_csv,
)
from src.hub.text_gen import generate_text  # noqa: E402

PORT = 8765
SCRAPER_VERSION = "mobile-ua-proxy-bypass-v4"
THUMB_CACHE_DIR = BASE_DIR / "data" / "thumb_cache"
_PREVIEW_OG_CACHE: dict[str, str] = {}
_PREVIEW_BYTES_CACHE: dict[str, tuple[bytes, str]] = {}
# Render disk is ephemeral — startup sync re-hydrates from Google Sheet after each deploy.
_STARTUP_SHEET_SYNC: dict = {
    "status": "idle",  # idle | skipped | running | ok | error
    "properties_total": 0,
    "message": "",
}
# After Hub add/edit: push web → sheet in background (admins need not click sync).
# Manual「ซิงค์ไปชีท」also uses this queue — never run push inline on Render
# (7k-row rewrite exceeds proxy timeout → HTML 502).
_AUTO_SYNC_TO_SHEET: dict = {
    "status": "idle",  # idle | queued | running | ok | error | skipped
    "pending": False,
    "running": False,
    "worker_started": False,
    "requested_at": 0.0,
    "reason": "",
    "last_at": "",
    "pushed": False,
    "spreadsheet_id": "",
    "written_count": 0,
    "sheet_title": "",
    "hub_sheet_title": "",
    "hub_rows_written": 0,
    "spreadsheet_url": "",
    "push_warning": "",
    "message": "",
    "result": None,
    "generation": 0,
    "completed_generation": 0,
}
_AUTO_SYNC_LOCK = __import__("threading").Lock()
_AUTO_SYNC_DEBOUNCE_SEC = 6.0
# Serialize Google Sheet pull/push so startup refresh and sync don't fight.
_SHEET_IO_LOCK = __import__("threading").Lock()
_CO_CATALOG_CACHE: dict = {"mtime": 0.0, "data": None}
_PREVIEW_CACHE_MAX = 400
_THUMB_FETCH_LOCK = __import__("threading").Semaphore(1)
_THUMB_PENDING: set[str] = set()
_THUMB_QUEUE = __import__("queue").Queue()
_THUMB_FAIL_UNTIL: dict[str, float] = {}


def _auto_sync_to_sheet_enabled() -> bool:
    import os

    flag = (os.environ.get("HUB_AUTO_SYNC_TO_SHEET") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def schedule_auto_sync_to_sheet(
    *,
    reason: str = "",
    debounce_sec: float | None = None,
    force: bool = False,
) -> dict:
    """Queue a debounced background push_hub_properties_to_sheet after Hub writes.

    Full overview rewrite can take ~1–2 min / risk 502 if done inline on Render,
    so we never block the save/update (or manual sync button) response.

    force=True: always queue (manual sync button), even if HUB_AUTO_SYNC_TO_SHEET=0.
    debounce_sec: override default debounce (manual sync uses ~0.2s).
    """
    import threading
    import time

    if not force and not _auto_sync_to_sheet_enabled():
        return {
            "queued": False,
            "status": "skipped",
            "message": "HUB_AUTO_SYNC_TO_SHEET=0",
        }

    debounce = (
        _AUTO_SYNC_DEBOUNCE_SEC if debounce_sec is None else max(0.0, float(debounce_sec))
    )
    with _AUTO_SYNC_LOCK:
        _AUTO_SYNC_TO_SHEET["pending"] = True
        # Keep earliest request clock when already pending so debounce doesn't
        # reset forever under rapid edits — except manual force which bumps now.
        now = time.time()
        if force or not _AUTO_SYNC_TO_SHEET.get("requested_at"):
            _AUTO_SYNC_TO_SHEET["requested_at"] = now - max(
                0.0, _AUTO_SYNC_DEBOUNCE_SEC - debounce
            )
        else:
            # Soft bump: allow coalescing but don't starve forever
            _AUTO_SYNC_TO_SHEET["requested_at"] = min(
                float(_AUTO_SYNC_TO_SHEET["requested_at"]),
                now - max(0.0, _AUTO_SYNC_DEBOUNCE_SEC - debounce),
            )
        _AUTO_SYNC_TO_SHEET["reason"] = (reason or "").strip() or "hub_write"
        _AUTO_SYNC_TO_SHEET["generation"] = int(
            _AUTO_SYNC_TO_SHEET.get("generation") or 0
        ) + 1
        gen = int(_AUTO_SYNC_TO_SHEET["generation"])
        _AUTO_SYNC_TO_SHEET["status"] = (
            "running" if _AUTO_SYNC_TO_SHEET.get("running") else "queued"
        )
        _AUTO_SYNC_TO_SHEET["message"] = (
            f"queued ({_AUTO_SYNC_TO_SHEET['reason']})…"
            if not _AUTO_SYNC_TO_SHEET.get("running")
            else _AUTO_SYNC_TO_SHEET.get("message") or "pushing…"
        )
        start_worker = not _AUTO_SYNC_TO_SHEET.get("worker_started")
        if start_worker:
            _AUTO_SYNC_TO_SHEET["worker_started"] = True

    if start_worker:
        threading.Thread(
            target=_auto_sync_to_sheet_worker_loop,
            daemon=True,
            name="auto-sync-to-sheet",
        ).start()

    return {
        "ok": True,
        "queued": True,
        "status": _AUTO_SYNC_TO_SHEET.get("status") or "queued",
        "reason": _AUTO_SYNC_TO_SHEET.get("reason") or "",
        "message": _AUTO_SYNC_TO_SHEET.get("message") or "",
        "generation": gen,
    }


def _auto_sync_status_payload() -> dict:
    return {
        "enabled": _auto_sync_to_sheet_enabled(),
        "status": _AUTO_SYNC_TO_SHEET.get("status") or "idle",
        "pending": bool(_AUTO_SYNC_TO_SHEET.get("pending")),
        "running": bool(_AUTO_SYNC_TO_SHEET.get("running")),
        "pushed": bool(_AUTO_SYNC_TO_SHEET.get("pushed")),
        "spreadsheet_id": _AUTO_SYNC_TO_SHEET.get("spreadsheet_id") or "",
        "written_count": int(_AUTO_SYNC_TO_SHEET.get("written_count") or 0),
        "sheet_title": _AUTO_SYNC_TO_SHEET.get("sheet_title") or "",
        "hub_sheet_title": _AUTO_SYNC_TO_SHEET.get("hub_sheet_title") or "",
        "hub_rows_written": int(_AUTO_SYNC_TO_SHEET.get("hub_rows_written") or 0),
        "spreadsheet_url": _AUTO_SYNC_TO_SHEET.get("spreadsheet_url") or "",
        "push_warning": _AUTO_SYNC_TO_SHEET.get("push_warning") or "",
        "last_at": _AUTO_SYNC_TO_SHEET.get("last_at") or "",
        "message": _AUTO_SYNC_TO_SHEET.get("message") or "",
        "reason": _AUTO_SYNC_TO_SHEET.get("reason") or "",
        "generation": int(_AUTO_SYNC_TO_SHEET.get("generation") or 0),
        "completed_generation": int(
            _AUTO_SYNC_TO_SHEET.get("completed_generation") or 0
        ),
        "result": _AUTO_SYNC_TO_SHEET.get("result"),
    }


def _auto_sync_to_sheet_worker_loop() -> None:
    import time

    while True:
        time.sleep(0.5)
        with _AUTO_SYNC_LOCK:
            if not _AUTO_SYNC_TO_SHEET.get("pending") or _AUTO_SYNC_TO_SHEET.get("running"):
                continue
            wait = _AUTO_SYNC_DEBOUNCE_SEC - (
                time.time() - float(_AUTO_SYNC_TO_SHEET.get("requested_at") or 0)
            )
            if wait > 0:
                continue
            # Don't fight startup sheet pull (same Sheets API / memory).
            startup = (_STARTUP_SHEET_SYNC.get("status") or "").strip()
            if startup == "running":
                _AUTO_SYNC_TO_SHEET["message"] = "waiting for startup sheet pull…"
                continue
            reason = _AUTO_SYNC_TO_SHEET.get("reason") or "hub_write"
            _AUTO_SYNC_TO_SHEET["pending"] = False
            _AUTO_SYNC_TO_SHEET["running"] = True
            _AUTO_SYNC_TO_SHEET["status"] = "running"
            _AUTO_SYNC_TO_SHEET["message"] = f"pushing ({reason})…"
            _AUTO_SYNC_TO_SHEET["result"] = None

        print(f"[hub] auto sync-to-sheet start ({reason})")
        try:
            with _SHEET_IO_LOCK:
                result = push_hub_properties_to_sheet()
            pushed = bool(result.get("pushed"))
            warn = (result.get("push_warning") or "").strip()
            msg = (
                f"pushed={pushed} rows={result.get('written_count') or 0}"
                + (f" · {warn}" if warn else "")
            )
            with _AUTO_SYNC_LOCK:
                _AUTO_SYNC_TO_SHEET.update(
                    {
                        "status": "ok" if pushed else "error",
                        "pushed": pushed,
                        "spreadsheet_id": result.get("spreadsheet_id") or "",
                        "written_count": int(result.get("written_count") or 0),
                        "sheet_title": result.get("sheet_title") or "",
                        "hub_sheet_title": result.get("hub_sheet_title") or "",
                        "hub_rows_written": int(result.get("hub_rows_written") or 0),
                        "spreadsheet_url": result.get("spreadsheet_url") or "",
                        "push_warning": warn,
                        "last_at": result.get("synced_at")
                        or time.strftime("%d/%m/%Y %H:%M"),
                        "message": msg,
                        "running": False,
                        "result": result,
                        "completed_generation": int(
                            _AUTO_SYNC_TO_SHEET.get("generation") or 0
                        ),
                    }
                )
            print(f"[hub] auto sync-to-sheet done: {msg}")
        except Exception as exc:  # noqa: BLE001
            with _AUTO_SYNC_LOCK:
                _AUTO_SYNC_TO_SHEET.update(
                    {
                        "status": "error",
                        "pushed": False,
                        "message": str(exc),
                        "push_warning": str(exc),
                        "running": False,
                        "result": None,
                        "completed_generation": int(
                            _AUTO_SYNC_TO_SHEET.get("generation") or 0
                        ),
                    }
                )
            print(f"[hub] auto sync-to-sheet error: {exc}")


def _cache_put(cache: dict, key: str, value) -> None:
    cache[key] = value
    while len(cache) > _PREVIEW_CACHE_MAX:
        cache.pop(next(iter(cache)), None)


def _co_catalog_cached() -> dict:
    """Rebuild Co-Agent catalog when properties.json changes."""
    from src.hub.project_store import PROPERTIES_JSON

    path = PROPERTIES_JSON
    try:
        mtime = path.stat().st_mtime if path.exists() else 0.0
    except OSError:
        mtime = 0.0
    cached = _CO_CATALOG_CACHE.get("data")
    if cached is not None and _CO_CATALOG_CACHE.get("mtime") == mtime:
        return cached
    data = build_co_catalog()
    _CO_CATALOG_CACHE["mtime"] = mtime
    _CO_CATALOG_CACHE["data"] = data
    return data


def _thumb_key(url: str) -> str:
    import hashlib

    return hashlib.sha1(url.encode("utf-8")).hexdigest()


def _load_thumb_disk(url: str) -> tuple[bytes, str] | None:
    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _thumb_key(url)
    bin_path = THUMB_CACHE_DIR / f"{key}.bin"
    meta_path = THUMB_CACHE_DIR / f"{key}.meta"
    if not bin_path.is_file() or not meta_path.is_file():
        return None
    try:
        meta = meta_path.read_text(encoding="utf-8").strip()
        ctype = meta.split("\n", 1)[0] or "image/jpeg"
        data = bin_path.read_bytes()
        if data and len(data) >= 500:
            return data, ctype
    except Exception:  # noqa: BLE001
        return None
    return None


def _save_thumb_disk(url: str, data: bytes, ctype: str) -> None:
    THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _thumb_key(url)
    try:
        (THUMB_CACHE_DIR / f"{key}.bin").write_bytes(data)
        (THUMB_CACHE_DIR / f"{key}.meta").write_text(
            f"{ctype or 'image/jpeg'}\n{url}\n", encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass


def _fetch_thumb_blocking(page_url: str) -> tuple[bytes, str]:
    """Hit Facebook — only from background worker (never on request thread)."""
    with _THUMB_FETCH_LOCK:
        disk = _load_thumb_disk(page_url)
        if disk:
            _cache_put(_PREVIEW_BYTES_CACHE, page_url, disk)
            return disk
        image_url = _PREVIEW_OG_CACHE.get(page_url)
        if image_url is None:
            try:
                image_url, _ = fetch_preview_image(page_url)
            except Exception:  # noqa: BLE001
                image_url = ""
            _cache_put(_PREVIEW_OG_CACHE, page_url, image_url or "")
        if not image_url:
            return b"", ""
        try:
            data, ctype = fetch_image_bytes(image_url)
        except Exception:  # noqa: BLE001
            return b"", ""
        if not data or len(data) < 500:
            return b"", ""
        ctype = ctype or "image/jpeg"
        _cache_put(_PREVIEW_BYTES_CACHE, page_url, (data, ctype))
        _save_thumb_disk(page_url, data, ctype)
        return data, ctype


def enqueue_preview_thumb(page_url: str) -> None:
    page_url = (page_url or "").strip()
    if not page_url.startswith("http"):
        return
    if page_url in _PREVIEW_BYTES_CACHE and _PREVIEW_BYTES_CACHE[page_url][0]:
        return
    if _load_thumb_disk(page_url):
        return
    import time

    if _THUMB_FAIL_UNTIL.get(page_url, 0) > time.time():
        return
    if page_url in _THUMB_PENDING:
        return
    _THUMB_PENDING.add(page_url)
    _THUMB_QUEUE.put(page_url)


def resolve_preview_thumb(page_url: str, *, wait: bool = False) -> tuple[bytes, str, str]:
    """Return (bytes, ctype, status) where status is hit|pending|miss.

    HTTP handlers must use wait=False so sheet/API stay responsive while FB fetch
    runs in the background worker.
    """
    page_url = (page_url or "").strip()
    if not page_url.startswith("http"):
        return b"", "", "miss"

    cached = _PREVIEW_BYTES_CACHE.get(page_url)
    if cached and cached[0]:
        return cached[0], cached[1], "hit"

    disk = _load_thumb_disk(page_url)
    if disk:
        _cache_put(_PREVIEW_BYTES_CACHE, page_url, disk)
        return disk[0], disk[1], "hit"

    if wait:
        data, ctype = _fetch_thumb_blocking(page_url)
        return data, ctype, ("hit" if data else "miss")

    import time

    if _THUMB_FAIL_UNTIL.get(page_url, 0) > time.time():
        return b"", "", "miss"

    enqueue_preview_thumb(page_url)
    return b"", "", "pending"


def _thumb_worker_loop() -> None:
    import time

    while True:
        page_url = _THUMB_QUEUE.get()
        try:
            data, _ctype = _fetch_thumb_blocking(page_url)
            if not data:
                _THUMB_FAIL_UNTIL[page_url] = time.time() + 120
        except Exception as exc:  # noqa: BLE001
            print(f"[hub] thumb worker error: {exc}")
            _THUMB_FAIL_UNTIL[page_url] = time.time() + 120
        finally:
            _THUMB_PENDING.discard(page_url)
            _THUMB_QUEUE.task_done()


def _hub_session_secret() -> str:
    import os

    return (os.environ.get("HUB_SESSION_SECRET") or "local-dev-hub-session-secret").strip()


def _load_hub_users() -> dict:
    """Login users from HUB_USERS_JSON only (never embed passwords in HTML).

    Local fallback is intentional weak demo accounts — production on Render
    must set HUB_USERS_JSON (and ideally HUB_SESSION_SECRET).
    """
    import os

    raw = (os.environ.get("HUB_USERS_JSON") or "").strip()
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print("[hub] WARN: HUB_USERS_JSON invalid JSON — login users empty")
            return {}
        if not isinstance(data, dict):
            print("[hub] WARN: HUB_USERS_JSON must be a JSON object — login users empty")
            return {}
        users: dict = {}
        for key, val in data.items():
            username = str(key or "").strip().lower()
            if not username or not isinstance(val, dict):
                continue
            password = str(val.get("password") or "")
            name = str(val.get("name") or username)
            if not password:
                continue
            users[username] = {"password": password, "name": name}
        return users

    if (os.environ.get("RENDER") or "").strip():
        print("[hub] WARN: HUB_USERS_JSON not set on Render — login will fail until configured")
        return {}

    # Local-only demo accounts (not used in production HTML / view-source)
    return {
        "angkarn1996": {"password": "localdev", "name": "เจ้าของ"},
        "ptp2": {"password": "localdev2", "name": "แอดมิน 1"},
        "ptp3": {"password": "localdev3", "name": "แอดมิน 2"},
        "ptp4": {"password": "localdev4", "name": "ทีม 4"},
        "ptp5": {"password": "localdev5", "name": "ทีม 5"},
    }


def _b64url_encode(raw: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    import base64

    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode((text + pad).encode("ascii"))


def _make_session_token(username: str, display_name: str) -> str:
    import hashlib
    import hmac
    import time

    payload = json.dumps(
        {
            "u": username,
            "n": display_name,
            "exp": int(time.time()) + 60 * 60 * 24 * 14,  # 14 days
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    body = _b64url_encode(payload.encode("utf-8"))
    sig = hmac.new(
        _hub_session_secret().encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{body}.{sig}"


def _parse_session_token(token: str) -> dict | None:
    import hashlib
    import hmac
    import time

    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expect = hmac.new(
        _hub_session_secret().encode("utf-8"),
        body.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:32]
    if not hmac.compare_digest(sig, expect):
        return None
    try:
        data = json.loads(_b64url_decode(body).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None
    if int(data.get("exp") or 0) < int(time.time()):
        return None
    username = str(data.get("u") or "").strip().lower()
    if not username:
        return None
    return {"username": username, "name": str(data.get("n") or username)}


def _cookie_value(headers: dict | None, name: str) -> str:
    raw = ""
    if headers:
        raw = headers.get("Cookie") or headers.get("cookie") or ""
    for part in raw.split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            return part[len(name) + 1 :].strip()
    return ""


def _preview_data_meta() -> dict:
    """Lightweight fingerprint of the embedded catalog (for cache-bust + freshness)."""
    if PREVIEW_META.is_file():
        try:
            data = json.loads(PREVIEW_META.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("data_version"):
                return {
                    "ok": True,
                    "data_version": str(data.get("data_version") or ""),
                    "generated_at": str(data.get("generated_at") or ""),
                    "properties_total": int(data.get("properties_total") or 0),
                    "projects": int(data.get("projects") or 0),
                }
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    version = ""
    generated_at = ""
    if PREVIEW_JS.is_file():
        try:
            st = PREVIEW_JS.stat()
            version = f"mtime-{int(st.st_mtime)}-{st.st_size}"
            from datetime import datetime, timezone

            generated_at = (
                datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                .astimezone()
                .isoformat(timespec="seconds")
            )
        except OSError:
            version = "unknown"
    return {
        "ok": True,
        "data_version": version,
        "generated_at": generated_at,
        "properties_total": 0,
        "projects": 0,
    }


def _no_store_headers(handler: "HubHandler") -> None:
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Expires", "0")
    handler.send_header("Surrogate-Control", "no-store")


def next_rxt_code(prefix: str = "RXT") -> str:
    p = (prefix or "RXT").strip().upper() or "RXT"
    if p not in {"RXT", "COA", "PTP"}:
        p = "RXT"
    from src.hub.project_store import load_properties_cached

    return next_hub_code(
        load_properties_cached(),
        prefix=p,
        main_csv=BASE_DIR / "data" / "main_sheet.csv",
        hub_csv=BASE_DIR / "data" / "hub_sheet_export.csv",
    )


class HubHandler(BaseHTTPRequestHandler):
    SESSION_COOKIE = "ptp_hub_session"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[hub] {self.address_string()} {fmt % args}")

    def _cors(self) -> None:
        origin = (self.headers.get("Origin") or "").strip()
        # Credentials + wildcard is invalid; echo known local origins for file:// / tunnel use.
        if origin in {"http://127.0.0.1:8765", "http://localhost:8765"} or origin.startswith("http://127.0.0.1:"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")

    def _json(self, status: int, payload: dict, *, set_cookie: str | None = None, clear_cookie: bool = False) -> None:
        import os

        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        _no_store_headers(self)
        secure = "; Secure" if (os.environ.get("RENDER") or "").strip() else ""
        if set_cookie:
            self.send_header(
                "Set-Cookie",
                f"{self.SESSION_COOKIE}={set_cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age={60 * 60 * 24 * 14}{secure}",
            )
        if clear_cookie:
            self.send_header(
                "Set-Cookie",
                f"{self.SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0{secure}",
            )
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(
        self,
        status: int,
        data: bytes,
        *,
        content_type: str,
        filename: str | None = None,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        if filename:
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _session_user(self) -> dict | None:
        token = _cookie_value(self.headers, self.SESSION_COOKIE)  # type: ignore[arg-type]
        return _parse_session_token(token)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/auth/me":
            user = self._session_user()
            if not user:
                self._json(401, {"ok": False, "logged_in": False})
                return
            self._json(200, {"ok": True, "logged_in": True, "username": user["username"], "name": user["name"]})
            return
        if path == "/api/health":
            from urllib.parse import parse_qs

            qs = parse_qs(urlparse(self.path).query or "")
            prefix = ((qs.get("prefix") or ["RXT"])[0] or "RXT").strip().upper()
            stats = queue_stats()
            meta = _preview_data_meta()
            self._json(
                200,
                {
                    "ok": True,
                    "phase": 2,
                    "scraper": SCRAPER_VERSION,
                    "next_code": next_rxt_code(prefix),
                    "queue_pending": stats["pending"] + stats["working"],
                    "data_version": meta.get("data_version") or "",
                    "properties_total": meta.get("properties_total") or 0,
                    "generated_at": meta.get("generated_at") or "",
                    "startup_sheet_sync": dict(_STARTUP_SHEET_SYNC),
                    "auto_sync_to_sheet": _auto_sync_status_payload(),
                },
            )
            return
        if path == "/api/properties/sync-status":
            self._json(
                200,
                {
                    "ok": True,
                    "auto_sync_to_sheet": _auto_sync_status_payload(),
                    "startup_sheet_sync": dict(_STARTUP_SHEET_SYNC),
                },
            )
            return
        if path == "/api/data-meta":
            self._json(200, _preview_data_meta())
            return
        if path in {
            "/api/properties/overview-export.csv",
            "/api/properties/hub-overview-export.csv",
        }:
            try:
                # Prefer last export on disk (sync-to-sheet already writes it).
                # Regenerating 2k–7k rows on free tier during startup can time out.
                data = b""
                if OVERVIEW_EXPORT_CSV.exists() and OVERVIEW_EXPORT_CSV.stat().st_size > 32:
                    data = OVERVIEW_EXPORT_CSV.read_bytes()
                else:
                    from src.hub.sheet_write import (
                        active_properties_for_overview,
                        write_overview_export_csv as _write_ov,
                    )

                    props = active_properties_for_overview()
                    if props:
                        data = _write_ov(props).read_bytes()
                if len(data) < 32:
                    self._json(
                        503,
                        {
                            "ok": False,
                            "error": (
                                "ยังไม่มีไฟล์ export — กด「ซิงค์ไปชีท Hub」ก่อนหนึ่งครั้ง "
                                "(แม้ซิงค์ไม่ขึ้นชีท ก็จะสร้าง CSV) แล้วกดดาวน์โหลดอีกครั้ง "
                                "หรือรอเซิร์ฟดึงชีทให้จบแล้วลองใหม่"
                            ),
                        },
                    )
                    return
                self._send_bytes(
                    200,
                    data,
                    content_type="text/csv; charset=utf-8",
                    filename=OVERVIEW_EXPORT_CSV.name,
                )
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/api/queue":
            include_done = "done=1" in (urlparse(self.path).query or "")
            items = list_queue(include_done=include_done)
            self._json(200, {"items": items, "stats": queue_stats()})
            return
        if path == "/api/customers":
            include_closed = "closed=1" in (urlparse(self.path).query or "")
            items = list_cases(include_closed=include_closed)
            self._json(
                200,
                {
                    "items": items,
                    "stats": case_stats(),
                    "status_labels": STATUS_LABELS,
                },
            )
            return
        if path == "/api/focus":
            items = list_focus()
            self._json(
                200,
                {
                    "items": items,
                    "ids": [x["id"] for x in items],
                    "stats": focus_stats(),
                },
            )
            return
        if path == "/api/preview-image":
            from urllib.parse import parse_qs

            qs = parse_qs(urlparse(self.path).query or "")
            url = ((qs.get("url") or [""])[0] or "").strip()
            if not url:
                self._json(400, {"ok": False, "error": "missing url", "image_url": ""})
                return
            try:
                if url in _PREVIEW_OG_CACHE:
                    image_url = _PREVIEW_OG_CACHE[url]
                    warnings: list[str] = []
                else:
                    image_url, warnings = fetch_preview_image(url)
                    _cache_put(_PREVIEW_OG_CACHE, url, image_url or "")
                self._json(
                    200,
                    {
                        "ok": bool(image_url),
                        "image_url": image_url,
                        "warnings": warnings,
                        "source_url": url,
                        "thumb_url": (
                            f"/api/preview-thumb?url={__import__('urllib.parse').quote(url, safe='')}"
                            if image_url
                            else ""
                        ),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc), "image_url": ""})
            return
        if path == "/api/preview-thumb":
            from urllib.parse import parse_qs

            qs = parse_qs(urlparse(self.path).query or "")
            url = ((qs.get("url") or [""])[0] or "").strip()
            if not url.startswith("http"):
                self.send_error(400)
                return
            try:
                data, ctype, status = resolve_preview_thumb(url, wait=False)
                if data:
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", ctype or "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.send_header("X-Thumb-Status", "hit")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                # pending = queued for background FB fetch; miss = failed / no image
                code = 202 if status == "pending" else 404
                body = b'{"ok":false,"status":"' + status.encode() + b'"}'
                self.send_response(code)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Thumb-Status", status)
                self.end_headers()
                self.wfile.write(body)
            except Exception:  # noqa: BLE001
                try:
                    self.send_error(502)
                except Exception:  # noqa: BLE001
                    pass
            return
        if path == "/api/groups":
            data = list_groups_summary()
            self._json(200, data)
            return
        if path == "/api/co/catalog":
            try:
                self._json(200, _co_catalog_cached())
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return
        if path in {"/co", "/co/"}:
            path = "/co/index.html"
        if path == "/":
            path = "/preview.html"
        file_path = (HUB_DIR / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(HUB_DIR.resolve())):
            self.send_error(403)
            return
        if not file_path.is_file():
            # Last-chance: rebuild catalog JS from properties.json if deploy/sync
            # dropped preview-data.js (avoids empty Hub 「ไม่พบ preview-data.js」).
            if file_path.name == "preview-data.js":
                try:
                    fixed = ensure_preview_js()
                    if fixed.get("ok") and file_path.is_file():
                        print(
                            f"[hub] served rebuilt preview-data.js "
                            f"({fixed.get('reason')}, "
                            f"{fixed.get('properties_total') or 0} props)"
                        )
                    else:
                        self.send_error(404)
                        return
                except Exception as exc:  # noqa: BLE001
                    print(f"[hub] ensure_preview_js on 404 failed: {exc}")
                    self.send_error(404)
                    return
            else:
                self.send_error(404)
                return
        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if file_path.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        # Cache-bust embedded catalog so Safari/mobile cannot keep a stale preview-data.js
        if file_path.name == "preview.html":
            content = file_path.read_bytes()
            meta = _preview_data_meta()
            ver = meta.get("data_version") or str(int(__import__("time").time()))
            text = content.decode("utf-8", errors="replace")
            text = text.replace(
                'src="preview-data.js"',
                f'src="preview-data.js?v={ver}"',
                1,
            )
            content = text.encode("utf-8")
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(content)))
            _no_store_headers(self)
            self.end_headers()
            self.wfile.write(content)
            return

        # Stream large catalogs (preview-data.js ~10MB) — avoid read_bytes OOM/502
        # on Render free tier when several requests overlap.
        try:
            size = file_path.stat().st_size
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        if file_path.suffix in {".html", ".js", ".css", ".json"} or file_path.name.endswith(
            ".meta.json"
        ):
            _no_store_headers(self)
        self.end_headers()
        with file_path.open("rb") as fh:
            while True:
                chunk = fh.read(256 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_json()
        except json.JSONDecodeError:
            self._json(400, {"error": "JSON ไม่ถูกต้อง"})
            return

        if path == "/api/auth/login":
            username = str(body.get("username") or "").strip().lower()
            password = str(body.get("password") or "")
            users = _load_hub_users()
            user = users.get(username)
            if not user or user.get("password") != password:
                self._json(401, {"ok": False, "error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"})
                return
            token = _make_session_token(username, user.get("name") or username)
            self._json(
                200,
                {
                    "ok": True,
                    "username": username,
                    "name": user.get("name") or username,
                },
                set_cookie=token,
            )
            return

        if path == "/api/auth/logout":
            self._json(200, {"ok": True}, clear_cookie=True)
            return

        if path == "/api/scrape":
            url = (body.get("url") or "").strip()
            if not url:
                self._json(400, {"error": "กรุณาใส่ URL"})
                return
            try:
                pasted = (body.get("text") or body.get("pasted_text") or "").strip()
                data = scrape_url(url, pasted_text=pasted)
                data["code"] = next_rxt_code()
                self._json(200, data)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/parse":
            text = body.get("text") or ""
            parsed = parse_listing_text(text)
            data = parsed_to_dict(parsed)
            data["code"] = next_rxt_code()
            data["source_url"] = body.get("source_url") or ""
            self._json(200, data)
            return

        if path == "/api/generate":
            data = body.get("property") or body
            code = data.get("code") or next_rxt_code()
            data["code"] = code
            self._json(
                200,
                {
                    "code": code,
                    "text_th": generate_text(data, "th"),
                    "text_en": generate_text(data, "en"),
                },
            )
            return

        if path == "/api/groups/recommend":
            try:
                prop = body.get("property") or body
                limit = body.get("limit")
                if limit is None:
                    limit = body.get("per_category") or 30
                result = recommend_groups(
                    prop,
                    limit=int(limit),
                    include_owner_only=bool(body.get("include_owner_only")),
                )
                self._json(200, result)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/groups/mark-used":
            try:
                mark_group_used(
                    (body.get("url") or "").strip(),
                    property_code=(body.get("code") or "").strip(),
                )
                self._json(200, {"ok": True})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/groups/prepare-caption":
            try:
                result = prepare_group_caption(
                    property_code=(body.get("code") or body.get("property_code") or "").strip(),
                    group_url=(body.get("group_url") or body.get("url") or "").strip(),
                    group_name=(body.get("group_name") or "").strip(),
                    page_post_text=(body.get("page_post_text") or "").strip(),
                    page_url=(body.get("page_url") or body.get("post_pages_url") or "").strip(),
                    post_url=(body.get("post_url") or "").strip(),
                    base_text=(body.get("base_text") or body.get("text_th") or "").strip(),
                    force_new=bool(body.get("force_new")),
                    allow_scrape=body.get("allow_scrape", True) is not False,
                )
                status = 200 if result.get("ok") else 400
                self._json(status, result)
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/groups/caption-history":
            try:
                code = (body.get("code") or body.get("property_code") or "").strip()
                self._json(200, list_caption_history(code))
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/groups/retag":
            try:
                self._json(200, {"ok": True, **retag_all()})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/groups/create":
            try:
                group = create_group(body.get("group") or body)
                self._json(200, {"ok": True, "group": group})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/groups/update":
            try:
                url = (body.get("original_url") or body.get("url") or "").strip()
                payload = body.get("group") or body
                group = update_group(url, payload)
                self._json(200, {"ok": True, "group": group})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/properties/save":
            try:
                prop = save_new_property(body.get("property") or body)
                code = (prop.get("code") or "").strip()
                sheet_sync = schedule_auto_sync_to_sheet(
                    reason=f"save {code}" if code else "save"
                )
                self._json(
                    200,
                    {
                        "ok": True,
                        "property": prop,
                        "next_code": next_rxt_code(prop.get("code_prefix") or "RXT"),
                        "sheet_sync": sheet_sync,
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/properties/update":
            try:
                pid = (body.get("id") or body.get("code") or "").strip()
                prop_body = body.get("property") or body
                if not pid:
                    pid = (prop_body.get("id") or prop_body.get("code") or "").strip()
                prop = update_property(pid, prop_body)
                code = (prop.get("code") or pid or "").strip()
                sheet_sync = schedule_auto_sync_to_sheet(
                    reason=f"update {code}" if code else "update"
                )
                self._json(
                    200,
                    {"ok": True, "property": prop, "sheet_sync": sheet_sync},
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/properties/update-links":
            try:
                pid = (body.get("id") or body.get("code") or "").strip()
                prop = update_property_links(pid, body)
                code = (prop.get("code") or pid or "").strip()
                sheet_sync = schedule_auto_sync_to_sheet(
                    reason=f"update-links {code}" if code else "update-links"
                )
                self._json(
                    200,
                    {"ok": True, "property": prop, "sheet_sync": sheet_sync},
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/projects/create":
            try:
                name = (body.get("canonical_name") or body.get("name") or "").strip()
                transit = body.get("transit_tags") or body.get("transit") or ""
                zone = body.get("zone_tags") if "zone_tags" in body else body.get("zone")
                aliases = body.get("aliases")
                # Only pass zone_raw when caller explicitly sent zone fields (projects form).
                kwargs: dict = {}
                if "zone_tags" in body or "zone" in body:
                    kwargs["zone_raw"] = zone if zone is not None else ""
                if aliases is not None:
                    kwargs["aliases"] = aliases
                project = create_project(name, transit, **kwargs)
                self._json(
                    200,
                    {
                        "ok": True,
                        "project": project,
                        "transit_display": ", ".join(project_transit_display(project)),
                        "zone_display": ", ".join(project_zone_display(project)),
                        "location_display": project_location_label(project),
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/projects/transit":
            try:
                project_id = (body.get("project_id") or "").strip()
                transit = body.get("transit_tags") or body.get("transit") or ""
                project, listings_updated = update_project_transit(project_id, transit)
                tags = project_transit_display(project)
                zones = project_zone_display(project)
                self._json(
                    200,
                    {
                        "ok": True,
                        "project": project,
                        "listings_updated": listings_updated,
                        "transit_display": ", ".join(tags),
                        "zone_display": ", ".join(zones),
                        "location_display": project_location_label(project),
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/projects/update":
            try:
                project_id = (body.get("project_id") or "").strip()
                project, listings_updated = update_project_standard(
                    project_id,
                    transit_raw=body.get("transit_tags") or body.get("transit"),
                    zone_raw=body.get("zone_tags") or body.get("zone") or "",
                    canonical_name=body.get("canonical_name"),
                    aliases=body.get("aliases"),
                )
                tags = project_transit_display(project)
                zones = project_zone_display(project)
                self._json(
                    200,
                    {
                        "ok": True,
                        "project": project,
                        "listings_updated": listings_updated,
                        "transit_display": ", ".join(tags),
                        "zone_display": ", ".join(zones),
                        "location_display": project_location_label(project),
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/queue/add":
            try:
                source = (body.get("source_url") or "").strip()
                owner = (
                    body.get("owner_contact")
                    or body.get("source_url_2")
                    or body.get("post_url")
                    or ""
                ).strip()
                note = body.get("note") or ""
                raw = body.get("text") or body.get("urls") or ""
                if source or owner or raw:
                    item = add_job(
                        source_url=source,
                        owner_contact=owner,
                        note=note,
                        raw=raw,
                    )
                    created = [item]
                else:
                    self._json(400, {"error": "ใส่ลิงก์ต้นทางก่อน"})
                    return
                self._json(200, {"ok": True, "created": created, "stats": queue_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/queue/update":
            try:
                item = update_item(
                    (body.get("id") or "").strip(),
                    status=body.get("status"),
                    note=body.get("note"),
                    source_url=body.get("source_url"),
                    owner_contact=body.get("owner_contact"),
                    source_url_2=body.get("source_url_2"),
                    post_url=body.get("post_url"),
                )
                self._json(200, {"ok": True, "item": item, "stats": queue_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/queue/delete":
            try:
                delete_item((body.get("id") or "").strip())
                self._json(200, {"ok": True, "stats": queue_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/queue/import-sheet":
            try:
                sheet_meta = refresh_wait_post_sheet(
                    csv_url=(body.get("csv_url") or "").strip()
                )
                replace = bool(body.get("replace"))
                result = import_from_sheet_csv(replace=replace)
                self._json(
                    200,
                    {
                        "ok": True,
                        **result,
                        "sheet": sheet_meta,
                        "stats": queue_stats(),
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/focus/add":
            try:
                raw = body.get("code") or body.get("codes") or body.get("text") or ""
                result = add_focus_codes(raw, load_properties())
                self._json(200, {"ok": True, **result})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/focus/remove":
            try:
                ref = (
                    body.get("id")
                    or body.get("property_id")
                    or body.get("code")
                    or ""
                ).strip()
                result = remove_focus_ref(ref)
                self._json(200, {"ok": True, **result})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/focus/toggle":
            # Legacy pin toggle — prefer /api/focus/add and /api/focus/remove
            try:
                result = toggle_focus(
                    (body.get("id") or body.get("property_id") or "").strip(),
                    code=(body.get("code") or "").strip(),
                )
                self._json(200, {"ok": True, **result})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/customers/add":
            try:
                item = add_case(**{k: v for k, v in body.items() if k != "id"})
                self._json(200, {"ok": True, "item": item, "stats": case_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/customers/update":
            try:
                cid = (body.get("id") or "").strip()
                fields = {k: v for k, v in body.items() if k != "id"}
                item = update_case(cid, **fields)
                self._json(200, {"ok": True, "item": item, "stats": case_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/customers/delete":
            try:
                delete_case((body.get("id") or "").strip())
                self._json(200, {"ok": True, "stats": case_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/customers/mark-contacted":
            try:
                days = body.get("followup_in_days")
                item = mark_contacted(
                    (body.get("id") or "").strip(),
                    note=(body.get("note") or body.get("last_note") or ""),
                    followup_in_days=int(days) if days not in (None, "") else None,
                )
                self._json(200, {"ok": True, "item": item, "stats": case_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/customers/append-codes":
            try:
                item = append_codes(
                    (body.get("id") or "").strip(),
                    offered=body.get("offered") or body.get("offered_codes"),
                    viewing=body.get("viewing") or body.get("viewing_codes"),
                    reserved=body.get("reserved") or body.get("reserved_codes"),
                )
                self._json(200, {"ok": True, "item": item, "stats": case_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/customers/recommend":
            try:
                cid = (body.get("id") or "").strip()
                if cid:
                    case = get_case(cid)
                    if not case:
                        self._json(404, {"error": "ไม่พบเคส"})
                        return
                else:
                    case = body.get("case") or body
                limit = int(body.get("limit") or 20)
                result = recommend_for_case(
                    case,
                    limit=limit,
                    exclude_offered=bool(body.get("exclude_offered", True)),
                    exclude_viewing=bool(body.get("exclude_viewing", False)),
                )
                # remember last recommend codes on saved cases
                if cid and result.get("items"):
                    codes = [x.get("code") for x in result["items"] if x.get("code")]
                    try:
                        update_case(cid, recommended_codes=codes[:30])
                    except ValueError:
                        pass
                self._json(200, result)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/customers/export-csv":
            try:
                path_out = write_followup_export_csv()
                self._json(
                    200,
                    {
                        "ok": True,
                        "export_csv": str(path_out.relative_to(BASE_DIR)),
                        "stats": case_stats(),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/co/match":
            try:
                limit = int(body.get("limit") or 30)
                result = match_co_brief(body, limit=limit)
                self._json(200, result)
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/properties/refresh-sheet":
            try:
                result = _run_sheet_refresh(
                    csv_url=(body.get("csv_url") or "").strip(),
                    wait_csv_url=(body.get("wait_csv_url") or "").strip(),
                )
                self._json(200, result)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except FileNotFoundError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/properties/sync-to-sheet":
            # Always queue in background. Inline push of ~7k rows exceeds Render
            # proxy idle timeout → browser sees HTML 502 ("เซิร์ฟเวอร์ตอบไม่ถูกต้อง").
            try:
                wait = bool(body.get("wait"))
                if wait:
                    with _SHEET_IO_LOCK:
                        result = push_hub_properties_to_sheet()
                    if not result.get("pushed"):
                        warn = result.get("push_warning") or "ซิงค์ชีทไม่สำเร็จ"
                        payload = {
                            "error": warn,
                            "ok": False,
                            "pushed": False,
                            "hub_count": result.get("hub_count", 0),
                            "overview_count": result.get("overview_count", 0),
                            "export_csv": result.get("export_csv"),
                            "synced_at": result.get("synced_at"),
                            "push_warning": warn,
                            "download_url": result.get("download_url")
                            or "/api/properties/overview-export.csv",
                        }
                        for key in (
                            "need_service_account",
                            "setup_steps",
                            "setup_hint",
                        ):
                            if key in result:
                                payload[key] = result[key]
                        self._json(502, payload)
                        return
                    self._json(200, result)
                    return
                queued = schedule_auto_sync_to_sheet(
                    reason="manual_sync_button",
                    debounce_sec=0.2,
                    force=True,
                )
                self._json(
                    202,
                    {
                        "ok": True,
                        "queued": True,
                        "async": True,
                        "status": queued.get("status") or "queued",
                        "generation": queued.get("generation") or 0,
                        "message": (
                            "กำลังซิงค์ขึ้นชีทในพื้นหลัง — รอสักครู่แล้วดูผลที่ปุ่มซิงค์"
                        ),
                        "poll_url": "/api/properties/sync-status",
                        "auto_sync_to_sheet": _auto_sync_status_payload(),
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        self._json(404, {"error": "ไม่พบ API"})


class ReuseThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _run_sheet_refresh(*, csv_url: str = "", wait_csv_url: str = "") -> dict:
    """Same path as POST /api/properties/refresh-sheet (main + wait-post queue)."""
    with _SHEET_IO_LOCK:
        result = refresh_main_sheet(csv_url=csv_url, rebuild=True)
        wait_meta: dict = {}
        wait_import: dict = {}
        try:
            wait_meta = refresh_wait_post_sheet(csv_url=wait_csv_url)
            wait_import = import_from_sheet_csv(replace=True)
        except Exception as wait_exc:  # noqa: BLE001
            wait_meta = {
                "ok": False,
                "download_warning": str(wait_exc),
            }
        result["wait_post"] = {
            **wait_meta,
            **wait_import,
            "stats": queue_stats(),
        }
        return result


def _startup_sheet_sync_enabled() -> bool:
    import os

    flag = (os.environ.get("HUB_STARTUP_SHEET_SYNC") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _startup_sheet_sync_worker() -> None:
    """Re-hydrate catalog from Google Sheet after deploy (Render disk is ephemeral)."""
    import os
    import threading

    # Bundled Docker data must be serveable even if sheet pull hangs/OOMs.
    try:
        ensured = ensure_preview_js()
        if ensured.get("rebuilt"):
            print(
                f"[hub] rebuilt preview-data.js from store "
                f"({ensured.get('reason')}, "
                f"{ensured.get('properties_total') or 0} properties)"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[hub] ensure_preview_js before sync failed: {exc}")

    if not _startup_sheet_sync_enabled():
        _STARTUP_SHEET_SYNC.update(
            {
                "status": "skipped",
                "message": "HUB_STARTUP_SHEET_SYNC disabled",
            }
        )
        print("[hub] startup sheet sync skipped (HUB_STARTUP_SHEET_SYNC=0)")
        return
    if not remote_sheet_source_configured():
        _STARTUP_SHEET_SYNC.update(
            {
                "status": "skipped",
                "message": "MAIN_SHEET_CSV_URL / SOURCE_GOOGLE_SHEETS_ID not set",
            }
        )
        print(
            "[hub] startup sheet sync skipped "
            "(set MAIN_SHEET_CSV_URL or SOURCE_GOOGLE_SHEETS_ID)"
        )
        return

    try:
        timeout_s = int(
            (os.environ.get("HUB_STARTUP_SHEET_SYNC_TIMEOUT") or "240").strip() or "240"
        )
    except ValueError:
        timeout_s = 240
    timeout_s = max(30, min(timeout_s, 900))

    import time as _time

    started = _time.time()
    _STARTUP_SHEET_SYNC.update(
        {
            "status": "running",
            "message": "pulling sheet…",
            "started_at": started,
        }
    )
    print(f"[hub] startup sheet sync starting (timeout {timeout_s}s)…")

    box: dict = {}

    def _run() -> None:
        try:
            box["result"] = _run_sheet_refresh()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    worker = threading.Thread(target=_run, daemon=True, name="startup-sheet-sync")
    worker.start()
    # Poll so status cannot stick on "running" if join misbehaves.
    while worker.is_alive() and (_time.time() - started) < timeout_s:
        worker.join(timeout=5.0)
        elapsed = int(_time.time() - started)
        if worker.is_alive():
            _STARTUP_SHEET_SYNC["message"] = f"pulling sheet… ({elapsed}s)"

    try:
        if worker.is_alive():
            # Leave the daemon thread running; do not let a hung sheet pull leave
            # status=running forever or block serving the baked catalog.
            try:
                n = len(load_properties())
            except Exception:
                n = 0
            msg = (
                f"startup sheet sync timed out after {timeout_s}s — "
                f"using bundled data ({n} properties)"
            )
            _STARTUP_SHEET_SYNC.update(
                {
                    "status": "error",
                    "properties_total": n,
                    "message": msg,
                }
            )
            print(f"[hub] {msg}")
        elif "error" in box:
            exc = box["error"]
            try:
                n = len(load_properties())
            except Exception:
                n = 0
            _STARTUP_SHEET_SYNC.update(
                {
                    "status": "error",
                    "properties_total": n,
                    "message": str(exc),
                }
            )
            print(
                f"[hub] startup sheet sync failed — using bundled data "
                f"({n} properties): {exc}"
            )
        else:
            result = box.get("result") or {}
            stats = result.get("stats") or {}
            n = int(
                stats.get("properties_total")
                or len(load_properties())
                or 0
            )
            warn = (result.get("download_warning") or "").strip()
            msg = f"startup sheet sync ok, {n} properties"
            if warn:
                msg = f"{msg} (download_warning: {warn})"
            _STARTUP_SHEET_SYNC.update(
                {
                    "status": "ok",
                    "properties_total": n,
                    "message": msg,
                    "downloaded": bool(result.get("downloaded")),
                    "source": result.get("source") or "",
                }
            )
            print(f"[hub] {msg}")
    finally:
        try:
            ensured = ensure_preview_js()
            if ensured.get("rebuilt"):
                print(
                    f"[hub] rebuilt preview-data.js after sync "
                    f"({ensured.get('properties_total') or 0} properties)"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[hub] ensure_preview_js after sync failed: {exc}")

def main() -> None:
    import os
    import threading
    import time

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", str(PORT)))

    # Make catalog JS available before the first browser hit (Render free tier
    # can otherwise briefly 404 preview-data.js during a bad sync window).
    try:
        ensured = ensure_preview_js()
        if ensured.get("rebuilt"):
            print(
                f"[hub] boot: rebuilt preview-data.js "
                f"({ensured.get('properties_total') or 0} properties)"
            )
        else:
            print(
                f"[hub] boot: preview-data.js ok "
                f"({ensured.get('properties_total') or 0} properties)"
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[hub] boot ensure_preview_js failed: {exc}")

    server = ReuseThreadingHTTPServer((host, port), HubHandler)

    for _ in range(2):
        threading.Thread(target=_thumb_worker_loop, daemon=True).start()

    def _warm_recent_thumbs() -> None:
        time.sleep(2)
        try:
            props = load_properties()
        except Exception as exc:  # noqa: BLE001
            print(f"[hub] thumb warm skip: {exc}")
            return
        candidates = []
        for p in props:
            if (p.get("import_status") or "") not in ("", "active"):
                continue
            u = (p.get("post_pages_url") or "").strip()
            if u.startswith("http"):
                candidates.append(u)
            if len(candidates) >= 20:
                break
        for u in candidates:
            enqueue_preview_thumb(u)
        print(f"[hub] queued {len(candidates)} page thumbs for background warm")

    # Background: pull sheet so redeploys restore catalog without manual 「รีเฟรชชีท」.
    # Server listens first so Render health checks pass during the sync window.
    threading.Thread(target=_startup_sheet_sync_worker, daemon=True).start()
    threading.Thread(target=_warm_recent_thumbs, daemon=True).start()

    print("=== Property Hub Server (Phase 2) ===")
    print(f"Listening: http://{host}:{port}/")
    print("API:  scrape/parse/generate · projects · queue · preview-thumb")
    print(f"Co-Agent: http://{host}:{port}/co/")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
