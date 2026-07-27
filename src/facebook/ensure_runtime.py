"""Ensure Playwright + Chromium are ready before opening Facebook."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from loguru import logger


ProgressFn = Callable[[str], None]


def _chromium_executable_exists() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        pw = sync_playwright().start()
        try:
            exe = Path(pw.chromium.executable_path)
            return exe.is_file()
        finally:
            pw.stop()
    except Exception:  # noqa: BLE001
        return False


def ensure_playwright_chromium(*, on_progress: ProgressFn | None = None) -> None:
    """
    Install Playwright package (if needed) and Chromium browser.
    Safe to call every agent start — no-ops when already ready.
    """
    import os

    def say(msg: str) -> None:
        logger.info(msg)
        if on_progress:
            on_progress(msg)

    try:
        import playwright  # noqa: F401
    except ImportError:
        say("กำลังติดตั้งชุด Playwright (ครั้งแรก)...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright"],
            check=True,
        )

    if _chromium_executable_exists():
        return

    say("กำลังดาวน์โหลดเบราว์เซอร์สำหรับเปิดเฟส (ครั้งแรกอาจใช้เวลา 1–3 นาที) — อย่าปิดหน้าต่างนี้")
    env = dict(os.environ)
    home = Path.home()
    if sys.platform == "darwin":
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "Library" / "Caches" / "ms-playwright")
    elif sys.platform.startswith("win"):
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "AppData" / "Local" / "ms-playwright")

    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        env=env,
    )

    if not _chromium_executable_exists():
        raise RuntimeError(
            "ติดตั้งเบราว์เซอร์แล้วยังเปิดไม่ได้ — ให้หัวหน้าทีมรัน: python3 -m playwright install chromium"
        )
    say("เตรียมเบราว์เซอร์เรียบร้อย")
