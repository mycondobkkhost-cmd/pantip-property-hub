"""Facebook authentication with persistent session management."""

from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from loguru import logger
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from config.settings import settings


class FacebookAuth:
    """
    Manages Facebook login using Playwright + cookie backup.

    Session strategy (reduces ban risk / 2FA pain):
    1. Prefer connecting to the user's real Google Chrome (CDP) so saved
       accounts, passwords, and already-passed 2FA are available.
    2. Else use persistent user_data_dir so Chromium keeps login between runs.
    3. Export cookies to JSON after successful login as a secondary backup.
    4. Prefer reusing session over re-entering password every run.
    5. Add human-like delays and avoid headless on first login (2FA/checkpoint).
    6. Run from a consistent IP (home/office) — avoid VPN rotation.
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
        browser_mode: str | None = None,
        cdp_url: str | None = None,
    ) -> None:
        self.email = email or settings.FACEBOOK_EMAIL
        self.password = password or settings.FACEBOOK_PASSWORD
        self.user_data_dir = user_data_dir or settings.BROWSER_USER_DATA_DIR
        self.cookies_path = cookies_path or settings.COOKIES_PATH
        self.headless = settings.HEADLESS if headless is None else headless
        self.browser_mode = (browser_mode or settings.FB_BROWSER_MODE or "auto").strip().lower()
        self.cdp_url = (cdp_url or settings.FB_CDP_URL or "http://127.0.0.1:9222").strip()

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.cookies_path.parent.mkdir(parents=True, exist_ok=True)

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        # False when attached to user's real Chrome — must not quit their browser
        self._owns_browser = True

    def _human_delay(self, min_s: float = 0.8, max_s: float = 2.0) -> None:
        time.sleep(random.uniform(min_s, max_s))

    @staticmethod
    def cdp_available(cdp_url: str | None = None) -> bool:
        url = (cdp_url or settings.FB_CDP_URL or "http://127.0.0.1:9222").rstrip("/")
        try:
            with urllib.request.urlopen(f"{url}/json/version", timeout=1.5) as resp:
                return int(getattr(resp, "status", 200) or 200) < 500
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return False

    def start_browser(self) -> Page:
        """Attach to real Chrome (CDP) or launch a dedicated browser profile."""
        mode = self.browser_mode
        if mode in {"cdp", "connect", "existing", "real-chrome"}:
            return self._connect_cdp(self.cdp_url)
        if mode in {"chrome", "system-chrome", "google-chrome"}:
            return self._launch_system_chrome()
        if mode in {"auto", ""}:
            if self.cdp_available(self.cdp_url):
                try:
                    return self._connect_cdp(self.cdp_url)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("เชื่อม Chrome จริงไม่สำเร็จ — ใช้เบราว์เซอร์แยก: {}", exc)
            return self._launch_playwright_chromium()
        return self._launch_playwright_chromium()

    def _connect_cdp(self, cdp_url: str) -> Page:
        if not self.cdp_available(cdp_url):
            raise RuntimeError(
                "ยังไม่พบ Chrome โหมด Agent — ให้ดับเบิลคลิก "
                "scripts/mac/เปิดChromeจริงสำหรับAgent.command "
                "ก่อน (ใช้โปรไฟล์ Chrome เดิมที่ล็อกอินเฟสไว้แล้ว) "
                f"แล้วค่อยลองใหม่ · CDP={cdp_url}"
            )
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
        self._owns_browser = False
        if self._browser.contexts:
            self._context = self._browser.contexts[0]
        else:
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="th-TH",
                timezone_id="Asia/Bangkok",
            )
        page = None
        for p in self._context.pages:
            try:
                u = (p.url or "").lower()
            except Exception:  # noqa: BLE001
                u = ""
            if "facebook.com" in u:
                page = p
                break
        if page is None:
            page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._page = page
        logger.info("เชื่อมกับ Google Chrome จริงแล้ว (CDP) · {}", cdp_url)
        return self._page

    def _launch_system_chrome(self) -> Page:
        """Google Chrome channel + Agent-owned profile (still separate from daily Chrome)."""
        self._playwright = sync_playwright().start()
        self._owns_browser = True
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                channel="chrome",
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                locale="th-TH",
                timezone_id="Asia/Bangkok",
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("เปิด channel=chrome ไม่ได้ — ใช้ Chromium: {}", exc)
            return self._launch_playwright_chromium(reuse_playwright=True)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._page

    def _launch_playwright_chromium(self, *, reuse_playwright: bool = False) -> Page:
        from src.facebook.ensure_runtime import ensure_playwright_chromium

        ensure_playwright_chromium()
        try:
            return self._launch_persistent(reuse_playwright=reuse_playwright)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "Executable doesn't exist" in msg or "playwright install" in msg.lower():
                logger.warning("Chromium missing — installing then retry once")
                ensure_playwright_chromium()
                return self._launch_persistent(reuse_playwright=True)
            raise

    def _launch_persistent(self, *, reuse_playwright: bool = False) -> Page:
        if not reuse_playwright or self._playwright is None:
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:  # noqa: BLE001
                    pass
            self._playwright = sync_playwright().start()
        self._owns_browser = True
        self._browser = None
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
        if not self._owns_browser:
            # Never inject cookies into the user's real Chrome profile
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
        try:
            cookies = self._context.cookies()
            self.cookies_path.write_text(
                json.dumps(cookies, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Saved cookies to {}", self.cookies_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Save cookies skipped: {}", exc)

    def _perform_login(self, page: Page) -> None:
        """Optional autofill when Hub has saved credentials."""
        if not self.email or not self.password:
            return

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
        """Keep browser open so user can finish login / 2FA / account switch."""
        deadline = time.time() + max(60.0, float(timeout_sec))
        last_msg_at = 0.0
        while time.time() < deadline:
            remaining = int(deadline - time.time())
            if on_status and (time.time() - last_msg_at) >= 15:
                on_status(
                    f"ล็อกอินในหน้าต่าง Chrome ได้เลย · เหลือ ~{max(1, remaining // 60)} นาที — อย่าปิดหน้าต่าง"
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
        force_manual: bool = False,
    ) -> Page:
        """
        Ensure an authenticated Facebook session.

        Default / Hub login button: open a visible browser so the user can
        log in (or switch accounts) manually — Hub password is optional.
        """

        def say(msg: str) -> None:
            logger.info(msg)
            if on_status:
                try:
                    on_status(msg)
                except Exception:  # noqa: BLE001
                    pass

        page = self.start_browser()
        if not self._owns_browser:
            say("ใช้ Google Chrome จริงแล้ว (โปรไฟล์เดิม) — สลับบัญชีจากไอคอนโปรไฟล์มุมขวาบนได้")

        if not force_manual:
            if self._is_logged_in(page):
                say("ล็อกอินอยู่แล้วจากเซสชันเดิม")
                self._save_cookies()
                return page

            if self._restore_cookies(page) and self._is_logged_in(page):
                say("ล็อกอินด้วยคุกกี้ที่บันทึกไว้")
                self._save_cookies()
                return page

        say("เปิดหน้าต่างเฟสแล้ว — ล็อกอินบัญชีที่ต้องการใน Chrome (สลับบัญชีได้)")
        try:
            page.goto(self.FACEBOOK_URL, wait_until="domcontentloaded")
        except Exception:  # noqa: BLE001
            pass

        already = False
        try:
            already = self._has_session_cookie() or self._is_logged_in(page, navigate=False)
        except Exception:  # noqa: BLE001
            already = False

        if already and force_manual:
            say(
                "เซสชันเดิมยังอยู่ — ถ้าจะสลับบัญชี ให้สลับโปรไฟล์ Chrome หรือล็อกเอาท์แล้วล็อกอินใหม่ "
                "(รอ ~20 วินาที ถ้าใช้บัญชีเดิมต่อระบบจะรับเอง)"
            )
            grace_end = time.time() + 20
            saw_logout = False
            while time.time() < grace_end:
                try:
                    if not self._has_session_cookie() and not self._is_logged_in(
                        page, navigate=False
                    ):
                        saw_logout = True
                        break
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(2)
            if not saw_logout:
                if self._is_logged_in(page, navigate=True):
                    self._save_cookies()
                    say("ใช้บัญชีเดิมต่อ — พร้อมทำงานอัตโนมัติ")
                    return page
            else:
                say("รอให้ล็อกอินบัญชีใหม่ใน Chrome…")

        # Optional autofill only when Hub has saved creds and form is visible
        if self.email and self.password:
            try:
                email_input = page.locator('input[name="email"]')
                if email_input.count() > 0:
                    say("มีบัญชีที่บันทึกไว้ (ไม่บังคับ) — กำลังลองใส่ให้อัตโนมัติ")
                    self._perform_login(page)
            except Exception as exc:  # noqa: BLE001
                logger.warning("autofill login skipped: {}", exc)
            if self._is_logged_in(page):
                self._save_cookies()
                say("ล็อกอินเฟสสำเร็จ")
                return page

        if self._wait_for_manual_verification(
            page,
            timeout_sec=wait_manual_sec,
            on_status=on_status,
        ):
            self._save_cookies()
            say("ล็อกอินเฟสสำเร็จ — ระบบจะคอมเมนต์อัตโนมัติต่อได้เลย")
            return page

        raise RuntimeError(
            "ยังล็อกอินไม่สำเร็จ — ล็อกอินในหน้าต่าง Chrome ให้ครบ แล้วกดปุ่มล็อกอินใน Hub อีกครั้ง"
        )

    def close(self) -> None:
        # Never quit the user's real Chrome when attached via CDP
        if self._owns_browser:
            if self._context:
                try:
                    self._context.close()
                except Exception:  # noqa: BLE001
                    pass
            if self._browser:
                try:
                    self._browser.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass
        self._context = None
        self._browser = None
        self._playwright = None
        self._page = None

    def __enter__(self) -> Page:
        return self.login()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
