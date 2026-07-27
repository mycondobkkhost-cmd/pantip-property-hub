"""Playwright commenter for personal Facebook on existing group posts."""

from __future__ import annotations

import random
import time
from typing import Any

from loguru import logger
from playwright.sync_api import Page


class FacebookPostCommenter:
    """Leave a short comment on a Facebook post permalink (personal session)."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def _human_delay(self, min_s: float = 0.8, max_s: float = 2.2) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def _dismiss_overlays(self) -> None:
        """Best-effort close cookie / login-ish dialogs that block the composer."""
        for label in ("Allow all cookies", "อนุญาตคุกกี้ทั้งหมด", "Close", "ปิด", "Not Now", "ไว้ทีหลัง"):
            loc = self.page.locator(f'[aria-label="{label}"]').first
            try:
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=1500)
                    self._human_delay(0.4, 1.0)
            except Exception:  # noqa: BLE001
                continue

    def _find_comment_box(self):
        selectors = [
            '[aria-label="เขียนความคิดเห็น"]',
            '[aria-label="Write a comment"]',
            '[aria-label="แสดงความคิดเห็น"]',
            'div[role="textbox"][contenteditable="true"][aria-label*="ความคิดเห็น"]',
            'div[role="textbox"][contenteditable="true"][aria-label*="comment" i]',
            'form [contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"][role="textbox"]',
        ]
        for sel in selectors:
            loc = self.page.locator(sel)
            try:
                n = loc.count()
            except Exception:  # noqa: BLE001
                continue
            for i in range(min(n, 6)):
                box = loc.nth(i)
                try:
                    if box.is_visible():
                        return box
                except Exception:  # noqa: BLE001
                    continue
        return None

    def comment_on_post(self, post_url: str, text: str) -> dict[str, Any]:
        """
        Open post_url and submit `text` as a comment.

        Returns {"ok": bool, "error": str|None}.
        """
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "empty comment text"}
        if not (post_url or "").strip():
            return {"ok": False, "error": "missing post_url"}

        logger.info("Opening post for comment: {}", post_url)
        try:
            self.page.goto(post_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"navigate failed: {exc}"}

        self._human_delay(2.5, 5.0)
        self._dismiss_overlays()

        # Scroll a bit so lazy comment composer mounts
        try:
            self.page.mouse.wheel(0, 600)
            self._human_delay(0.8, 1.6)
            self.page.mouse.wheel(0, 400)
            self._human_delay(0.6, 1.2)
        except Exception:  # noqa: BLE001
            pass

        # Click “Comment” / “แสดงความคิดเห็น” affordance if present
        for label in (
            "แสดงความคิดเห็น",
            "Comment",
            "เขียนความคิดเห็น",
            "Leave a comment",
        ):
            btn = self.page.locator(f'[aria-label="{label}"]').first
            try:
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2000)
                    self._human_delay(0.8, 1.5)
                    break
            except Exception:  # noqa: BLE001
                continue

        box = self._find_comment_box()
        if box is None:
            # One more scroll + retry
            try:
                self.page.keyboard.press("End")
                self._human_delay(1.0, 2.0)
            except Exception:  # noqa: BLE001
                pass
            box = self._find_comment_box()

        if box is None:
            return {"ok": False, "error": "comment box not found"}

        try:
            box.click(timeout=5000)
            self._human_delay(0.4, 0.9)
            # Prefer type for human-like input; fill as fallback
            try:
                box.type(text, delay=random.randint(35, 90))
            except Exception:  # noqa: BLE001
                box.fill(text)
            self._human_delay(0.6, 1.4)

            # Submit: Enter usually sends a FB comment
            box.press("Enter")
            self._human_delay(2.5, 4.5)

            # Fallback: look for Comment / แสดงความคิดเห็น submit near composer
            for sel in (
                'div[aria-label="แสดงความคิดเห็น"][role="button"]',
                'div[aria-label="Comment"][role="button"]',
                '[aria-label="Post"]',
                '[aria-label="โพสต์"]',
            ):
                btn = self.page.locator(sel).first
                try:
                    if btn.count() > 0 and btn.is_visible():
                        btn.click(timeout=1500)
                        self._human_delay(2.0, 3.5)
                        break
                except Exception:  # noqa: BLE001
                    continue

            logger.success("Comment submitted (best-effort): {}", text[:80])
            return {"ok": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"comment failed: {exc}"}
