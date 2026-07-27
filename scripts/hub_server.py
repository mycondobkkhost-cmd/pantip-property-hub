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
from src.hub.group_post_store import (  # noqa: E402
    add_code as add_comment_code,
    add_link_for_code,
    add_post_link,
    comments_today_count,
    delete_code as delete_comment_code,
    delete_item as delete_group_post_link,
    get_code_detail,
    list_codes as list_comment_codes,
    list_due as list_group_post_due,
    list_items as list_group_post_links,
    stats as group_post_link_stats,
    update_code as update_comment_code,
    update_item as update_group_post_link,
)
from src.hub.fb_agent_store import (  # noqa: E402
    agent_heartbeat,
    agent_pull,
    public_status as fb_agent_public_status,
    request_login as fb_agent_request_login,
    rotate_agent_token,
    set_credentials as fb_agent_set_credentials,
    verify_agent_token,
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
    load_queue,
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
    merge_cases_from_sheet,
    replace_cases_from_sheet,
    update_case,
    write_followup_export_csv,
)
from src.hub.tenant_store import (  # noqa: E402
    STATUS_LABELS as TENANT_STATUS_LABELS,
    add_tenant,
    delete_tenant,
    list_tenants,
    merge_tenants_from_sheet,
    replace_tenants_from_sheet,
    tenant_alerts,
    tenant_stats,
    update_tenant,
)
from src.hub.focus_store import (  # noqa: E402
    add_focus_codes,
    focus_stats,
    list_focus,
    merge_focus_from_sheet,
    remove_focus_ref,
    replace_focus_from_sheet,
    toggle_focus,
)
from src.hub.location_master_store import (  # noqa: E402
    delete_transit,
    delete_zone,
    ensure_labels,
    ensure_masters_ready,
    ensure_transit,
    ensure_zone,
    list_transits,
    list_zones,
    replace_transits_from_sheet,
    replace_zones_from_sheet,
    seed_from_dataset,
    update_transit,
    update_zone,
)
from src.hub.customer_match import recommend_for_case  # noqa: E402
from src.hub.co_catalog import get_co_catalog, match_co_brief  # noqa: E402
from src.hub.scraper import scrape_url, fetch_preview_image, fetch_image_bytes  # noqa: E402
from src.hub.sheet_sync import (  # noqa: E402
    refresh_main_sheet,
    refresh_wait_post_sheet,
    remote_sheet_source_configured,
)
from src.hub.sheet_write import (  # noqa: E402
    OVERVIEW_EXPORT_CSV,
    append_wait_post_job,
    delete_wait_post_job,
    pull_wait_post_sheet_via_gspread,
    push_hub_properties_to_sheet,
    update_wait_post_job,
    write_overview_export_csv,
)
from src.hub.text_gen import generate_text  # noqa: E402
from src.hub.line_menu_webhook import (  # noqa: E402
    line_health_payload,
    process_webhook as process_line_webhook,
)
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
_AUTO_SYNC_DEBOUNCE_SEC = 2.0
# Hub→Sheet dirty flush: if edits never completed a push, retry after this age.
_SHEET_EXPORT_DIRTY_FLUSH_SEC = 600.0
_SHEET_EXPORT_DIRTY_AT = 0.0
_SHEET_EXPORT_LAST_OK_AT = 0.0
# Serialize Google Sheet pull/push so startup refresh and sync don't fight.
_SHEET_IO_LOCK = __import__("threading").Lock()
# Wait-post queue lives on local JSON — on Fly with >1 machine that splits.
# Re-hydrate from Google Sheet「รอโพสต์」so GET sees adds from any instance.
_QUEUE_SHEET_SYNC: dict = {"last": 0.0}
_QUEUE_SHEET_SYNC_LOCK = __import__("threading").Lock()
_PREVIEW_CACHE_MAX = 400
_THUMB_FETCH_LOCK = __import__("threading").Semaphore(1)
_THUMB_PENDING: set[str] = set()
_THUMB_QUEUE = __import__("queue").Queue()
_THUMB_FAIL_UNTIL: dict[str, float] = {}


def _auto_sync_to_sheet_enabled() -> bool:
    import os

    flag = (os.environ.get("HUB_AUTO_SYNC_TO_SHEET") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _sheet_pull_allowed() -> bool:
    """Emergency-only: Hub volume is SoT; sheet pull is off unless explicitly enabled."""
    import os

    flag = (os.environ.get("HUB_ALLOW_SHEET_PULL") or "0").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _mark_sheet_export_dirty() -> None:
    import time

    global _SHEET_EXPORT_DIRTY_AT
    _SHEET_EXPORT_DIRTY_AT = time.time()


def _mark_sheet_export_ok() -> None:
    import time

    global _SHEET_EXPORT_LAST_OK_AT, _SHEET_EXPORT_DIRTY_AT
    now = time.time()
    _SHEET_EXPORT_LAST_OK_AT = now
    # Clear dirty only when nothing else is pending.
    with _AUTO_SYNC_LOCK:
        if not _AUTO_SYNC_TO_SHEET.get("pending"):
            _SHEET_EXPORT_DIRTY_AT = 0.0


def _queue_sheet_sync_enabled() -> bool:
    import os

    flag = (os.environ.get("HUB_QUEUE_SHEET_SYNC") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _queue_sheet_sync_interval_sec() -> float:
    import os

    raw = (os.environ.get("HUB_QUEUE_SHEET_SYNC_SEC") or "8").strip() or "8"
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 8.0


def sync_queue_from_sheet(*, force: bool = False) -> dict:
    """Pull「รอโพสต์」and replace local queue (preserve hub-local pending).

    Prefers gspread (service account) because public CSV export often 401s.
    """
    import time

    if not _queue_sheet_sync_enabled():
        return {"ok": True, "skipped": True, "reason": "disabled"}
    now = time.time()
    interval = _queue_sheet_sync_interval_sec()
    with _QUEUE_SHEET_SYNC_LOCK:
        if not force and (now - float(_QUEUE_SHEET_SYNC.get("last") or 0)) < interval:
            return {"ok": True, "skipped": True, "reason": "debounce"}
        with _SHEET_IO_LOCK:
            wait_meta: dict = {}
            try:
                wait_meta = pull_wait_post_sheet_via_gspread()
            except Exception as gs_exc:  # noqa: BLE001
                wait_meta = refresh_wait_post_sheet()
                wait_meta["gspread_error"] = str(gs_exc)
            wait_import = import_from_sheet_csv(replace=True)
        _QUEUE_SHEET_SYNC["last"] = time.time()
        return {"ok": True, **wait_meta, **wait_import}


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

    _mark_sheet_export_dirty()

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


def _flush_pending_sheet_sync(*, timeout_sec: float = 90.0) -> dict:
    """Run any queued Hub→Sheet push immediately (deploy/shutdown safety)."""
    import time

    with _AUTO_SYNC_LOCK:
        pending = bool(_AUTO_SYNC_TO_SHEET.get("pending"))
        running = bool(_AUTO_SYNC_TO_SHEET.get("running"))
        if not pending and not running:
            return {"ok": True, "flushed": False, "reason": "idle"}
        reason = _AUTO_SYNC_TO_SHEET.get("reason") or "flush"
        _AUTO_SYNC_TO_SHEET["pending"] = False
        if running:
            # Wait briefly for in-flight push.
            deadline = time.time() + min(30.0, timeout_sec)
            while time.time() < deadline and _AUTO_SYNC_TO_SHEET.get("running"):
                time.sleep(0.4)
            if _AUTO_SYNC_TO_SHEET.get("running"):
                return {"ok": False, "flushed": False, "reason": "still_running"}
            if not _AUTO_SYNC_TO_SHEET.get("pending"):
                return {"ok": True, "flushed": True, "reason": "waited"}
            reason = _AUTO_SYNC_TO_SHEET.get("reason") or reason
            _AUTO_SYNC_TO_SHEET["pending"] = False
        _AUTO_SYNC_TO_SHEET["running"] = True
        _AUTO_SYNC_TO_SHEET["status"] = "running"
        _AUTO_SYNC_TO_SHEET["message"] = f"flushing ({reason})…"

    print(f"[hub] flush sheet sync start ({reason})")
    try:
        with _SHEET_IO_LOCK:
            result = push_hub_properties_to_sheet()
        pushed = bool(result.get("pushed"))
        with _AUTO_SYNC_LOCK:
            _AUTO_SYNC_TO_SHEET.update(
                {
                    "status": "ok" if pushed else "error",
                    "pushed": pushed,
                    "running": False,
                    "result": result,
                    "message": f"flushed pushed={pushed}",
                    "completed_generation": int(
                        _AUTO_SYNC_TO_SHEET.get("generation") or 0
                    ),
                }
            )
        print(f"[hub] flush sheet sync done pushed={pushed}")
        if pushed:
            _mark_sheet_export_ok()
        return {"ok": pushed, "flushed": True, "result": result}
    except Exception as exc:  # noqa: BLE001
        with _AUTO_SYNC_LOCK:
            _AUTO_SYNC_TO_SHEET.update(
                {
                    "status": "error",
                    "running": False,
                    "message": f"flush failed: {exc}",
                }
            )
        print(f"[hub] flush sheet sync failed: {exc}")
        return {"ok": False, "flushed": False, "error": str(exc)}


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
            # Still keep pending=True so clients keep polling instead of
            # timing out while boot refresh holds the sheet lock.
            startup = (_STARTUP_SHEET_SYNC.get("status") or "").strip()
            if startup == "running":
                _AUTO_SYNC_TO_SHEET["status"] = "queued"
                _AUTO_SYNC_TO_SHEET["message"] = "waiting for startup sheet pull…"
                continue
            # Manual sync: start as soon as startup finished (or timed out).
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
            if pushed:
                _mark_sheet_export_ok()
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


def _periodic_sheet_export_worker() -> None:
    """If Hub edits stayed dirty without a completed push, flush after ~10 minutes."""
    import time

    while True:
        time.sleep(60.0)
        try:
            dirty_at = float(_SHEET_EXPORT_DIRTY_AT or 0.0)
            last_ok = float(_SHEET_EXPORT_LAST_OK_AT or 0.0)
            if dirty_at <= 0:
                continue
            if dirty_at <= last_ok:
                continue
            age = time.time() - dirty_at
            if age < _SHEET_EXPORT_DIRTY_FLUSH_SEC:
                continue
            with _AUTO_SYNC_LOCK:
                if _AUTO_SYNC_TO_SHEET.get("running") or _AUTO_SYNC_TO_SHEET.get(
                    "pending"
                ):
                    continue
            print(
                f"[hub] periodic sheet export: dirty for {int(age)}s — queueing push"
            )
            schedule_auto_sync_to_sheet(
                reason="periodic_dirty_flush",
                debounce_sec=0.1,
                force=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[hub] periodic sheet export skipped: {exc}")


def _cache_put(cache: dict, key: str, value) -> None:
    cache[key] = value
    while len(cache) > _PREVIEW_CACHE_MAX:
        cache.pop(next(iter(cache)), None)


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


def _is_cloud_host() -> bool:
    """True on Render / Fly (and similar) where HTTPS + real user secrets apply."""
    import os

    return bool(
        (os.environ.get("RENDER") or "").strip()
        or (os.environ.get("FLY_APP_NAME") or "").strip()
        or (os.environ.get("FORCE_SECURE_COOKIES") or "").strip()
    )


def _parse_hub_users_json(raw: str):
    """Parse HUB_USERS_JSON; tolerate fly secrets import quote-escaping."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # fly secrets import of bare JSON can store {\"k\":\"v\"} instead of {"k":"v"}
        if '\\"' in raw:
            try:
                return json.loads(raw.replace('\\"', '"'))
            except json.JSONDecodeError:
                pass
        raise


def _load_hub_users() -> dict:
    """Login users from HUB_USERS_JSON only (never embed passwords in HTML).

    Local fallback is intentional weak demo accounts — production on Render/Fly
    must set HUB_USERS_JSON (and ideally HUB_SESSION_SECRET).
    """
    import os

    raw = (os.environ.get("HUB_USERS_JSON") or "").strip()
    if raw:
        try:
            data = _parse_hub_users_json(raw)
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

    if _is_cloud_host():
        print("[hub] WARN: HUB_USERS_JSON not set on cloud host — login will fail until configured")
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


_AGENT_API_PREFIXES = (
    "/api/fb-agent/pull",
    "/api/fb-agent/heartbeat",
)


def _request_agent_token(handler: "HubHandler") -> str:
    auth = (handler.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (handler.headers.get("X-Agent-Token") or "").strip()


def _is_agent_authorized(handler: "HubHandler") -> bool:
    return verify_agent_token(_request_agent_token(handler))


def _fb_agent_starter_download(handler: "HubHandler", *, kind: str) -> None:
    """Serve a ready-to-run starter script for Windows (.bat) or Mac (.command)."""
    from urllib.parse import parse_qs

    qs = parse_qs(urlparse(handler.path).query or "")
    status = fb_agent_public_status(include_token=True)
    token = str(status.get("agent_token") or "").strip()
    if not token:
        handler._json(500, {"ok": False, "error": "ยังไม่มีรหัสเชื่อมต่อ"})
        return
    hub_url = ((qs.get("hub") or [""])[0] or "").strip()
    if not hub_url:
        host = (handler.headers.get("Host") or "127.0.0.1:8765").strip()
        hub_url = f"http://{host}"
    project_dir = str(BASE_DIR.resolve())

    kind = (kind or "windows").strip().lower()
    if kind in {"mac", "macos", "darwin"}:
        tpl = BASE_DIR / "scripts" / "mac" / "เปิดระบบคอมเมนต์.command.template"
        fallback = (
            "#!/bin/bash\n"
            'PROJECT_DIR="__PROJECT_DIR__"\n'
            'HUB_URL="__HUB_URL__"\n'
            'COMMENT_AGENT_TOKEN="__AGENT_TOKEN__"\n'
            'xattr -d com.apple.quarantine "$0" 2>/dev/null || true\n'
            'cd "$PROJECT_DIR" || exit 1\n'
            'python3 scripts/comment_agent.py --hub "$HUB_URL" --token "$COMMENT_AGENT_TOKEN"\n'
            'read -r -p "กด Enter เพื่อปิด..."\n'
        )
        filename = "เปิดระบบคอมเมนต์.command"
        text = tpl.read_text(encoding="utf-8") if tpl.exists() else fallback
        text = (
            text.replace("__PROJECT_DIR__", project_dir)
            .replace("__HUB_URL__", hub_url)
            .replace("__AGENT_TOKEN__", token)
        )
        data = text.encode("utf-8")
        handler._send_bytes(
            200,
            data,
            content_type="application/x-sh",
            filename=filename,
        )
        return

    tpl = BASE_DIR / "scripts" / "windows" / "เปิดระบบคอมเมนต์.bat.template"
    if not tpl.exists():
        tpl = BASE_DIR / "scripts" / "windows" / "start_comment_agent.template.bat"
    if tpl.exists():
        text = tpl.read_text(encoding="utf-8")
    else:
        text = (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "title ระบบคอมเมนต์เฟส PTP\r\n"
            'cd /d "%~dp0..\\.."\r\n'
            'set "HUB_URL=__HUB_URL__"\r\n'
            'set "COMMENT_AGENT_TOKEN=__AGENT_TOKEN__"\r\n'
            "echo เปิดทิ้งไว้ — อย่าปิดหน้าต่างนี้\r\n"
            'python scripts\\comment_agent.py --hub "%HUB_URL%" --token "%COMMENT_AGENT_TOKEN%"\r\n'
            "pause\r\n"
        )
    text = text.replace("__HUB_URL__", hub_url.replace("%", "%%"))
    text = text.replace("__AGENT_TOKEN__", token.replace("%", "%%"))
    data = ("\ufeff" + text.replace("\n", "\r\n")).encode("utf-8")
    handler._send_bytes(
        200,
        data,
        content_type="application/octet-stream",
        filename="เปิดระบบคอมเมนต์.bat",
    )


def _fb_agent_install_mac_to_downloads() -> dict:
    """Write ready .command into ~/Downloads so user never has to move files."""
    import os
    import subprocess

    status = fb_agent_public_status(include_token=True)
    token = str(status.get("agent_token") or "").strip()
    if not token:
        raise ValueError("ยังไม่มีรหัสเชื่อมต่อ")

    hub_url = "http://127.0.0.1:8765"
    project_dir = str(BASE_DIR.resolve())
    tpl = BASE_DIR / "scripts" / "mac" / "เปิดระบบคอมเมนต์.command.template"
    if not tpl.exists():
        raise ValueError("ไม่พบเทมเพลตไฟล์ Mac")
    text = (
        tpl.read_text(encoding="utf-8")
        .replace("__PROJECT_DIR__", project_dir)
        .replace("__HUB_URL__", hub_url)
        .replace("__AGENT_TOKEN__", token)
    )
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    out = downloads / "เปิดระบบคอมเมนต์.command"
    out.write_text(text, encoding="utf-8")
    os.chmod(out, 0o755)
    try:
        subprocess.run(
            ["xattr", "-d", "com.apple.quarantine", str(out)],
            check=False,
            capture_output=True,
        )
    except OSError:
        pass
    # Open Downloads folder in Finder so user can see the file
    try:
        subprocess.run(["open", "-R", str(out)], check=False, capture_output=True)
    except OSError:
        try:
            subprocess.run(["open", str(downloads)], check=False, capture_output=True)
        except OSError:
            pass
    return {
        "ok": True,
        "path": str(out),
        "folder": str(downloads),
        "filename": out.name,
    }


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
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        _no_store_headers(self)
        secure = "; Secure" if _is_cloud_host() else ""
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
            from urllib.parse import quote

            ascii_name = (
                "open-comment-system.command"
                if filename.endswith(".command")
                else "open-comment-system.bat"
                if filename.endswith(".bat")
                else "download.bin"
            )
            self.send_header(
                "Content-Disposition",
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
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

        # Public GET APIs (no Hub session). Everything else under /api/* requires login.
        # Static Hub/Co pages and preview-data.js stay public below (SPA has its own login gate).
        _public_get_apis = frozenset(
            {
                "/api/auth/me",
                "/api/health",
                "/api/co/catalog",
                "/api/preview-image",
                "/api/preview-thumb",
            }
        )
        if (
            path.startswith("/api/")
            and path not in _public_get_apis
            and not path.startswith("/api/co/")
            and not path.startswith("/api/auth/")
        ):
            if path.startswith("/api/fb-agent/") and _is_agent_authorized(self):
                pass
            elif not self._session_user():
                self._json(401, {"ok": False, "error": "กรุณาเข้าสู่ระบบ"})
                return

        if path == "/api/fb-agent/status":
            self._json(200, fb_agent_public_status(include_token=True))
            return
        if path == "/api/fb-agent/download-windows":
            _fb_agent_starter_download(self, kind="windows")
            return
        if path == "/api/fb-agent/download-mac":
            _fb_agent_starter_download(self, kind="mac")
            return
        if path == "/api/fb-agent/pull":
            if not _is_agent_authorized(self):
                self._json(401, {"ok": False, "error": "agent token ไม่ถูกต้อง"})
                return
            self._json(200, agent_pull())
            return

        if path == "/api/auth/me":
            user = self._session_user()
            if not user:
                self._json(401, {"ok": False, "logged_in": False})
                return
            self._json(200, {"ok": True, "logged_in": True, "username": user["username"], "name": user["name"]})
            return
        if path in {"/line/health", "/line/webhook"}:
            self._json(200, line_health_payload())
            return
        if path == "/api/health":
            from urllib.parse import parse_qs

            # Fly/keepalive probes stay public with a minimal payload; full stats need session.
            if not self._session_user():
                self._json(
                    200,
                    {
                        "ok": True,
                        "phase": 2,
                        "scraper": SCRAPER_VERSION,
                    },
                )
                return
            qs = parse_qs(urlparse(self.path).query or "")
            prefix = ((qs.get("prefix") or ["RXT"])[0] or "RXT").strip().upper()
            stats = queue_stats()
            meta = _preview_data_meta()
            focus = focus_stats()
            customers = case_stats()
            tenants = tenant_stats()
            line = line_health_payload()
            self._json(
                200,
                {
                    "ok": True,
                    "phase": 2,
                    "scraper": SCRAPER_VERSION,
                    "next_code": next_rxt_code(prefix),
                    "queue_pending": stats["pending"] + stats["working"],
                    "focus_total": focus.get("total") or 0,
                    "customers_open": customers.get("open") or 0,
                    "tenants_active": tenants.get("active") or 0,
                    "tenants_alerts": tenants.get("alerts") or 0,
                    "data_version": meta.get("data_version") or "",
                    "properties_total": meta.get("properties_total") or 0,
                    "generated_at": meta.get("generated_at") or "",
                    "startup_sheet_sync": dict(_STARTUP_SHEET_SYNC),
                    "auto_sync_to_sheet": _auto_sync_status_payload(),
                    "line_menu": {
                        "enabled": line.get("enabled"),
                        "chat_mode": line.get("chat_mode"),
                        "triggers": len(line.get("menu_triggers") or []),
                    },
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
            q = urlparse(self.path).query or ""
            force_sync = "sync=1" in q or "refresh=1" in q
            try:
                sync_queue_from_sheet(force=force_sync)
            except Exception as sync_exc:  # noqa: BLE001
                print(f"[hub] queue sheet sync on GET failed: {sync_exc}")
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
        if path == "/api/tenants":
            include_moved = "moved=1" in (urlparse(self.path).query or "")
            items = list_tenants(include_moved_out=include_moved)
            self._json(
                200,
                {
                    "items": items,
                    "stats": tenant_stats(),
                    "alerts": tenant_alerts(items),
                    "status_labels": TENANT_STATUS_LABELS,
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
        if path == "/api/group-posts":
            from urllib.parse import parse_qs

            qs = parse_qs(urlparse(self.path).query or "")
            status = ((qs.get("status") or [""])[0] or "").strip() or None
            code = ((qs.get("code") or [""])[0] or "").strip() or None
            try:
                limit = int((qs.get("limit") or ["300"])[0] or 300)
            except ValueError:
                limit = 300
            items = list_group_post_links(status=status, property_code=code, limit=limit)
            self._json(
                200,
                {
                    "ok": True,
                    "items": items,
                    "stats": group_post_link_stats(),
                    "due": list_group_post_due(limit=50),
                },
            )
            return
        if path == "/api/comment-codes":
            from urllib.parse import parse_qs

            qs = parse_qs(urlparse(self.path).query or "")
            try:
                limit = int((qs.get("limit") or ["300"])[0] or 300)
            except ValueError:
                limit = 300
            items = list_comment_codes(limit=limit)
            link_stats = group_post_link_stats()
            active_n = sum(1 for x in items if x.get("active"))
            links_n = sum(int(x.get("link_count") or 0) for x in items)
            due_n = sum(int(x.get("due_count") or 0) for x in items)
            fb = fb_agent_public_status(include_token=False)
            self._json(
                200,
                {
                    "ok": True,
                    "items": items,
                    "dashboard": {
                        "codes_total": len(items),
                        "codes_active": active_n,
                        "links_total": links_n,
                        "due_total": due_n,
                        "comments_today": comments_today_count(),
                        "links_stats": link_stats,
                        "fb": fb,
                    },
                },
            )
            return
        if path == "/api/comment-code-detail":
            from urllib.parse import parse_qs

            qs = parse_qs(urlparse(self.path).query or "")
            code = ((qs.get("code") or [""])[0] or "").strip()
            try:
                self._json(200, {"ok": True, **get_code_detail(code)})
            except ValueError as exc:
                self._json(404, {"ok": False, "error": str(exc)})
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
        if path == "/api/zones":
            try:
                ensure_masters_ready()
                items = list_zones()
                self._json(200, {"ok": True, "items": items, "total": len(items)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/api/transits":
            try:
                ensure_masters_ready()
                items = list_transits()
                self._json(200, {"ok": True, "items": items, "total": len(items)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return
        if path == "/api/co/catalog":
            try:
                self._json(200, get_co_catalog())
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return
        if path in {"/co", "/co/"}:
            path = "/co/index.html"
        if path == "/":
            path = "/preview.html"
        # Catalog JS/meta live on the data volume (not ephemeral hub/).
        if path.rstrip("/").endswith("preview-data.js"):
            file_path = PREVIEW_JS.resolve()
        elif path.rstrip("/").endswith("preview-data.meta.json"):
            file_path = PREVIEW_META.resolve()
        else:
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
        if file_path.name == "preview-data.js":
            ctype = "application/javascript; charset=utf-8"
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

        # LINE Rich Menu webhook — raw body + signature (no Hub auth)
        if path in {"/line/webhook", "/webhook/line"}:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            sig = self.headers.get("X-Line-Signature") or ""
            status, payload = process_line_webhook(raw, sig)
            self._json(status, payload)
            return

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

        # Hub SPA uses cookie session; Co-Agent match stays public for /co/.
        # LINE webhook is handled above (raw body) before JSON parse.
        # Comment agent may use bearer token on /api/fb-agent/*.
        is_agent_api = any(path.startswith(p) or path == p for p in _AGENT_API_PREFIXES) or path.startswith(
            "/api/fb-agent/"
        )
        if path != "/api/co/match":
            if is_agent_api and _is_agent_authorized(self):
                pass
            elif not self._session_user():
                self._json(401, {"ok": False, "error": "กรุณาเข้าสู่ระบบ"})
                return

        if path == "/api/fb-agent/credentials":
            try:
                email = (body.get("email") or "").strip()
                password = body.get("password")
                if password is not None:
                    password = str(password)
                self._json(200, {"ok": True, **fb_agent_set_credentials(email=email, password=password)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/fb-agent/request-login":
            try:
                self._json(200, {"ok": True, **fb_agent_request_login()})
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/fb-agent/install-mac":
            try:
                self._json(200, _fb_agent_install_mac_to_downloads())
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/fb-agent/rotate-token":
            try:
                self._json(200, {"ok": True, **rotate_agent_token()})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/fb-agent/heartbeat":
            if not _is_agent_authorized(self):
                self._json(401, {"ok": False, "error": "agent token ไม่ถูกต้อง"})
                return
            try:
                fb_flag = body.get("fb_logged_in")
                self._json(
                    200,
                    {
                        "ok": True,
                        **agent_heartbeat(
                            status=str(body.get("status") or "online"),
                            message=str(body.get("message") or ""),
                            hostname=str(body.get("hostname") or ""),
                            fb_logged_in=None if fb_flag is None else bool(fb_flag),
                            clear_login_request=bool(body.get("clear_login_request")),
                            last_run=body.get("last_run") if isinstance(body.get("last_run"), dict) else None,
                        ),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/fb-agent/pull":
            if not _is_agent_authorized(self):
                self._json(401, {"ok": False, "error": "agent token ไม่ถูกต้อง"})
                return
            self._json(200, agent_pull())
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

        if path == "/api/group-posts":
            try:
                status = (body.get("status") or "").strip() or None
                code = (body.get("code") or body.get("property_code") or "").strip() or None
                limit = int(body.get("limit") or 300)
                items = list_group_post_links(status=status, property_code=code, limit=limit)
                self._json(
                    200,
                    {
                        "ok": True,
                        "items": items,
                        "stats": group_post_link_stats(),
                        "due": list_group_post_due(limit=50),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/group-posts/add":
            try:
                code = (body.get("code") or body.get("property_code") or "").strip()
                if code:
                    item = add_link_for_code(
                        code,
                        post_url=(body.get("post_url") or body.get("url") or "").strip(),
                        group_url=(body.get("group_url") or "").strip(),
                        group_name=(body.get("group_name") or "").strip(),
                        comment_immediately=bool(body.get("comment_immediately")),
                    )
                else:
                    item = add_post_link(
                    post_url=(body.get("post_url") or body.get("url") or "").strip(),
                    property_code=code,
                    group_url=(body.get("group_url") or "").strip(),
                    group_name=(body.get("group_name") or "").strip(),
                    max_comments=body.get("max_comments"),
                    comment_immediately=bool(body.get("comment_immediately")),
                )
                self._json(200, {"ok": True, "item": item, "stats": group_post_link_stats()})
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/group-posts/update":
            try:
                item_id = (body.get("id") or "").strip()
                patch = body.get("patch") or body
                item = update_group_post_link(item_id, patch)
                self._json(200, {"ok": True, "item": item})
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/group-posts/delete":
            try:
                item_id = (body.get("id") or "").strip()
                ok = delete_group_post_link(item_id)
                if not ok:
                    self._json(404, {"ok": False, "error": "ไม่พบรายการ"})
                    return
                self._json(200, {"ok": True, "stats": group_post_link_stats()})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/comment-codes":
            try:
                self._json(200, {"ok": True, "items": list_comment_codes(limit=int(body.get("limit") or 300))})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/comment-codes/add":
            try:
                code = (body.get("code") or "").strip()
                item = add_comment_code(code)
                self._json(200, {"ok": True, "item": item})
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/comment-codes/update":
            try:
                code = (body.get("code") or "").strip()
                patch = body.get("patch") or body
                item = update_comment_code(code, patch)
                self._json(200, {"ok": True, "item": item})
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/comment-codes/delete":
            try:
                code = (body.get("code") or "").strip()
                ok = delete_comment_code(code)
                if not ok:
                    self._json(404, {"ok": False, "error": "ไม่พบรหัส"})
                    return
                self._json(200, {"ok": True})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
            return

        if path == "/api/comment-code-detail":
            try:
                code = (body.get("code") or "").strip()
                self._json(200, {"ok": True, **get_code_detail(code)})
            except ValueError as exc:
                self._json(404, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"ok": False, "error": str(exc)})
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
                try:
                    ensure_labels(
                        zones=project_zone_display(project),
                        transits=project_transit_display(project),
                    )
                except Exception as master_exc:  # noqa: BLE001
                    print(f"[hub] ensure location masters after create: {master_exc}")
                sheet_sync = schedule_auto_sync_to_sheet(
                    reason=f"project-create {(project.get('canonical_name') or name or '')[:40]}"
                )
                self._json(
                    200,
                    {
                        "ok": True,
                        "project": project,
                        "transit_display": ", ".join(project_transit_display(project)),
                        "zone_display": ", ".join(project_zone_display(project)),
                        "location_display": project_location_label(project),
                        "sheet_sync": sheet_sync,
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
                try:
                    ensure_labels(zones=zones, transits=tags)
                except Exception as master_exc:  # noqa: BLE001
                    print(f"[hub] ensure location masters after transit: {master_exc}")
                sheet_sync = schedule_auto_sync_to_sheet(
                    reason=f"project-transit {project_id[:12]}"
                )
                self._json(
                    200,
                    {
                        "ok": True,
                        "project": project,
                        "listings_updated": listings_updated,
                        "transit_display": ", ".join(tags),
                        "zone_display": ", ".join(zones),
                        "location_display": project_location_label(project),
                        "sheet_sync": sheet_sync,
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
                try:
                    ensure_labels(zones=zones, transits=tags)
                except Exception as master_exc:  # noqa: BLE001
                    print(f"[hub] ensure location masters after update: {master_exc}")
                sheet_sync = schedule_auto_sync_to_sheet(
                    reason=f"project-update {project_id[:12]}"
                )
                self._json(
                    200,
                    {
                        "ok": True,
                        "project": project,
                        "listings_updated": listings_updated,
                        "transit_display": ", ".join(tags),
                        "zone_display": ", ".join(zones),
                        "location_display": project_location_label(project),
                        "sheet_sync": sheet_sync,
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/zones/create":
            try:
                label = (body.get("label") or body.get("name") or "").strip()
                item = ensure_zone(label)
                self._json(200, {"ok": True, "item": item})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/zones/update":
            try:
                item_id = (body.get("id") or "").strip()
                item = update_zone(
                    item_id,
                    label=body.get("label") if "label" in body else None,
                    aliases=body.get("aliases") if "aliases" in body else None,
                )
                self._json(200, {"ok": True, "item": item})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/zones/delete":
            try:
                item_id = (body.get("id") or "").strip()
                self._json(200, delete_zone(item_id))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/zones/seed":
            try:
                self._json(200, seed_from_dataset(force=True))
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/transits/create":
            try:
                label = (body.get("label") or body.get("name") or "").strip()
                item = ensure_transit(label)
                self._json(200, {"ok": True, "item": item})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/transits/update":
            try:
                item_id = (body.get("id") or "").strip()
                item = update_transit(
                    item_id,
                    label=body.get("label") if "label" in body else None,
                    aliases=body.get("aliases") if "aliases" in body else None,
                )
                self._json(200, {"ok": True, "item": item})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/transits/delete":
            try:
                item_id = (body.get("id") or "").strip()
                self._json(200, delete_transit(item_id))
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/transits/seed":
            try:
                self._json(200, seed_from_dataset(force=True))
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
                project = body.get("project") or body.get("project_name") or ""
                price = body.get("price") or ""
                queued_at = body.get("queued_at") or ""
                raw = body.get("text") or body.get("urls") or ""
                if source or owner or raw:
                    item = add_job(
                        source_url=source,
                        owner_contact=owner,
                        note=note,
                        raw=raw,
                        project=project,
                        price=price,
                        queued_at=queued_at,
                    )
                    created = [item]
                else:
                    self._json(400, {"error": "ใส่ลิงก์ต้นทางก่อน"})
                    return
                sheet_meta: dict = {}
                try:
                    # Shared SoT so other Fly machines see the new row on next GET sync.
                    sheet_meta = append_wait_post_job(
                        source_url=item.get("source_url") or "",
                        owner_contact=item.get("owner_contact") or "",
                        note=item.get("note") or "",
                        project=item.get("project") or "",
                        price=item.get("price") or "",
                        queued_at=item.get("queued_at") or "",
                    )
                except Exception as sheet_exc:  # noqa: BLE001
                    sheet_meta = {"ok": False, "error": str(sheet_exc)}
                    print(f"[hub] wait-post sheet append failed: {sheet_exc}")
                self._json(
                    200,
                    {
                        "ok": True,
                        "created": created,
                        "stats": queue_stats(),
                        "sheet": sheet_meta,
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/queue/update":
            try:
                item_id = (body.get("id") or "").strip()
                prev = next(
                    (x for x in load_queue() if x.get("id") == item_id),
                    None,
                )
                old_url = ((prev or {}).get("source_url") or "").strip()
                item = update_item(
                    item_id,
                    status=body.get("status"),
                    note=body.get("note"),
                    source_url=body.get("source_url"),
                    owner_contact=body.get("owner_contact"),
                    source_url_2=body.get("source_url_2"),
                    post_url=body.get("post_url"),
                    project=body.get("project") if "project" in body else (
                        body.get("project_name") if "project_name" in body else None
                    ),
                    price=body.get("price") if "price" in body else None,
                    queued_at=body.get("queued_at") if "queued_at" in body else None,
                )
                sheet_meta: dict = {}
                # Push content-field updates to sheet (status-only stays local)
                content_keys = {
                    "note",
                    "source_url",
                    "owner_contact",
                    "source_url_2",
                    "post_url",
                    "project",
                    "project_name",
                    "price",
                    "queued_at",
                }
                if content_keys & set(body.keys()):
                    try:
                        sheet_meta = update_wait_post_job(
                            item.get("source_url") or "",
                            owner_contact=item.get("owner_contact") or "",
                            note=item.get("note") or "",
                            project=item.get("project") or "",
                            price=item.get("price") or "",
                            queued_at=item.get("queued_at") or "",
                            old_source_url=old_url,
                        )
                    except Exception as sheet_exc:  # noqa: BLE001
                        sheet_meta = {"ok": False, "error": str(sheet_exc)}
                        print(f"[hub] wait-post sheet update failed: {sheet_exc}")
                self._json(
                    200,
                    {
                        "ok": True,
                        "item": item,
                        "stats": queue_stats(),
                        "sheet": sheet_meta,
                    },
                )
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/queue/delete":
            try:
                item_id = (body.get("id") or "").strip()
                # Capture URL before delete for sheet cleanup
                prev = next(
                    (x for x in load_queue() if x.get("id") == item_id),
                    None,
                )
                delete_item(item_id)
                sheet_meta: dict = {}
                src_url = ((prev or {}).get("source_url") or "").strip()
                if src_url:
                    try:
                        sheet_meta = delete_wait_post_job(src_url)
                    except Exception as sheet_exc:  # noqa: BLE001
                        sheet_meta = {"ok": False, "error": str(sheet_exc)}
                        print(f"[hub] wait-post sheet delete failed: {sheet_exc}")
                self._json(
                    200,
                    {"ok": True, "stats": queue_stats(), "sheet": sheet_meta},
                )
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

        if path == "/api/tenants/add":
            try:
                item = add_tenant(**{k: v for k, v in body.items() if k != "id"})
                self._json(200, {"ok": True, "item": item, "stats": tenant_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/tenants/update":
            try:
                tid = (body.get("id") or "").strip()
                fields = {k: v for k, v in body.items() if k != "id"}
                item = update_tenant(tid, **fields)
                self._json(200, {"ok": True, "item": item, "stats": tenant_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
            return

        if path == "/api/tenants/delete":
            try:
                delete_tenant((body.get("id") or "").strip())
                self._json(200, {"ok": True, "stats": tenant_stats()})
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
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
            if not _sheet_pull_allowed():
                self._json(
                    403,
                    {
                        "ok": False,
                        "error": (
                            "ปิดการดึงชีททับทรัพย์แล้ว — เว็บ (Hub) เป็นแหล่งความจริง "
                            "ข้อมูลอัปขึ้นชีทอย่างเดียว ไม่ดึงกลับมาทับ"
                        ),
                        "hint": (
                            "ถ้าฉุกเฉินจริงๆ ตั้ง HUB_ALLOW_SHEET_PULL=1 ชั่วคราว "
                            "แล้วรีสตาร์ท — ใช้แล้วควรปิดทันที"
                        ),
                        "sot": "hub_volume",
                    },
                )
                return
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
    # Finish any pending Hub→Sheet push first so pull does not race a half-written edit.
    try:
        _flush_pending_sheet_sync(timeout_sec=90.0)
    except Exception as flush_exc:  # noqa: BLE001
        print(f"[hub] refresh-sheet flush skipped: {flush_exc}")
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

    # Default OFF: Hub volume is SoT; sheet pull must not wipe properties on boot.
    flag = (os.environ.get("HUB_STARTUP_SHEET_SYNC") or "0").strip().lower()
    return flag not in ("0", "false", "no", "off")


def _startup_sheet_sync_worker() -> None:
    """Boot from Hub volume catalog. Optional emergency sheet pull if explicitly enabled."""
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
        try:
            n = len(load_properties())
        except Exception:
            n = 0
        _STARTUP_SHEET_SYNC.update(
            {
                "status": "skipped",
                "properties_total": n,
                "message": (
                    "HUB_STARTUP_SHEET_SYNC disabled — serving Hub volume "
                    f"({n} properties; sheet is export-only)"
                ),
            }
        )
        print(
            f"[hub] startup sheet pull skipped (Hub SoT) — volume has {n} properties"
        )
        return
    if not _sheet_pull_allowed():
        # Even if STARTUP=1, require explicit ALLOW to avoid accidental wipe.
        try:
            n = len(load_properties())
        except Exception:
            n = 0
        _STARTUP_SHEET_SYNC.update(
            {
                "status": "skipped",
                "properties_total": n,
                "message": (
                    "startup pull blocked — set HUB_ALLOW_SHEET_PULL=1 for emergency"
                ),
            }
        )
        print("[hub] startup sheet pull blocked (HUB_ALLOW_SHEET_PULL=0)")
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
            # Focus + customer cases + tenants + location masters:
            # merge local volume with sheet (never wipe Hub-only rows on empty sheet).
            focus_meta: dict = {}
            cust_meta: dict = {}
            tenant_meta: dict = {}
            zone_meta: dict = {}
            transit_meta: dict = {}

            try:
                focus_meta = merge_focus_from_sheet()
                print(
                    f"[hub] focus sheet merge: {focus_meta.get('count')} items "
                    f"(local={focus_meta.get('local_before')} "
                    f"sheet={focus_meta.get('sheet')} "
                    f"merged={focus_meta.get('merged')})"
                )
            except Exception as focus_exc:  # noqa: BLE001
                print(f"[hub] focus sheet merge skipped: {focus_exc}")
            try:
                cust_meta = merge_cases_from_sheet()
                print(
                    f"[hub] customers sheet merge: {cust_meta.get('count')} items "
                    f"(local={cust_meta.get('local_before')} "
                    f"sheet={cust_meta.get('sheet')} "
                    f"merged={cust_meta.get('merged')})"
                )
            except Exception as cust_exc:  # noqa: BLE001
                print(f"[hub] customers sheet merge skipped: {cust_exc}")
            try:
                tenant_meta = merge_tenants_from_sheet()
                print(
                    f"[hub] tenants sheet merge: {tenant_meta.get('count')} items "
                    f"(local={tenant_meta.get('local_before')} "
                    f"sheet={tenant_meta.get('sheet')} "
                    f"merged={tenant_meta.get('merged')})"
                )
            except Exception as tenant_exc:  # noqa: BLE001
                print(f"[hub] tenants sheet merge skipped: {tenant_exc}")
            try:
                zone_meta = replace_zones_from_sheet()
                print(f"[hub] zones sheet pull: {zone_meta.get('count')} items")
            except Exception as zone_exc:  # noqa: BLE001
                print(f"[hub] zones sheet pull skipped: {zone_exc}")
            try:
                transit_meta = replace_transits_from_sheet()
                print(f"[hub] transits sheet pull: {transit_meta.get('count')} items")
            except Exception as transit_exc:  # noqa: BLE001
                print(f"[hub] transits sheet pull skipped: {transit_exc}")
            # Create empty SoT tabs (or seed from local) on first deploy
            try:
                from src.hub.focus_store import list_focus
                from src.hub.customer_store import load_cases
                from src.hub.tenant_store import load_tenants
                from src.hub.location_master_store import (
                    list_transits as _list_transits,
                    list_zones as _list_zones,
                    save_transits,
                    save_zones,
                    seed_from_dataset,
                )
                from src.hub.hub_state_sheet import (
                    push_customers_to_sheet,
                    push_focus_to_sheet,
                    push_tenants_to_sheet,
                    push_transits_to_sheet,
                    push_zones_to_sheet,
                )

                local_focus = list_focus()
                local_cases = load_cases()
                local_tenants = load_tenants()
                # Seed sheet tabs only when pull/merge never ran (no meta).
                if not focus_meta:
                    push_focus_to_sheet(local_focus)
                if not cust_meta:
                    push_customers_to_sheet(local_cases)
                if not tenant_meta:
                    meta = push_tenants_to_sheet(local_tenants)
                    print(
                        f"[hub] tenants sheet seeded/created: "
                        f"{meta.get('sheet_title')} ({meta.get('count')} rows)"
                    )

                # Location masters: seed from dataset if empty, then push sheet
                seed_from_dataset(force=False)
                local_zones = _list_zones()
                local_transits = _list_transits()
                if not zone_meta:
                    meta = push_zones_to_sheet(local_zones)
                    print(
                        f"[hub] zones sheet seeded/created: "
                        f"{meta.get('sheet_title')} ({meta.get('count')} rows)"
                    )
                elif zone_meta.get("count", -1) == 0 and local_zones:
                    save_zones(local_zones, sync_sheet=True)
                    print("[hub] zones sheet seeded from local volume")
                if not transit_meta:
                    meta = push_transits_to_sheet(local_transits)
                    print(
                        f"[hub] transits sheet seeded/created: "
                        f"{meta.get('sheet_title')} ({meta.get('count')} rows)"
                    )
                elif transit_meta.get("count", -1) == 0 and local_transits:
                    save_transits(local_transits, sync_sheet=True)
                    print("[hub] transits sheet seeded from local volume")
            except Exception as seed_exc:  # noqa: BLE001
                print(f"[hub] focus/customers/tenants/zones sheet seed skipped: {seed_exc}")
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

    try:
        masters = ensure_masters_ready()
        print(
            f"[hub] boot: location masters "
            f"zones={masters.get('zones')} transits={masters.get('transits')} "
            f"seeded={masters.get('seeded')}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[hub] boot location masters failed: {exc}")

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

    # Background: serve Hub volume catalog (sheet pull is off by default — Hub is SoT).
    # Server listens first so health checks pass during any optional sync window.
    threading.Thread(target=_startup_sheet_sync_worker, daemon=True).start()
    threading.Thread(
        target=_periodic_sheet_export_worker,
        daemon=True,
        name="periodic-sheet-export",
    ).start()
    threading.Thread(target=_warm_recent_thumbs, daemon=True).start()

    print("=== Property Hub Server (Phase 2) ===")
    print(f"Listening: http://{host}:{port}/")
    print("API:  scrape/parse/generate · projects · queue · preview-thumb")
    print(f"Co-Agent: http://{host}:{port}/co/")
    print("Ctrl+C to stop")

    _shutting_down = {"done": False}

    def _request_shutdown(signum=None, frame=None) -> None:  # noqa: ARG001
        if _shutting_down["done"]:
            return
        _shutting_down["done"] = True
        print("[hub] shutdown signal — flushing sheet sync then stopping…")

        def _stop() -> None:
            try:
                meta = _flush_pending_sheet_sync(timeout_sec=75.0)
                print(f"[hub] shutdown flush: {meta}")
            except Exception as flush_exc:  # noqa: BLE001
                print(f"[hub] shutdown flush failed: {flush_exc}")
            try:
                server.shutdown()
            except Exception:
                pass

        threading.Thread(target=_stop, daemon=True, name="hub-shutdown").start()

    try:
        import signal

        signal.signal(signal.SIGTERM, _request_shutdown)
        signal.signal(signal.SIGINT, _request_shutdown)
    except Exception as sig_exc:  # noqa: BLE001
        print(f"[hub] signal handlers skipped: {sig_exc}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        if not _shutting_down["done"]:
            _shutting_down["done"] = True
            try:
                _flush_pending_sheet_sync(timeout_sec=30.0)
            except Exception:
                pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
