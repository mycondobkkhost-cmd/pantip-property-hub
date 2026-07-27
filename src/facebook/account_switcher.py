"""Switch among Facebook accounts already logged into one Chrome profile."""

from __future__ import annotations

import random
import time
from typing import Any

from loguru import logger
from playwright.sync_api import Page


class FacebookAccountSwitcher:
    """Use Facebook's in-browser account switcher (not Chrome profiles)."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def _human_delay(self, min_s: float = 0.6, max_s: float = 1.6) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def _safe_click(self, loc, *, timeout: int = 3000) -> bool:
        try:
            if loc.count() <= 0:
                return False
        except Exception:  # noqa: BLE001
            return False
        try:
            loc.click(timeout=timeout)
            return True
        except Exception:  # noqa: BLE001
            try:
                loc.click(timeout=timeout, force=True)
                return True
            except Exception:  # noqa: BLE001
                try:
                    loc.evaluate("el => el.click()")
                    return True
                except Exception:  # noqa: BLE001
                    return False

    def current_account_hint(self) -> str:
        """Best-effort display name of the active FB account."""
        selectors = (
            '[aria-label="Your profile"]',
            '[aria-label="บัญชีของคุณ"]',
            '[aria-label="โปรไฟล์ของคุณ"]',
            'div[role="banner"] [aria-label*="profile" i]',
            'div[role="banner"] [aria-label*="บัญชี"]',
        )
        for sel in selectors:
            loc = self.page.locator(sel).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    label = (loc.get_attribute("aria-label") or "").strip()
                    if label:
                        return label
            except Exception:  # noqa: BLE001
                continue
        return ""

    def _open_account_menu(self) -> bool:
        triggers = (
            '[aria-label="Your profile"]',
            '[aria-label="บัญชีของคุณ"]',
            '[aria-label="Account"]',
            '[aria-label="โปรไฟล์ของคุณ"]',
            'div[role="banner"] [aria-label*="profile" i]',
            'div[role="banner"] [aria-label*="บัญชี"]',
        )
        for sel in triggers:
            loc = self.page.locator(sel).first
            if self._safe_click(loc, timeout=2500):
                self._human_delay(0.8, 1.5)
                return True
        return False

    def switch_to(self, switch_name: str) -> dict[str, Any]:
        """
        Switch to a Facebook account whose menu label contains `switch_name`.

        Accounts must already be added in Facebook's account switcher.
        """
        name = (switch_name or "").strip()
        if not name:
            return {"ok": False, "error": "missing switch_name", "action": "switch_failed"}

        try:
            self.page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"navigate failed: {exc}",
                "action": "switch_failed",
            }
        self._human_delay(1.5, 2.8)

        hint = self.current_account_hint()
        if hint and name.lower() in hint.lower():
            logger.info("Already on FB account matching {!r} ({})", name, hint)
            return {"ok": True, "action": "already", "detail": hint}

        if not self._open_account_menu():
            return {
                "ok": False,
                "error": "เปิดเมนูโปรไฟล์เฟสไม่ได้",
                "action": "switch_failed",
            }

        # See all profiles / Switch accounts
        for label in (
            "See all profiles",
            "ดูโปรไฟล์ทั้งหมด",
            "Switch profiles",
            "สลับโปรไฟล์",
            "Log into another account",
            "เข้าสู่ระบบบัญชีอื่น",
        ):
            loc = self.page.locator(
                f'[role="menuitem"]:has-text("{label}"), '
                f'div[role="button"]:has-text("{label}"), '
                f'span:has-text("{label}")'
            ).first
            if self._safe_click(loc, timeout=2000):
                self._human_delay(1.0, 2.0)
                break

        # Click account row matching name
        candidates = [
            f'[role="menuitem"]:has-text("{name}")',
            f'[role="listitem"]:has-text("{name}")',
            f'div[role="button"]:has-text("{name}")',
            f'span:has-text("{name}")',
        ]
        clicked = False
        for sel in candidates:
            loc = self.page.locator(sel).first
            try:
                if loc.count() <= 0 or not loc.is_visible():
                    continue
            except Exception:  # noqa: BLE001
                continue
            if self._safe_click(loc, timeout=3000):
                clicked = True
                break

        if not clicked:
            try:
                self.page.keyboard.press("Escape")
            except Exception:  # noqa: BLE001
                pass
            return {
                "ok": False,
                "error": f"ไม่พบบัญชีเฟสชื่อใกล้เคียง «{name}» ในเมนูสลับ — ตรวจว่าล็อกอินค้างไว้แล้ว และชื่อใน Hub ตรงกับชื่อในเฟส",
                "action": "switch_failed",
            }

        self._human_delay(2.5, 4.5)
        # Dismiss possible dialogs
        try:
            self.page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001
            pass
        self._human_delay(0.5, 1.0)

        hint2 = self.current_account_hint()
        logger.success("Switched FB account toward {!r} · hint={}", name, hint2 or "—")
        return {
            "ok": True,
            "action": "switched",
            "detail": hint2 or name,
        }
