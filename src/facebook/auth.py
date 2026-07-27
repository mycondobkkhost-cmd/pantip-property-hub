"""Facebook authentication with persistent session management."""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from pathlib import Path

from loguru import logger
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from config.settings import settings


class FacebookAuth:
    """
    Manages Facebook login using Playwright persistent context + cookie backup.

  Session strategy (reduces ban risk):
    1. Use persistent user_data_dir so Chromium keeps login between runs.
    2. Export cookies to JSON after successful login as a secondary backup.
    3. Prefer reusing session over re-entering password every run.
    4. Add human-like delays and avoid headless on first login (2FA/checkpoint).
    5. Run from a consistent IP (Mac Mini at home/office) — avoid VPN rotation.
    """

    FACEBOOK_URL = "https://www.facebook.com/"
    LOGIN_CHECK_SELECTORS = (
        '[aria-label="Your profile"]',
        '[aria-label="บัญชีของคุณ"]',
        '[aria-label="Profile"]',
        '[aria-label="โปรไฟล์ของคุณ"]',
        '[aria-label="Account"]',
        'div[role="navigation"] [aria-label*="profile" i]',
        'div[role="banner"] [aria-label*="บัญชี"]',
    )

    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        user_data_dir: Path | None = None,
        cookies_path: Path | None = None,
        headless: bool | None = None,
    ) -> None:
        self.email = email or settings.FACEBOOK_EMAIL
        self.password = password or settings.FACEBOOK_PASSWORD
        self.user_data_dir = user_data_dir or settings.BROWSER_USER_DATA_DIR
        self.cookies_path = cookies_path or settings.COOKIES_PATH
        self.headless = settings.HEADLESS if headless is None else headless

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)

        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def _human_delay(self, min_s: float = 0.8, max_s: float = 2.0) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def start_browser(self) -> Page:
        """Launch Chromium with persistent profile (Apple Silicon native)."""
        from src.facebook.ensure_runtime import ensure_playwright_chromium

        ensure_playwright_chromium()
        try:
            return self._launch_persistent()
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "Executable doesn't exist" in msg or "playwright install" in msg.lower():
                logger.warning("Chromium missing — installing then retry once")
                ensure_playwright_chromium()
                return self._launch_persistent()
            raise

    def _launch_persistent(self) -> Page:
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            locale="th-TH",
            timezone_id="Asia/Bangkok",
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._page

    def _has_session_cookie(self) -> bool:
        if not self._context:
            return False
        try:
            return any(c.get("name") == "c_user" for c in self._context.cookies())
        except Exception:  # noqa: BLE001
            return False

    def _is_logged_in(self, page: Page, *, navigate: bool = True) -> bool:
        if navigate:
            page.goto(self.FACEBOOK_URL, wait_until="domcontentloaded")
            self._human_delay(1.5, 3.0)

        if self._has_session_cookie():
            # Cookie alone is strong signal; still verify not stuck on login form.
            email_box = page.locator('input[name="email"]')
            pass_box = page.locator('input[name="pass"]')
            if email_box.count() == 0 or pass_box.count() == 0:
                return True

        for sel in self.LOGIN_CHECK_SELECTORS:
            try:
                if page.locator(sel).count() > 0:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _restore_cookies(self, page: Page) -> bool:
        if not self.cookies_path.exists():
            return False

        try:
            cookies = json.loads(self.cookies_path.read_text(encoding="utf-8"))
            self._context.add_cookies(cookies)
            logger.info("Restored cookies from {}", self.cookies_path)
            return True
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to restore cookies: {}", exc)
            return False

    def _save_cookies(self) -> None:
        if not self._context:
            return
        cookies = self._context.cookies()
        self.cookies_path.write_text(
            json.dumps(cookies, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved cookies to {}", self.cookies_path)

    def _perform_login(self, page: Page) -> None:
        if not self.email or not self.password:
            raise ValueError("ยังไม่มีอีเมล/รหัสเฟส — บันทึกใน Hub แท็บเชื่อมต่อเฟสก่อน")

        page.goto(self.FACEBOOK_URL, wait_until="domcontentloaded")
        self._human_delay()

        email_input = page.locator('input[name="email"]')
        password_input = page.locator('input[name="pass"]')

        if email_input.count() == 0:
            logger.info("Login form not visible — may already be authenticated")
            return

        email_input.fill(self.email)
        self._human_delay(0.5, 1.2)
        password_input.fill(self.password)
        self._human_delay(0.5, 1.2)
        page.locator('button[name="login"]').click()

        logger.info("ส่งฟอร์มล็อกอินแล้ว — ถ้ามี 2FA/checkpoint ให้ทำในหน้าต่างเบราว์เซอร์")
        try:
            page.wait_for_load_state("domcontentloaded", timeout=60_000)
        except Exception:  # noqa: BLE001
            pass
        self._human_delay(2.0, 4.0)

    def _wait_for_manual_verification(
        self,
        page: Page,
        *,
        timeout_sec: float = 600,
        on_status: Callable[[str], None] | None = None,
    ) -> bool:
        """Keep browser open so user can finish 2FA / checkpoint."""
        deadline = time.time() + max(60.0, float(timeout_sec))
        last_msg_at = 0.0
        while time.time() < deadline:
            remaining = int(deadline - time.time())
            if on_status and (time.time() - last_msg_at) >= 15:
                on_status(
                    f"รอยืนยันในหน้าต่างเฟส (2FA/รหัส) · เหลือ ~{remaining // 60} นาที — อย่าปิดหน้าต่าง Chrome"
                )
                last_msg_at = time.time()
            try:
                # Do not navigate away while user is mid-2FA/checkpoint.
                if self._has_session_cookie():
                    if self._is_logged_in(page, navigate=True):
                        return True
                elif self._is_logged_in(page, navigate=False):
                    return True
            except Exception:  # noqa: BLE001
                pass
            time.sleep(5)
        return False

    def login(
        self,
        *,
        wait_manual_sec: float = 600,
        on_status: Callable[[str], None] | None = None,
    ) -> Page:
        """
        Ensure an authenticated Facebook session.

        Flow:
          1. Start persistent browser context (visible for first login)
          2. Try existing session in user_data_dir
          3. Fallback: restore cookies from file
          4. Fallback: credential login + wait for manual 2FA/checkpoint
          5. Persist cookies after success
        """
        def say(msg: str) -> None:
            logger.info(msg)
            if on_status:
                try:
                    on_status(msg)
                except Exception:  # noqa: BLE001
                    pass

        page = self.start_browser()

        if self._is_logged_in(page):
            say("ล็อกอินอยู่แล้วจากเซสชันเดิม")
            self._save_cookies()
            return page

        if self._restore_cookies(page) and self._is_logged_in(page):
            say("ล็อกอินด้วยคุกกี้ที่บันทึกไว้")
            self._save_cookies()
            return page

        say("กำลังใส่บัญชีเฟส — ถ้ามีรหัสยืนยัน ให้ใส่ในหน้าต่าง Chrome ที่เปิด")
        self._perform_login(page)

        if self._is_logged_in(page):
            self._save_cookies()
            say("ล็อกอินเฟสสำเร็จ")
            return page

        say("เฟสขอตรวจเพิ่ม — กรุณาใส่ 2FA / ยืนยันในหน้าต่าง Chrome (รอได้นานสุด ~10 นาที)")
        if self._wait_for_manual_verification(
            page,
            timeout_sec=wait_manual_sec,
            on_status=on_status,
        ):
            self._save_cookies()
            say("ล็อกอินเฟสสำเร็จหลังยืนยันมือ")
            return page

        raise RuntimeError(
            "ยังล็อกอินไม่สำเร็จ — ใส่รหัสยืนยันในหน้าต่างเฟสให้ครบ แล้วกดปุ่มล็อกอินใน Hub อีกครั้ง"
        )

    def close(self) -> None:
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()
        self._context = None
        self._playwright = None
        self._page = None

    def __enter__(self) -> Page:
        return self.login()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
