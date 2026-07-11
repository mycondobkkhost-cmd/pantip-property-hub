"""Facebook authentication with persistent session management."""

from __future__ import annotations

import json
import random
import time
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
    LOGIN_CHECK_SELECTOR = '[aria-label="Your profile"], [aria-label="บัญชีของคุณ"]'

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

    def _is_logged_in(self, page: Page) -> bool:
        page.goto(self.FACEBOOK_URL, wait_until="domcontentloaded")
        self._human_delay(1.5, 3.0)
        return page.locator(self.LOGIN_CHECK_SELECTOR).count() > 0

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
            raise ValueError("FACEBOOK_EMAIL and FACEBOOK_PASSWORD must be set in .env")

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

        logger.info(
            "Submitted login. If 2FA/checkpoint appears, complete it in the browser "
            "(set HEADLESS=false for first login)."
        )
        page.wait_for_load_state("networkidle", timeout=120_000)
        self._human_delay(2.0, 4.0)

    def login(self) -> Page:
        """
        Ensure an authenticated Facebook session.

        Flow:
          1. Start persistent browser context
          2. Try existing session in user_data_dir
          3. Fallback: restore cookies from file
          4. Fallback: credential login (manual 2FA if needed)
          5. Persist cookies after success
        """
        page = self.start_browser()

        if self._is_logged_in(page):
            logger.info("Already logged in via persistent session")
            self._save_cookies()
            return page

        if self._restore_cookies(page) and self._is_logged_in(page):
            logger.info("Logged in via restored cookies")
            self._save_cookies()
            return page

        logger.info("No valid session found — performing credential login")
        self._perform_login(page)

        if not self._is_logged_in(page):
            raise RuntimeError(
                "Login failed or requires manual verification. "
                "Run with HEADLESS=false, complete 2FA/checkpoint, then retry."
            )

        self._save_cookies()
        logger.success("Facebook login successful")
        return page

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
