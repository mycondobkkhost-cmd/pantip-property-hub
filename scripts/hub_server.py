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
from src.hub.project_store import (  # noqa: E402
    PREVIEW_JS,
    PREVIEW_META,
    create_project,
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
    focus_stats,
    list_focus,
    toggle_focus,
)
from src.hub.customer_match import recommend_for_case  # noqa: E402
from src.hub.co_catalog import build_co_catalog, match_co_brief  # noqa: E402
from src.hub.scraper import scrape_url, fetch_preview_image, fetch_image_bytes  # noqa: E402
from src.hub.sheet_sync import refresh_main_sheet, refresh_wait_post_sheet  # noqa: E402
from src.hub.sheet_write import push_hub_properties_to_sheet  # noqa: E402
from src.hub.text_gen import generate_text  # noqa: E402

PORT = 8765
SCRAPER_VERSION = "mobile-ua-proxy-bypass-v4"
THUMB_CACHE_DIR = BASE_DIR / "data" / "thumb_cache"
_PREVIEW_OG_CACHE: dict[str, str] = {}
_PREVIEW_BYTES_CACHE: dict[str, tuple[bytes, str]] = {}
_CO_CATALOG_CACHE: dict = {"mtime": 0.0, "data": None}
_PREVIEW_CACHE_MAX = 400
_THUMB_FETCH_LOCK = __import__("threading").Semaphore(1)
_THUMB_PENDING: set[str] = set()
_THUMB_QUEUE = __import__("queue").Queue()
_THUMB_FAIL_UNTIL: dict[str, float] = {}


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
    return next_hub_code(
        load_properties(),
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
                },
            )
            return
        if path == "/api/data-meta":
            self._json(200, _preview_data_meta())
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
            self.send_error(404)
            return
        content = file_path.read_bytes()
        ctype = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        if file_path.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        # Cache-bust embedded catalog so Safari/mobile cannot keep a stale preview-data.js
        if file_path.name == "preview.html":
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
        # Avoid stale UI/data after sheet refresh — never long-cache HTML/JS/CSS/JSON
        if file_path.suffix in {".html", ".js", ".css", ".json"} or file_path.name.endswith(".meta.json"):
            _no_store_headers(self)
        self.end_headers()
        self.wfile.write(content)

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
                self._json(
                    200,
                    {
                        "ok": True,
                        "property": prop,
                        "next_code": next_rxt_code(prop.get("code_prefix") or "RXT"),
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
                self._json(200, {"ok": True, "property": prop})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/properties/update-links":
            try:
                pid = (body.get("id") or body.get("code") or "").strip()
                prop = update_property_links(pid, body)
                self._json(200, {"ok": True, "property": prop})
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

        if path == "/api/focus/toggle":
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
                result = refresh_main_sheet(
                    csv_url=(body.get("csv_url") or "").strip(),
                    rebuild=True,
                )
                # Also pull รอโพสต์ tab → queue (same refresh action users expect)
                wait_meta: dict = {}
                wait_import: dict = {}
                try:
                    wait_meta = refresh_wait_post_sheet(
                        csv_url=(body.get("wait_csv_url") or "").strip()
                    )
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
                self._json(200, result)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except FileNotFoundError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/properties/sync-to-sheet":
            try:
                result = push_hub_properties_to_sheet()
                self._json(200, result)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        self._json(404, {"error": "ไม่พบ API"})


class ReuseThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def main() -> None:
    import os
    import threading
    import time

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", str(PORT)))
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
