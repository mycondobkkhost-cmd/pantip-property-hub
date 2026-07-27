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


def _local_credentials_fallback() -> tuple[str, str]:
    """When agent runs against the same Hub data dir (local)."""
    try:
        creds = get_credentials_for_agent()
        return creds.get("email") or "", creds.get("password") or ""
    except Exception:  # noqa: BLE001
        return settings.FACEBOOK_EMAIL or "", settings.FACEBOOK_PASSWORD or ""


def do_login(hub: str, token: str, email: str, password: str) -> bool:
    from src.facebook.ensure_runtime import ensure_playwright_chromium

    def progress(msg: str) -> None:
        print(msg, flush=True)
        try:
            heartbeat(hub, token, status="logging_in", message=msg)
        except Exception:  # noqa: BLE001
            pass

    try:
        ensure_playwright_chromium(on_progress=progress)
    except Exception as exc:  # noqa: BLE001
        heartbeat(
            hub,
            token,
            status="error",
            message=f"เตรียมเบราว์เซอร์ไม่สำเร็จ: {exc}",
            fb_logged_in=False,
            clear_login_request=True,
        )
        logger.error("ensure browser failed: {}", exc)
        return False

    progress("กำลังเปิดหน้าต่าง Facebook — อย่าปิด Chrome ที่เด้งขึ้น")
    auth = FacebookAuth(email=email or None, password=password or None, headless=False)
    try:
        auth.login(wait_manual_sec=600, on_status=progress)
        heartbeat(
            hub,
            token,
            status="online",
            message="ล็อกอินเฟสสำเร็จ",
            fb_logged_in=True,
            clear_login_request=True,
        )
        logger.success("Facebook login OK")
        return True
    except Exception as exc:  # noqa: BLE001
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
        print("ดูหน้าต่าง Chrome ที่เปิดไว้ — ใส่รหัสยืนยันให้ครบ แล้วกดปุ่มล็อกอินใน Hub อีกครั้ง")
        print("")
        return False
    finally:
        auth.close()


def check_session(hub: str, token: str, email: str, password: str) -> bool:
    auth = FacebookAuth(email=email or None, password=password or None, headless=True)
    try:
        page = auth.start_browser()
        ok = auth._is_logged_in(page)  # noqa: SLF001
        heartbeat(
            hub,
            token,
            status="online",
            message="เซสชันเฟสพร้อม" if ok else "ยังไม่ได้ล็อกอินเฟส — กดปุ่มล็อกอินใน Hub",
            fb_logged_in=ok,
        )
        return ok
    except Exception as exc:  # noqa: BLE001
        heartbeat(hub, token, status="error", message=f"เช็คเซสชันไม่ได้: {exc}", fb_logged_in=False)
        return False
    finally:
        auth.close()


def run_comments(hub: str, token: str, email: str, password: str) -> None:
    # Prefer Hub-stored credentials for this process
    if email:
        os.environ["FACEBOOK_EMAIL"] = email
    if password:
        os.environ["FACEBOOK_PASSWORD"] = password
    settings.FACEBOOK_EMAIL = email or settings.FACEBOOK_EMAIL
    settings.FACEBOOK_PASSWORD = password or settings.FACEBOOK_PASSWORD

    heartbeat(hub, token, status="working", message="กำลังคอมเมนต์คิว…")
    try:
        summary = run_once()
        done = int(summary.get("done") or 0)
        failed = int(summary.get("failed") or 0)
        msg = f"รอบล่าสุด: สำเร็จ {done} · ล้มเหลว {failed}"
        if summary.get("skipped"):
            msg = f"ข้าม ({summary.get('skipped')})"
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


def loop(hub: str, token: str, *, poll_sec: float, comment_every_sec: float) -> None:
    host = socket.gethostname()
    logger.info("Comment agent started · hub={} · host={}", hub, host)
    last_comment_at = 0.0
    last_session_check = 0.0
    logged_in = False

    while True:
        try:
            data = pull(hub, token)
            email = (data.get("email") or "").strip()
            password = (data.get("password") or "").strip()
            if not email or not password:
                le, lp = _local_credentials_fallback()
                email = email or le
                password = password or lp

            if data.get("login_requested"):
                logged_in = do_login(hub, token, email, password)
                last_session_check = time.time()
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
                            "Agent พร้อม · รอคิวคอมเมนต์"
                            if logged_in
                            else "Agent ออนไลน์ · ยังไม่ล็อกอินเฟส — กดปุ่มล็อกอินใน Hub"
                        ),
                        hostname=host,
                        fb_logged_in=logged_in,
                    )

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
    args = parser.parse_args()

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
