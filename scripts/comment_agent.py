#!/usr/bin/env python3
"""
Facebook comment agent — runs on the always-on PC (Windows/Mac).

Talks to Hub for credentials + queue status. Opens a real browser window
when Hub requests Facebook login (so 2FA can be completed on this machine).

Usage:
    set HUB_URL=http://127.0.0.1:8765
    set COMMENT_AGENT_TOKEN=...   # copy from Hub → คอมเมนต์กลุ่ม
    python scripts/comment_agent.py

    python scripts/comment_agent.py --hub http://127.0.0.1:8765 --token YOUR_TOKEN
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import settings  # noqa: E402
from src.facebook.auth import FacebookAuth  # noqa: E402
from src.hub.fb_agent_store import get_credentials_for_agent  # noqa: E402

# Import run_once from sibling script without treating scripts/ as a package
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "comment_group_posts",
    BASE_DIR / "scripts" / "comment_group_posts.py",
)
_cgp = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_cgp)
run_once = _cgp.run_once
setup_logging = _cgp.setup_logging


def _hub_url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def _request(
    method: str,
    url: str,
    *,
    token: str,
    body: dict | None = None,
    timeout: float = 30,
) -> dict:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Agent-Token": token,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def heartbeat(hub: str, token: str, **payload) -> dict:
    payload.setdefault("hostname", socket.gethostname())
    return _request("POST", _hub_url(hub, "/api/fb-agent/heartbeat"), token=token, body=payload)


def pull(hub: str, token: str) -> dict:
    return _request("GET", _hub_url(hub, "/api/fb-agent/pull"), token=token)


def sync_chrome_profiles(hub: str, token: str) -> dict:
    """Upload local Chrome profile list so Hub can show a picker."""
    try:
        from src.facebook.chrome_profiles import list_chrome_profiles

        profiles = list_chrome_profiles()
    except Exception as exc:  # noqa: BLE001
        logger.warning("list chrome profiles failed: {}", exc)
        return {"ok": False, "error": str(exc), "count": 0}
    try:
        data = _request(
            "POST",
            _hub_url(hub, "/api/fb-agent/chrome-profiles"),
            token=token,
            body={"profiles": profiles, "agent_id": _agent_id},
        )
        return {"ok": True, "count": len(profiles), **(data if isinstance(data, dict) else {})}
    except Exception as exc:  # noqa: BLE001
        logger.warning("upload chrome profiles failed: {}", exc)
        return {"ok": False, "error": str(exc), "count": len(profiles)}


def sync_page_thumbs(hub: str, token: str, *, limit: int = 12) -> dict:
    """Fetch Facebook page thumbs from this PC (home IP) and upload to Hub.

    Fly/datacenter IPs get Facebook login walls; Mac/Windows Agent usually can
    read og:image and push bytes into Hub thumb_cache.
    """
    import base64

    from src.hub.scraper import fetch_image_bytes, fetch_preview_image

    try:
        data = _request("GET", _hub_url(hub, f"/api/fb-agent/thumb-due?limit={int(limit)}"), token=token)
    except Exception as exc:  # noqa: BLE001
        logger.warning("thumb-due failed: {}", exc)
        return {"ok": False, "done": 0, "failed": 0, "error": str(exc)}

    items = list(data.get("items") or [])
    if not items:
        return {"ok": True, "done": 0, "failed": 0, "due": 0}

    done = 0
    failed = 0
    for it in items:
        page_url = str((it or {}).get("url") or "").strip()
        code = str((it or {}).get("code") or "")
        if not page_url.startswith("http"):
            continue
        try:
            image_url, warnings = fetch_preview_image(page_url)
            if not image_url:
                failed += 1
                logger.info("thumb miss {} · {}", code or "—", "; ".join(warnings)[:120])
                continue
            blob, ctype = fetch_image_bytes(image_url)
            if not blob or len(blob) < 500:
                failed += 1
                logger.info("thumb download empty {} · {}", code or "—", image_url[:80])
                continue
            _request(
                "POST",
                _hub_url(hub, "/api/fb-agent/thumb-upload"),
                token=token,
                body={
                    "url": page_url,
                    "content_type": ctype or "image/jpeg",
                    "image_base64": base64.b64encode(blob).decode("ascii"),
                },
            )
            done += 1
            logger.success("thumb uploaded {} · {} bytes", code or page_url[:40], len(blob))
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.warning("thumb sync failed {}: {}", code or page_url[:40], exc)
        time.sleep(0.6)
    return {"ok": True, "done": done, "failed": failed, "due": len(items)}


def _local_credentials_fallback() -> tuple[str, str]:
    """When agent runs against the same Hub data dir (local)."""
    try:
        creds = get_credentials_for_agent()
        return creds.get("email") or "", creds.get("password") or ""
    except Exception:  # noqa: BLE001
        return settings.FACEBOOK_EMAIL or "", settings.FACEBOOK_PASSWORD or ""


# Keep one visible browser open so the user can see login + commenting.
_alive_auth: FacebookAuth | None = None
_agent_id: str = (os.getenv("COMMENT_AGENT_ID") or "owner").strip() or "owner"


def _session_paths(agent_id: str) -> tuple[Path, Path]:
    aid = (agent_id or "owner").strip() or "owner"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in aid)
    data_dir = settings.BASE_DIR / "cookies" / f"facebook_session_{safe}"
    cookies = settings.BASE_DIR / "cookies" / f"facebook_cookies_{safe}.json"
    return data_dir, cookies


def _make_auth(email: str, password: str, *, headless: bool) -> FacebookAuth:
    data_dir, cookies = _session_paths(_agent_id)
    return FacebookAuth(
        email=email or None,
        password=password or None,
        user_data_dir=data_dir,
        cookies_path=cookies,
        headless=headless,
    )


def _close_alive_auth() -> None:
    global _alive_auth
    if _alive_auth is not None:
        try:
            _alive_auth.close()
        except Exception:  # noqa: BLE001
            pass
        _alive_auth = None


def do_login(hub: str, token: str, email: str, password: str) -> bool:
    global _alive_auth
    from src.facebook.auth import FacebookAuth
    from src.facebook.ensure_runtime import ensure_playwright_chromium

    def progress(msg: str) -> None:
        print(msg, flush=True)
        try:
            heartbeat(hub, token, status="logging_in", message=msg)
        except Exception:  # noqa: BLE001
            pass

    # Always show a real window for Hub login button
    os.environ["HEADLESS"] = "false"
    settings.HEADLESS = False

    progress(f"ได้รับคำสั่งล็อกอิน ({_agent_id}) — กำลังเปิดเบราว์เซอร์…")

    # Prefer real Chrome (CDP) — skip Playwright Chromium download when available
    using_cdp = FacebookAuth.cdp_available()
    if not using_cdp:
        progress("ยังไม่มี Chrome โหมด Agent — จะเปิด Google Chrome / Chromium ขึ้นมาใหม่ให้เห็น")
        try:
            ensure_playwright_chromium(on_progress=progress)
        except Exception as exc:  # noqa: BLE001
            heartbeat(
                hub,
                token,
                status="error",
                message=(
                    f"เตรียมเบราว์เซอร์ไม่สำเร็จ: {exc} · "
                    "ลองดับเบิลคลิก「เปิดChromeจริงสำหรับAgent」ก่อน แล้วกดล็อกอินอีกครั้ง"
                ),
                fb_logged_in=False,
                clear_login_request=True,
            )
            logger.error("ensure browser failed: {}", exc)
            return False
    else:
        progress("พบ Google Chrome โหมด Agent — จะเปิดแท็บเฟสใหม่ให้อยู่ด้านหน้า")

    _close_alive_auth()
    if using_cdp:
        progress(
            f"กำลังเชื่อม Chrome จริง ({_agent_id}) — สลับบัญชีจากไอคอนโปรไฟล์ได้เลย"
        )
    else:
        progress(
            f"กำลังเปิดหน้าต่าง Facebook ({_agent_id}) — "
            "ถ้าไม่เห็นหน้าต่าง ให้ดูแถบงานด้านล่าง (Chrome/Chromium)"
        )
    auth = _make_auth(email, password, headless=False)
    # Without CDP, force system Chrome channel so a visible window always appears on Windows
    if not using_cdp:
        auth.browser_mode = "chrome"
    try:
        auth.login(wait_manual_sec=600, on_status=progress, force_manual=True)
        _alive_auth = auth
        heartbeat(
            hub,
            token,
            status="online",
            message=f"ล็อกอินสำเร็จ ({_agent_id}) · Chrome เปิดค้างไว้ให้ดู — ระบบจะคอมเมนต์อัตโนมัติต่อ",
            fb_logged_in=True,
            clear_login_request=True,
        )
        logger.success("Facebook login OK — browser kept open · agent={}", _agent_id)
        print("")
        print("===== ล็อกอินสำเร็จ =====")
        print(f"Agent: {_agent_id}")
        print("หน้าต่าง Chrome ยังเปิดอยู่ — ดูได้ว่าเข้าบัญชีถูก")
        print("ระบบจะคอมเมนต์คิวของ Agent นี้ให้อัตโนมัติ (อย่าปิด Terminal)")
        print("")
        return True
    except Exception as exc:  # noqa: BLE001
        try:
            auth.close()
        except Exception:  # noqa: BLE001
            pass
        _alive_auth = None
        heartbeat(
            hub,
            token,
            status="error",
            message=f"ล็อกอินไม่สำเร็จ: {exc}",
            fb_logged_in=False,
            clear_login_request=True,
        )
        logger.error("Login failed: {}", exc)
        print("")
        print("===== ล็อกอินเฟสยังไม่สำเร็จ =====")
        print(str(exc))
        print("ดูหน้าต่าง Chrome ที่เปิดไว้ — ล็อกอินให้ครบ แล้วกดปุ่มล็อกอินใน Hub อีกครั้ง")
        print("")
        return False


def check_session(hub: str, token: str, email: str, password: str) -> bool:
    global _alive_auth
    if _alive_auth is not None and _alive_auth._page is not None:  # noqa: SLF001
        try:
            ok = _alive_auth._is_logged_in(_alive_auth._page, navigate=False)  # noqa: SLF001
            if not ok:
                ok = _alive_auth._is_logged_in(_alive_auth._page, navigate=True)  # noqa: SLF001
            heartbeat(
                hub,
                token,
                status="online",
                message=(
                    f"เซสชันเฟสพร้อม ({_agent_id}) · Chrome เปิดค้างให้ดูอยู่"
                    if ok
                    else "ยังไม่ได้ล็อกอินเฟส — กดปุ่มล็อกอินใน Hub"
                ),
                fb_logged_in=ok,
            )
            return ok
        except Exception as exc:  # noqa: BLE001
            logger.warning("alive session check failed: {}", exc)

    auth = _make_auth(email, password, headless=True)
    try:
        page = auth.start_browser()
        ok = auth._is_logged_in(page)  # noqa: SLF001
        heartbeat(
            hub,
            token,
            status="online",
            message=(
                f"เซสชันเฟสพร้อม ({_agent_id})"
                if ok
                else "ยังไม่ได้ล็อกอินเฟส — กดปุ่มล็อกอินใน Hub"
            ),
            fb_logged_in=ok,
        )
        return ok
    except Exception as exc:  # noqa: BLE001
        heartbeat(hub, token, status="error", message=f"เช็คเซสชันไม่ได้: {exc}", fb_logged_in=False)
        return False
    finally:
        auth.close()


def run_comments(hub: str, token: str, email: str, password: str) -> None:
    global _alive_auth
    if email:
        os.environ["FACEBOOK_EMAIL"] = email
    if password:
        os.environ["FACEBOOK_PASSWORD"] = password
    settings.FACEBOOK_EMAIL = email or settings.FACEBOOK_EMAIL
    settings.FACEBOOK_PASSWORD = password or settings.FACEBOOK_PASSWORD
    os.environ["COMMENT_AGENT_ID"] = _agent_id
    os.environ["HUB_URL"] = (hub or "").rstrip("/")
    os.environ["COMMENT_AGENT_TOKEN"] = token or ""

    def progress(msg: str) -> None:
        print(msg, flush=True)
        try:
            heartbeat(hub, token, status="working", message=msg, fb_logged_in=True)
        except Exception:  # noqa: BLE001
            pass

    heartbeat(
        hub,
        token,
        status="working",
        message=f"กำลังคอมเมนต์คิว ({_agent_id}) — ดูหน้าต่าง Chrome ได้",
    )
    try:
        auth = _alive_auth
        if auth is None:
            auth = _make_auth(email, password, headless=False)
        summary = run_once(auth=auth, keep_open=True, headless=False, on_status=progress)
        if summary.get("auth") is not None:
            _alive_auth = summary["auth"]
        elif auth is not None:
            _alive_auth = auth
        done = int(summary.get("done") or 0)
        failed = int(summary.get("failed") or 0)
        msg = f"รอบล่าสุด ({_agent_id}): สำเร็จ {done} · ล้มเหลว {failed}"
        if summary.get("skipped"):
            msg = f"ข้าม ({summary.get('skipped')})"
        elif summary.get("due") == 0 and done == 0 and failed == 0:
            msg = f"ยังไม่มีคิวถึงเวลา ({_agent_id}) · Chrome เปิดค้างได้"
        heartbeat(
            hub,
            token,
            status="online",
            message=msg,
            fb_logged_in=True,
            last_run={
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "done": done,
                "failed": failed,
                "message": msg,
            },
        )
    except Exception as exc:  # noqa: BLE001
        heartbeat(
            hub,
            token,
            status="error",
            message=f"รันคอมเมนต์ล้มเหลว: {exc}",
            last_run={
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "done": 0,
                "failed": 1,
                "message": str(exc),
            },
        )
        logger.exception("comment run failed")


def _find_account(accounts: list, job: dict) -> dict | None:
    aid = str(job.get("fb_account_id") or "").strip()
    if not aid:
        return None
    for a in accounts or []:
        if not isinstance(a, dict):
            continue
        if str(a.get("id") or "") == aid:
            return a
        if str(a.get("switch_name") or "") == aid or str(a.get("label") or "") == aid:
            return a
    return None


def sync_joined_groups(hub: str, token: str, email: str, password: str, *, account_id: str = "") -> dict:
    """Scrape facebook.com/groups/joins and merge into Hub group book."""
    global _alive_auth
    from src.facebook import humanize

    if email:
        os.environ["FACEBOOK_EMAIL"] = email
    if password:
        os.environ["FACEBOOK_PASSWORD"] = password

    auth = _alive_auth
    if auth is None:
        auth = _make_auth(email, password, headless=False)
        try:
            auth.login(wait_manual_sec=90, force_manual=False)
            _alive_auth = auth
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
    page = getattr(auth, "_page", None)
    if page is None:
        return {"ok": False, "error": "no browser page"}

    try:
        page.goto("https://www.facebook.com/groups/joins/?nav_source=tab", wait_until="domcontentloaded", timeout=60_000)
        humanize.pause(2.0, 4.0)
        for _ in range(6):
            humanize.soft_scroll(page, times=1)
            humanize.pause(0.6, 1.2)
        links = page.evaluate(
            """() => {
              const out = [];
              const seen = new Set();
              for (const a of document.querySelectorAll('a[href*="/groups/"]')) {
                let href = a.href || '';
                if (!href.includes('/groups/')) continue;
                href = href.split('?')[0].replace(/\\/$/, '');
                if (/\\/groups\\/(joins|feed|create|discover)/.test(href)) continue;
                const m = href.match(/\\/groups\\/([^\\/]+)/);
                if (!m) continue;
                const url = 'https://www.facebook.com/groups/' + m[1];
                if (seen.has(url)) continue;
                seen.add(url);
                const name = (a.innerText || a.getAttribute('aria-label') || '').trim().split('\\n')[0].slice(0, 120);
                out.push({ url, name, membership: 'joined' });
              }
              return out.slice(0, 400);
            }"""
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}

    items = links if isinstance(links, list) else []
    try:
        result = _request(
            "POST",
            _hub_url(hub, "/api/groups/sync-joins"),
            token=token,
            body={
                "groups": items,
                "account_id": account_id or "default",
                "account_label": account_id or "default",
            },
        )
        return {"ok": True, "scraped": len(items), **(result if isinstance(result, dict) else {})}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "scraped": len(items)}


def run_publish(hub: str, token: str, email: str, password: str, *, max_posts: int = 1) -> dict:
    """Pull due publish jobs → switch FB account → post images+caption → report."""
    global _alive_auth
    from src.facebook.account_switcher import FacebookAccountSwitcher
    from src.facebook.poster import FacebookGroupPoster
    from src.hub import publish_policy as policy

    if email:
        os.environ["FACEBOOK_EMAIL"] = email
    if password:
        os.environ["FACEBOOK_PASSWORD"] = password

    def progress(msg: str) -> None:
        print(msg, flush=True)
        try:
            heartbeat(hub, token, status="working", message=msg, fb_logged_in=True)
        except Exception:  # noqa: BLE001
            pass

    try:
        data = _request(
            "GET",
            _hub_url(hub, f"/api/fb-agent/publish-due?limit={max(1, int(max_posts))}"),
            token=token,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("publish-due failed: {}", exc)
        return {"ok": False, "done": 0, "failed": 0, "error": str(exc)}

    if data.get("work_paused"):
        progress("⏸ หยุดงานฉุกเฉิน — ข้ามคิวโพส")
        return {"ok": True, "done": 0, "failed": 0, "paused": True}

    due = data.get("due") or []
    accounts = data.get("fb_accounts") or []
    if not due:
        return {"ok": True, "done": 0, "failed": 0, "due": 0}

    auth = _alive_auth
    if auth is None:
        auth = _make_auth(email, password, headless=False)
        try:
            auth.login(wait_manual_sec=120, force_manual=False)
            _alive_auth = auth
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "done": 0, "failed": 1, "error": str(exc)}

    page = getattr(auth, "_page", None)
    if page is None:
        try:
            page = auth.login(wait_manual_sec=60, force_manual=False)
            _alive_auth = auth
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "done": 0, "failed": 1, "error": str(exc)}
    if page is None:
        return {"ok": False, "done": 0, "failed": 1, "error": "no browser page"}

    switcher = FacebookAccountSwitcher(page)
    poster = FacebookGroupPoster(page)
    done = 0
    failed = 0
    last_account: dict | None = None

    for job in due[: max(1, int(max_posts))]:
        job_id = str(job.get("id") or "")
        code = str(job.get("property_code") or "")
        group_url = str(job.get("group_url") or "")
        caption = str(job.get("caption") or "")
        images = job.get("image_urls") or []
        acc = _find_account(accounts, job)
        switch_name = ""
        if acc:
            switch_name = str(acc.get("switch_name") or acc.get("label") or "").strip()
            last_account = acc

        progress(f"โพส {code} → กลุ่ม · บัญชี {switch_name or job.get('fb_account_id') or 'ปัจจุบัน'}")

        if switch_name:
            sw = switcher.switch_to(switch_name)
            if not sw.get("ok"):
                detail = sw.get("detail") or sw.get("error") or "สลับบัญชีไม่สำเร็จ"
                progress(f"⚠ {detail}")
                try:
                    _request(
                        "POST",
                        _hub_url(hub, "/api/fb-agent/publish-result"),
                        token=token,
                        body={
                            "id": job_id,
                            "ok": False,
                            "action": "switch_failed",
                            "error": detail,
                            "detail": detail,
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
                failed += 1
                continue

        try:
            # Expand relative Hub upload URLs to absolute for local download
            hub_base = hub.rstrip("/")
            resolved_images = []
            for u in (images if isinstance(images, list) else []):
                s = str(u or "").strip()
                if not s:
                    continue
                if s.startswith("/api/publish-uploads/"):
                    s = hub_base + s
                resolved_images.append(s)
            outcome = poster.post_to_group(
                caption=caption,
                image_urls=resolved_images,
                property_id=code or "property",
                group_url=group_url,
            )
        except Exception as exc:  # noqa: BLE001
            outcome = {
                "ok": False,
                "error": str(exc),
                "action": "exception",
                "detail": str(exc),
            }

        ok = bool(outcome.get("ok"))
        try:
            _request(
                "POST",
                _hub_url(hub, "/api/fb-agent/publish-result"),
                token=token,
                body={
                    "id": job_id,
                    "ok": ok,
                    "permalink": outcome.get("permalink") or "",
                    "action": outcome.get("action") or ("posted" if ok else "failed"),
                    "error": outcome.get("error") or "",
                    "detail": outcome.get("detail") or "",
                    "join_status": outcome.get("join_status") or "",
                    "needs_manual_join": bool(outcome.get("needs_manual_join")),
                    "comment_immediately": ok,
                },
            )
        except Exception as report_exc:  # noqa: BLE001
            logger.warning("publish-result report failed: {}", report_exc)

        if ok:
            done += 1
            progress(f"✓ โพสสำเร็จ {code} · {outcome.get('permalink') or '(รอ permalink)'}")
        else:
            failed += 1
            detail = outcome.get("detail") or outcome.get("error") or ""
            if outcome.get("action") == "awaiting_join" or outcome.get("needs_manual_join"):
                progress(f"⚠ รอเข้ากลุ่ม: {detail}")
            else:
                progress(f"✗ โพสไม่สำเร็จ: {detail}")
            if outcome.get("action") == "restricted":
                break

        # Anti-ban delay between posts (even if only 1, leave a short settle)
        delay = policy.random_post_delay_sec(last_account)
        if len(due) > 1 and done + failed < len(due[:max_posts]):
            progress(f"พัก {int(delay)} วินาที ก่อนโพสถัดไป…")
            time.sleep(delay)
        else:
            time.sleep(min(15.0, delay * 0.05))

    msg = f"โพสรอบนี้ ({_agent_id}): สำเร็จ {done} · ล้มเหลว {failed}"
    heartbeat(
        hub,
        token,
        status="online",
        message=msg,
        fb_logged_in=True,
        last_run={
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "done": done,
            "failed": failed,
            "message": msg,
            "kind": "publish",
        },
    )
    return {"ok": True, "done": done, "failed": failed}


def loop(hub: str, token: str, *, poll_sec: float, comment_every_sec: float) -> None:
    host = socket.gethostname()
    logger.info("Comment agent started · hub={} · host={}", hub, host)
    last_comment_at = 0.0
    last_publish_at = 0.0
    last_groups_sync_at = 0.0
    last_session_check = 0.0
    last_thumb_at = 0.0
    last_profiles_at = 0.0
    logged_in = False
    thumb_every_sec = float(os.getenv("COMMENT_AGENT_THUMB_EVERY_SEC", "90"))
    profiles_every_sec = float(os.getenv("COMMENT_AGENT_PROFILES_EVERY_SEC", "300"))
    publish_every_sec = float(os.getenv("COMMENT_AGENT_PUBLISH_EVERY_SEC", "180"))

    # First tick: publish Chrome profiles for Hub picker
    try:
        summary = sync_chrome_profiles(hub, token)
        if summary.get("ok"):
            logger.info("synced {} Chrome profiles to Hub", summary.get("count") or 0)
            last_profiles_at = time.time()
    except Exception as exc:  # noqa: BLE001
        logger.warning("initial chrome profile sync failed: {}", exc)

    while True:
        try:
            data = pull(hub, token)
            email = (data.get("email") or "").strip()
            password = (data.get("password") or "").strip()
            if not email or not password:
                le, lp = _local_credentials_fallback()
                email = email or le
                password = password or lp

            selected_profile = str(data.get("chrome_profile_dir") or "").strip()
            if selected_profile:
                os.environ["FB_CHROME_PROFILE_DIRECTORY"] = selected_profile
            selected_name = str(data.get("chrome_profile_name") or "").strip()
            if selected_name:
                os.environ["FB_CHROME_PROFILE_NAME"] = selected_name

            now = time.time()
            if now - last_profiles_at >= profiles_every_sec:
                try:
                    sync_chrome_profiles(hub, token)
                except Exception as pe:  # noqa: BLE001
                    logger.warning("chrome profile sync tick error: {}", pe)
                last_profiles_at = time.time()

            # Always try page thumbs from this PC — does not need FB login
            now = time.time()
            if now - last_thumb_at >= thumb_every_sec:
                try:
                    summary = sync_page_thumbs(hub, token, limit=10)
                    if summary.get("done") or summary.get("failed"):
                        heartbeat(
                            hub,
                            token,
                            status="online",
                            message=(
                                f"ดึงรูปหน้าหลัก: สำเร็จ {summary.get('done') or 0}"
                                f" · ไม่สำเร็จ {summary.get('failed') or 0}"
                            ),
                            hostname=host,
                            fb_logged_in=logged_in,
                        )
                except Exception as thumb_exc:  # noqa: BLE001
                    logger.warning("thumb sync tick error: {}", thumb_exc)
                last_thumb_at = time.time()

            if data.get("login_requested"):
                if data.get("work_paused"):
                    heartbeat(
                        hub,
                        token,
                        status="paused",
                        message="⏸ หยุดงานฉุกเฉิน — ไม่ล็อกอิน/โพส/คอมเมนต์จนกว่าจะกดทำงานต่อใน Hub",
                        hostname=host,
                        fb_logged_in=logged_in,
                        clear_login_request=True,
                    )
                else:
                    logged_in = do_login(hub, token, email, password)
                    last_session_check = time.time()
                    if logged_in:
                        run_publish(hub, token, email, password, max_posts=1)
                        last_publish_at = time.time()
                        run_comments(hub, token, email, password)
                        last_comment_at = time.time()
            elif data.get("work_paused"):
                logged_in = bool(data.get("fb_logged_in")) or logged_in
                heartbeat(
                    hub,
                    token,
                    status="paused",
                    message="⏸ หยุดงานฉุกเฉิน — กด「ทำงานต่อ」ใน Hub เมื่อพร้อม (ครอบคลุมโพส+คอมเมนต์)",
                    hostname=host,
                    fb_logged_in=logged_in,
                )
            else:
                now = time.time()
                if now - last_session_check > 300:
                    logged_in = check_session(hub, token, email, password)
                    last_session_check = now
                else:
                    logged_in = bool(data.get("fb_logged_in")) or logged_in
                    heartbeat(
                        hub,
                        token,
                        status="online",
                        message=(
                            "Agent พร้อม · รอคิวโพส/คอมเมนต์"
                            if logged_in
                            else "Agent ออนไลน์ · ยังไม่ล็อกอินเฟส — กดปุ่มล็อกอินใน Hub"
                        ),
                        hostname=host,
                        fb_logged_in=logged_in,
                    )

                if logged_in and (now - last_publish_at >= publish_every_sec):
                    run_publish(hub, token, email, password, max_posts=1)
                    last_publish_at = time.time()
                if logged_in and (now - last_groups_sync_at >= 6 * 3600):
                    try:
                        sync_joined_groups(hub, token, email, password)
                    except Exception as sync_exc:  # noqa: BLE001
                        logger.warning("groups sync failed: {}", sync_exc)
                    last_groups_sync_at = time.time()

                if logged_in and (now - last_comment_at >= comment_every_sec):
                    run_comments(hub, token, email, password)
                    last_comment_at = time.time()

        except Exception as exc:  # noqa: BLE001
            logger.warning("agent tick error: {}", exc)
            try:
                heartbeat(hub, token, status="error", message=str(exc), hostname=host)
            except Exception:  # noqa: BLE001
                pass

        time.sleep(max(5.0, poll_sec))


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Hub Facebook comment agent")
    parser.add_argument("--hub", default=os.getenv("HUB_URL", "http://127.0.0.1:8765"))
    parser.add_argument("--token", default=os.getenv("COMMENT_AGENT_TOKEN", ""))
    parser.add_argument("--poll", type=float, default=float(os.getenv("COMMENT_AGENT_POLL_SEC", "20")))
    parser.add_argument(
        "--comment-every",
        type=float,
        default=float(os.getenv("COMMENT_AGENT_COMMENT_EVERY_SEC", "300")),
        help="Seconds between comment batch attempts (default 5 min)",
    )
    parser.add_argument("--login-once", action="store_true", help="Login once then exit")
    parser.add_argument("--once", action="store_true", help="One comment batch then exit")
    parser.add_argument(
        "--agent",
        "--agent-id",
        dest="agent_id",
        default=os.getenv("COMMENT_AGENT_ID", "owner"),
        help="Agent slot id: owner (Mac) or admin (Windows)",
    )
    args = parser.parse_args()

    global _agent_id
    _agent_id = (args.agent_id or "owner").strip() or "owner"
    os.environ["COMMENT_AGENT_ID"] = _agent_id

    token = (args.token or "").strip()
    if not token:
        # Local Hub: read token from store file
        try:
            from src.hub.fb_agent_store import load as load_agent

            token = str(load_agent().get("agent_token") or "")
        except Exception:  # noqa: BLE001
            token = ""
    if not token:
        logger.error("ต้องมี COMMENT_AGENT_TOKEN (คัดลอกจาก Hub แท็บคอมเมนต์กลุ่ม)")
        sys.exit(1)

    hub = args.hub.strip()

    # Self-heal: prepare Chromium so login/comment works without manual setup
    from src.facebook.ensure_runtime import ensure_playwright_chromium

    def _boot_progress(msg: str) -> None:
        print(msg, flush=True)
        try:
            heartbeat(hub, token, status="online", message=msg)
        except Exception:  # noqa: BLE001
            pass

    try:
        ensure_playwright_chromium(on_progress=_boot_progress)
    except Exception as exc:  # noqa: BLE001
        logger.error("เตรียมระบบไม่สำเร็จ: {}", exc)
        try:
            heartbeat(hub, token, status="error", message=f"เตรียมระบบไม่สำเร็จ: {exc}")
        except Exception:  # noqa: BLE001
            pass
        print("")
        print("===== เกิดข้อผิดพลาด =====")
        print(str(exc))
        print("ให้หัวหน้าทีมดูข้อความนี้ หรือรัน: python3 -m playwright install chromium")
        print("")
        try:
            input("กด Enter เพื่อปิด...")
        except EOFError:
            pass
        sys.exit(1)

    if args.login_once:
        data = pull(hub, token)
        email = (data.get("email") or "").strip()
        password = (data.get("password") or "").strip()
        if not email:
            email, password = _local_credentials_fallback()
        ok = do_login(hub, token, email, password)
        sys.exit(0 if ok else 1)

    if args.once:
        data = pull(hub, token)
        email = (data.get("email") or "").strip()
        password = (data.get("password") or "").strip()
        if not email:
            email, password = _local_credentials_fallback()
        run_comments(hub, token, email, password)
        return

    loop(hub, token, poll_sec=args.poll, comment_every_sec=args.comment_every)


if __name__ == "__main__":
    main()
