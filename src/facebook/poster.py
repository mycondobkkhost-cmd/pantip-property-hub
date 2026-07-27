"""Facebook Group posting automation (images + caption, no link attachments)."""

from __future__ import annotations

import random
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from loguru import logger
from playwright.sync_api import Page

from config.settings import settings
from src.hub.group_post_publish_store import sanitize_caption_no_links


_RESTRICT_NEEDLES = (
    "you're temporarily blocked",
    "we limit how often",
    "จำกัดการใช้งาน",
    "คุณถูกจำกัด",
    "ชั่วคราว",
    "try again later",
    "ไม่สามารถโพสต์ได้ในขณะนี้",
    "this feature isn't available",
)


class FacebookGroupPoster:
    """Upload images and publish property posts to a Facebook Group."""

    def __init__(self, page: Page, image_cache_dir: Path | None = None) -> None:
        self.page = page
        self.image_cache_dir = image_cache_dir or settings.IMAGE_CACHE_DIR
        self.image_cache_dir.mkdir(parents=True, exist_ok=True)

    def _human_delay(self, min_s: float = 1.0, max_s: float = 2.5) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def _page_blob(self) -> str:
        try:
            return (self.page.inner_text("body") or "")[:6000]
        except Exception:  # noqa: BLE001
            return ""

    def _detect_restriction(self) -> str | None:
        blob = self._page_blob().lower()
        for n in _RESTRICT_NEEDLES:
            if n.lower() in blob:
                return n
        return None

    def _download_image(self, url: str, property_id: str) -> Path | None:
        try:
            parsed = urlparse(url)
            suffix = Path(parsed.path).suffix or ".jpg"
            if len(suffix) > 8:
                suffix = ".jpg"
            dest = self.image_cache_dir / f"{property_id}_{hash(url) & 0xFFFFFFFF}{suffix}"
            if dest.exists() and dest.stat().st_size > 500:
                return dest
            response = requests.get(url, timeout=45)
            response.raise_for_status()
            dest.write_bytes(response.content)
            return dest
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to download {}: {}", url, exc)
            return None

    def _resolve_image_paths(self, image_urls: list[str], property_id: str) -> list[Path]:
        paths: list[Path] = []
        for item in image_urls or []:
            s = str(item or "").strip()
            if not s:
                continue
            if s.startswith(("http://", "https://")):
                cached = self._download_image(s, property_id)
                if cached:
                    paths.append(cached)
            else:
                local = Path(s)
                if local.exists():
                    paths.append(local)
        return paths[:10]

    def navigate_to_group(self, group_url: str) -> None:
        logger.info("Navigating to group: {}", group_url)
        self.page.goto(group_url, wait_until="domcontentloaded", timeout=60_000)
        self._human_delay(2.0, 4.0)

    def _open_composer(self) -> bool:
        triggers = [
            'div[role="button"]:has-text("เขียนอะไรสักหน่อย")',
            'div[role="button"]:has-text("Write something")',
            'div[role="button"]:has-text("Do you want to share")',
            '[aria-label="สร้างโพสต์สาธารณะ"]',
            '[aria-label="Create a public post"]',
            '[aria-label="Create post"]',
            'div[role="button"]:has-text("Photo/video")',
            'div[role="button"]:has-text("รูปภาพ/วิดีโอ")',
        ]
        for selector in triggers:
            loc = self.page.locator(selector).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    loc.click(timeout=3000)
                    self._human_delay(1.2, 2.2)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _type_caption(self, caption: str) -> bool:
        text = sanitize_caption_no_links(caption)
        selectors = [
            '[role="dialog"] [role="textbox"][contenteditable="true"]',
            '[role="textbox"][contenteditable="true"]',
            'div[aria-label*="สร้างโพสต์"]',
            'div[aria-label*="Create"][contenteditable="true"]',
            'div[contenteditable="true"][role="textbox"]',
        ]
        for selector in selectors:
            box = self.page.locator(selector).first
            try:
                if box.count() <= 0 or not box.is_visible():
                    continue
            except Exception:  # noqa: BLE001
                continue
            try:
                box.click(timeout=2500)
                self._human_delay(0.3, 0.7)
                try:
                    box.fill("")
                except Exception:  # noqa: BLE001
                    pass
                # Human-like typing in chunks
                chunk = 40
                for i in range(0, len(text), chunk):
                    box.type(text[i : i + chunk], delay=random.randint(12, 35))
                    self._human_delay(0.05, 0.2)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("caption type failed on {}: {}", selector, exc)
                continue
        return False

    def _upload_images(self, paths: list[Path]) -> bool:
        if not paths:
            return False
        # Prefer dialog file input
        for sel in (
            '[role="dialog"] input[type="file"]',
            'input[type="file"][accept*="image"]',
            'input[type="file"]',
        ):
            loc = self.page.locator(sel)
            try:
                n = loc.count()
            except Exception:  # noqa: BLE001
                continue
            for i in range(min(n, 5)):
                inp = loc.nth(i)
                try:
                    inp.set_input_files([str(p) for p in paths])
                    self._human_delay(3.0, 6.0)
                    return True
                except Exception:  # noqa: BLE001
                    continue
        # Click photo button then retry
        for label in ("Photo/video", "รูปภาพ/วิดีโอ", "Photo", "รูปภาพ"):
            btn = self.page.locator(
                f'[role="dialog"] [aria-label="{label}"], '
                f'[role="dialog"] div[role="button"]:has-text("{label}")'
            ).first
            try:
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2000)
                    self._human_delay(0.8, 1.5)
                    break
            except Exception:  # noqa: BLE001
                continue
        for sel in ('[role="dialog"] input[type="file"]', 'input[type="file"]'):
            loc = self.page.locator(sel).first
            try:
                if loc.count() > 0:
                    loc.set_input_files([str(p) for p in paths])
                    self._human_delay(3.0, 6.0)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _click_post(self) -> bool:
        selectors = [
            '[role="dialog"] [aria-label="โพสต์"][role="button"]',
            '[role="dialog"] [aria-label="Post"][role="button"]',
            '[role="dialog"] div[aria-label="โพสต์"]',
            '[role="dialog"] div[aria-label="Post"]',
            'div[aria-label="โพสต์"][role="button"]',
            'div[aria-label="Post"][role="button"]',
        ]
        for sel in selectors:
            btn = self.page.locator(sel).first
            try:
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=3000)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _extract_permalink(self) -> str:
        """Best-effort: current URL or first /groups/.../posts/ link."""
        try:
            url = self.page.url or ""
            if "/posts/" in url or "/permalink" in url:
                return url.split("?")[0]
        except Exception:  # noqa: BLE001
            pass
        try:
            hrefs = self.page.eval_on_selector_all(
                'a[href*="/posts/"], a[href*="permalink"]',
                "els => els.slice(0, 12).map(e => e.href)",
            )
            for h in hrefs or []:
                if isinstance(h, str) and ("/groups/" in h or "permalink" in h):
                    return h.split("?")[0]
        except Exception:  # noqa: BLE001
            pass
        return ""

    def post_to_group(
        self,
        caption: str,
        image_urls: list[str],
        property_id: str = "property",
        group_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a group post with images + caption (no URL attachments).

        Returns detailed dict: ok, permalink, action, detail, error
        """
        group_url = (group_url or settings.FACEBOOK_GROUP_URL or "").strip()
        if not group_url:
            return {
                "ok": False,
                "error": "missing group_url",
                "action": "skipped",
                "detail": "ไม่มีลิงก์กลุ่ม",
            }

        caption = sanitize_caption_no_links(caption)
        if not caption:
            return {
                "ok": False,
                "error": "empty caption",
                "action": "skipped",
                "detail": "ไม่มีข้อความโพส",
            }

        image_paths = self._resolve_image_paths(image_urls, property_id)
        if not image_paths:
            return {
                "ok": False,
                "error": "no images",
                "action": "skipped",
                "detail": "ไม่มีรูปสำหรับโพส",
            }

        self.navigate_to_group(group_url)
        blocked = self._detect_restriction()
        if blocked:
            return {
                "ok": False,
                "error": blocked,
                "action": "restricted",
                "detail": f"บัญชีถูกจำกัด: {blocked}",
            }

        if not self._open_composer():
            return {
                "ok": False,
                "error": "composer not found",
                "action": "composer_missing",
                "detail": "เปิดช่องโพสต์กลุ่มไม่ได้",
            }

        if not self._upload_images(image_paths):
            return {
                "ok": False,
                "error": "upload failed",
                "action": "upload_failed",
                "detail": "อัปโหลดรูปไม่สำเร็จ",
            }

        if not self._type_caption(caption):
            return {
                "ok": False,
                "error": "caption failed",
                "action": "caption_failed",
                "detail": "พิมพ์ข้อความโพสไม่สำเร็จ",
            }

        self._human_delay(1.0, 2.2)
        if not self._click_post():
            return {
                "ok": False,
                "error": "post button missing",
                "action": "submit_failed",
                "detail": "หาปุ่มโพสต์ไม่เจอ",
            }

        self._human_delay(4.0, 8.0)
        blocked = self._detect_restriction()
        if blocked:
            return {
                "ok": False,
                "error": blocked,
                "action": "restricted",
                "detail": f"ถูกจำกัดหลังกดโพสต์: {blocked}",
            }

        permalink = self._extract_permalink()
        logger.success("Posted {} · permalink={}", property_id, permalink or "(pending)")
        return {
            "ok": True,
            "permalink": permalink,
            "action": "posted",
            "detail": "โพสสำเร็จ",
            "error": None,
        }


def process_property_batch(
    properties: list[dict[str, Any]],
    page: Page,
    max_posts: int | None = None,
) -> list[dict[str, Any]]:
    """Legacy sheet-driven batch poster (compat for main.py / scheduler)."""
    from src.sheets.client import mark_property_status

    max_posts = max_posts or settings.MAX_POSTS_PER_RUN
    poster = FacebookGroupPoster(page)
    results: list[dict[str, Any]] = []

    for prop in properties[:max_posts]:
        prop_id = prop.get("row_id", "unknown")
        logger.info("Posting property: {} — {}", prop_id, prop.get("title", ""))

        outcome = poster.post_to_group(
            caption=prop["caption"],
            image_urls=prop["image_urls"],
            property_id=str(prop_id),
            group_url=prop.get("group_url"),
        )
        success = bool(outcome.get("ok")) if isinstance(outcome, dict) else bool(outcome)

        status = "posted" if success else "failed"
        try:
            mark_property_status(prop["row_index"], status)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not update sheet status for row {}: {}", prop["row_index"], exc)

        results.append(
            {
                **prop,
                "post_success": success,
                "final_status": status,
                "permalink": (outcome or {}).get("permalink") if isinstance(outcome, dict) else "",
            }
        )
        time.sleep(random.uniform(30, 90))

    return results
