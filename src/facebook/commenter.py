"""Playwright commenter for personal Facebook on existing group posts."""

from __future__ import annotations

import random
import re
import time
from typing import Any
from urllib.parse import urlparse

from loguru import logger
from playwright.sync_api import Page


_PERSONAL_POST_RE = re.compile(
    r"facebook\.com/(?:people/[^/]+/\d+|profile\.php|[^/]+)/posts/",
    re.I,
)


class FacebookPostCommenter:
    """Leave a short comment on a Facebook post permalink (personal session)."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def _human_delay(self, min_s: float = 0.8, max_s: float = 2.2) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def _safe_click(self, loc, *, timeout: int = 3000) -> bool:
        """Click with fallbacks when FB overlays intercept pointer events."""
        try:
            if loc.count() <= 0:
                return False
        except Exception:  # noqa: BLE001
            return False
        try:
            loc.scroll_into_view_if_needed(timeout=timeout)
        except Exception:  # noqa: BLE001
            pass
        # 1) normal
        try:
            loc.click(timeout=timeout)
            return True
        except Exception:  # noqa: BLE001
            pass
        # 2) force (bypass intercepting overlays)
        try:
            loc.click(timeout=timeout, force=True)
            return True
        except Exception:  # noqa: BLE001
            pass
        # 3) JS click
        try:
            loc.evaluate("el => el.click()")
            return True
        except Exception:  # noqa: BLE001
            return False

    def _current_url(self) -> str:
        try:
            return self.page.url or ""
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _is_group_post_url(url: str) -> bool:
        u = (url or "").lower()
        return "/groups/" in u

    @staticmethod
    def _is_personal_post_url(url: str) -> bool:
        """True for profile/timeline posts — never comment on these."""
        u = (url or "").strip()
        if not u:
            return False
        if "/groups/" in u.lower():
            return False
        if "/share/" in u.lower():
            return False
        return bool(_PERSONAL_POST_RE.search(u))

    @staticmethod
    def _is_share_shortlink(url: str) -> bool:
        u = (url or "").lower()
        return "/share/p/" in u or "/share/v/" in u

    def _dismiss_cookie_banners(self) -> None:
        """Dismiss cookie / chat prompts only — never close the target post dialog."""
        labels = (
            "Allow all cookies",
            "อนุญาตคุกกี้ทั้งหมด",
            "Not Now",
            "ไว้ทีหลัง",
            "ปิดการสนทนา",
            "Dismiss",
        )
        for label in labels:
            loc = self.page.locator(f'[aria-label="{label}"]').first
            try:
                if loc.count() > 0 and loc.is_visible():
                    self._safe_click(loc, timeout=1500)
                    self._human_delay(0.3, 0.7)
            except Exception:  # noqa: BLE001
                continue

    def _open_original_from_photo_viewer(self) -> None:
        """If /share/p landed on a photo lightbox, open the full post (keep dialog)."""
        if self._find_comment_box() is not None:
            return
        for label in (
            "ดูโพสต์",
            "See post",
            "Open post",
            "ดูโพสต์ต้นฉบับ",
            "ไปที่โพสต์",
        ):
            loc = self.page.locator(
                f'a:has-text("{label}"), div[role="link"]:has-text("{label}"), '
                f'span:has-text("{label}"), [aria-label="{label}"]'
            ).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    self._safe_click(loc, timeout=2000)
                    self._human_delay(1.2, 2.2)
                    return
            except Exception:  # noqa: BLE001
                continue

    def _dismiss_overlays(self) -> None:
        """Safe pre-comment cleanup: cookies only (do NOT Escape/close post dialogs)."""
        self._dismiss_cookie_banners()

    def _page_text_blob(self) -> str:
        try:
            return (self.page.inner_text("body") or "")[:8000]
        except Exception:  # noqa: BLE001
            return ""

    def _detect_access_block(self) -> str | None:
        blob = self._page_text_blob()
        needles = (
            ("เนื้อหานี้ยังไม่พร้อมใช้งาน", "โพสต์/กลุ่มไม่พร้อมใช้งาน หรือถูกลบ"),
            ("This content isn't available", "โพสต์/กลุ่มไม่พร้อมใช้งาน หรือถูกลบ"),
            ("คุณต้องเป็นสมาชิก", "ต้องเป็นสมาชิกกลุ่มก่อน"),
            ("You must be a member", "ต้องเป็นสมาชิกกลุ่มก่อน"),
            ("กลุ่มส่วนตัว", "กลุ่มส่วนตัว — ต้องขอเข้าร่วม"),
            ("Private group", "กลุ่มส่วนตัว — ต้องขอเข้าร่วม"),
            ("ขอเข้าร่วมกลุ่มนี้เพื่อดูโพสต์", "กลุ่มปิด — ต้องขอเข้าร่วมก่อนดูโพสต์"),
            ("Join this group to see", "กลุ่มปิด — ต้องขอเข้าร่วมก่อนดูโพสต์"),
        )
        for needle, detail in needles:
            if needle.lower() in blob.lower():
                return detail
        return None

    def _find_join_button(self):
        labels = (
            "ขอเข้าร่วมกลุ่ม",
            "เข้าร่วมกลุ่ม",
            "Join group",
            "Join Group",
            "Join",
            "Request to join",
            "ขอเข้าร่วม",
        )
        for label in labels:
            for sel in (
                f'[aria-label="{label}"]',
                f'div[role="button"]:has-text("{label}")',
                f'span:has-text("{label}")',
            ):
                loc = self.page.locator(sel).first
                try:
                    if loc.count() > 0 and loc.is_visible():
                        return loc, label
                except Exception:  # noqa: BLE001
                    continue
        return None, ""

    def _already_requested_join(self) -> bool:
        blob = self._page_text_blob().lower()
        markers = (
            "ยกเลิกคำขอ",
            "cancel request",
            "requested",
            "ส่งคำขอแล้ว",
            "รอการอนุมัติ",
            "pending",
        )
        return any(m in blob for m in markers)

    def try_request_join_group(self) -> dict[str, Any]:
        """
        If the post/group requires membership, click Join / Request to join.
        Returns detailed status for Hub reporting.
        """
        if self._already_requested_join():
            return {
                "ok": True,
                "action": "join_pending",
                "join_status": "pending",
                "detail": "ส่งคำขอเข้ากลุ่มไว้แล้ว รอแอดมินกลุ่มอนุมัติ",
                "error": None,
            }

        btn, label = self._find_join_button()
        if btn is None:
            block = self._detect_access_block()
            return {
                "ok": False,
                "action": "join_needed",
                "join_status": "needed",
                "detail": block or "พบว่าเข้ากลุ่มไม่ได้ แต่ไม่เจอปุ่มขอเข้าร่วมบนหน้า",
                "error": "join button not found",
            }

        try:
            if not self._safe_click(btn, timeout=4000):
                raise RuntimeError("click join button failed")
            self._human_delay(1.5, 3.0)
            for conf in ("ส่ง", "Confirm", "ยืนยัน", "Join", "ขอเข้าร่วม"):
                c = self.page.locator(f'[aria-label="{conf}"], div[role="button"]:has-text("{conf}")').first
                try:
                    if c.count() > 0 and c.is_visible():
                        self._safe_click(c, timeout=2000)
                        self._human_delay(1.0, 2.0)
                        break
                except Exception:  # noqa: BLE001
                    continue

            if self._already_requested_join() or "join" in label.lower() or "เข้าร่วม" in label:
                return {
                    "ok": True,
                    "action": "join_requested",
                    "join_status": "requested",
                    "detail": f"กด「{label}」แล้ว — รออนุมัติถ้าเป็นกลุ่มปิด",
                    "error": None,
                }
            return {
                "ok": True,
                "action": "join_clicked",
                "join_status": "clicked",
                "detail": f"กด「{label}」แล้ว แต่ยังยืนยันสถานะไม่ได้ชัด — ตรวจใน Chrome",
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "action": "join_failed",
                "join_status": "failed",
                "detail": f"กดขอเข้ากลุ่มไม่สำเร็จ: {exc}",
                "error": str(exc),
            }

    def _is_comment_textbox(self, loc) -> bool:
        """True if locator looks like an editable comment composer (not a button)."""
        try:
            role = (loc.get_attribute("role") or "").lower()
            editable = (loc.get_attribute("contenteditable") or "").lower()
            tag = ""
            try:
                tag = (loc.evaluate("el => el.tagName") or "").lower()
            except Exception:  # noqa: BLE001
                pass
            if editable in {"true", "plaintext-only"}:
                return True
            if role == "textbox":
                return True
            if tag == "textarea":
                return True
            # Explicitly reject comment toggle buttons
            if role == "button":
                return False
            return False
        except Exception:  # noqa: BLE001
            return False

    def _comment_box_selectors(self) -> list[str]:
        # Prefer real textboxes — do NOT use "แสดงความคิดเห็น" (that's a button)
        return [
            '[aria-label="เขียนความคิดเห็น"][contenteditable="true"]',
            '[aria-label="Write a comment"][contenteditable="true"]',
            'div[role="textbox"][contenteditable="true"][aria-label*="ความคิดเห็น"]',
            'div[role="textbox"][contenteditable="true"][aria-label*="comment" i]',
            'div[role="textbox"][contenteditable="true"][aria-placeholder*="ความคิดเห็น"]',
            'div[role="textbox"][contenteditable="true"][aria-placeholder*="comment" i]',
            'form [contenteditable="true"][role="textbox"]',
            'div[contenteditable="true"][role="textbox"]',
            '[aria-label="เขียนความคิดเห็น"]',
            '[aria-label="Write a comment"]',
            '[aria-label="Leave a comment"]',
        ]

    def _find_comment_box_in(self, root):
        for sel in self._comment_box_selectors():
            loc = root.locator(sel)
            try:
                n = loc.count()
            except Exception:  # noqa: BLE001
                continue
            for i in range(min(n, 8)):
                box = loc.nth(i)
                try:
                    if not box.is_visible():
                        continue
                    if self._is_comment_textbox(box):
                        return box
                except Exception:  # noqa: BLE001
                    continue
        return None

    def _find_comment_box(self):
        """Prefer composer inside the open post dialog — never the news-feed first box."""
        try:
            dialogs = self.page.locator('div[role="dialog"]')
            n = dialogs.count()
        except Exception:  # noqa: BLE001
            n = 0
        for i in range(min(n, 4)):
            dlg = dialogs.nth(i)
            try:
                if not dlg.is_visible():
                    continue
            except Exception:  # noqa: BLE001
                continue
            box = self._find_comment_box_in(dlg)
            if box is not None:
                return box
        # Fallback only when URL is clearly a group post (not the feed)
        url = self._current_url()
        if self._is_group_post_url(url) or self._is_share_shortlink(url):
            return self._find_comment_box_in(self.page)
        return None

    def _open_comment_composer(self) -> None:
        """Click 'show/write comment' controls if the textbox is not mounted yet."""
        labels = (
            "เขียนความคิดเห็น",
            "Write a comment",
            "Leave a comment",
            "แสดงความคิดเห็น",
            "Comment",
        )
        roots: list[Any] = []
        try:
            dialogs = self.page.locator('div[role="dialog"]')
            for i in range(min(dialogs.count(), 3)):
                dlg = dialogs.nth(i)
                if dlg.is_visible():
                    roots.append(dlg)
        except Exception:  # noqa: BLE001
            pass
        if not roots:
            roots = [self.page]

        for root in roots:
            for label in labels:
                btn = root.locator(
                    f'div[role="button"][aria-label="{label}"], '
                    f'[role="button"][aria-label="{label}"]'
                ).first
                try:
                    if btn.count() > 0 and btn.is_visible():
                        self._dismiss_cookie_banners()
                        self._safe_click(btn, timeout=2500)
                        self._human_delay(0.8, 1.6)
                        if self._find_comment_box() is not None:
                            return
                except Exception:  # noqa: BLE001
                    continue

    def _type_comment(self, box, text: str) -> None:
        self._dismiss_overlays()
        if not self._safe_click(box, timeout=4000):
            try:
                box.focus(timeout=2000)
            except Exception:  # noqa: BLE001
                pass
        self._human_delay(0.3, 0.7)
        try:
            # Clear any placeholder selection
            self.page.keyboard.press("Meta+A")
            self._human_delay(0.05, 0.12)
        except Exception:  # noqa: BLE001
            pass
        try:
            box.type(text, delay=random.randint(30, 85))
        except Exception:  # noqa: BLE001
            try:
                box.fill(text)
            except Exception:  # noqa: BLE001
                # Last resort: insert via keyboard after focus
                self.page.keyboard.type(text, delay=random.randint(30, 70))

    def _reject_wrong_target(self, opened_url: str) -> dict[str, Any] | None:
        """Abort if Facebook landed on a personal/timeline post (not a group)."""
        url = self._current_url()
        if self._is_personal_post_url(url):
            logger.error(
                "Refusing to comment on personal post · opened={} · landed={}",
                opened_url,
                url,
            )
            return {
                "ok": False,
                "error": "landed on personal post",
                "action": "wrong_target",
                "detail": (
                    "ลิงก์พาไปโพสต์ส่วนตัวของคนอื่น ไม่ใช่โพสต์กลุ่ม — "
                    "ระบบหยุดไม่คอมเมนต์ "
                    "ให้ใส่ลิงก์โพสต์ในกลุ่ม (/groups/...) หรือแชร์จากโพสต์กลุ่มเท่านั้น"
                ),
                "join_status": "",
                "landed_url": url,
            }
        # Share shortlink still resolving is OK if dialog has a group context later;
        # if we only have feed URL with no dialog, that is unsafe.
        if not self._is_group_post_url(url) and not self._is_share_shortlink(url):
            try:
                has_dialog = self.page.locator('div[role="dialog"]').count() > 0
            except Exception:  # noqa: BLE001
                has_dialog = False
            if not has_dialog:
                host = ""
                try:
                    host = urlparse(url).path or ""
                except Exception:  # noqa: BLE001
                    host = ""
                if host in {"", "/"} or host.startswith("/watch") or "facebook.com" in url:
                    # Likely news feed after dialog was closed — refuse
                    if "/groups/" not in url.lower():
                        logger.error("Refusing comment on non-group page · {}", url)
                        return {
                            "ok": False,
                            "error": "not a group post page",
                            "action": "wrong_target",
                            "detail": (
                                "ไม่ได้เปิดหน้าโพสต์กลุ่ม (อาจปิด dialog แล้วเหลือฟีด) — "
                                "ระบบหยุดไม่คอมเมนต์ ลองใส่ลิงก์ /groups/... โดยตรง"
                            ),
                            "join_status": "",
                            "landed_url": url,
                        }
        return None

    def comment_on_post(self, post_url: str, text: str) -> dict[str, Any]:
        """
        Open post_url and submit `text` as a comment.

        Returns detailed dict for Hub reporting:
          ok, error, action, detail, join_status, join_requested
        """
        text = (text or "").strip()
        if not text:
            return {
                "ok": False,
                "error": "empty comment text",
                "action": "skipped",
                "detail": "ไม่มีข้อความคอมเมนต์",
                "join_status": "",
            }
        if not (post_url or "").strip():
            return {
                "ok": False,
                "error": "missing post_url",
                "action": "skipped",
                "detail": "ไม่มีลิงก์โพสต์",
                "join_status": "",
            }

        logger.info("Opening post for comment: {}", post_url)
        try:
            self.page.goto(post_url, wait_until="domcontentloaded", timeout=60_000)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"navigate failed: {exc}",
                "action": "navigate_failed",
                "detail": f"เปิดลิงก์โพสต์ไม่สำเร็จ: {exc}",
                "join_status": "",
            }

        self._human_delay(2.5, 4.5)
        self._dismiss_cookie_banners()
        self._open_original_from_photo_viewer()
        self._human_delay(0.6, 1.2)
        self._dismiss_cookie_banners()

        # Let share shortlinks finish redirecting
        for _ in range(6):
            url_now = self._current_url()
            if self._is_group_post_url(url_now) or self._is_personal_post_url(url_now):
                break
            self._human_delay(0.4, 0.8)

        wrong = self._reject_wrong_target(post_url)
        if wrong:
            return wrong

        block = self._detect_access_block()
        join_btn, _ = self._find_join_button()
        if block or join_btn is not None:
            join_res = self.try_request_join_group()
            self._human_delay(1.5, 3.0)
            self._dismiss_cookie_banners()
            box_after = self._find_comment_box()
            if box_after is None:
                return {
                    "ok": False,
                    "error": join_res.get("error") or "group access required",
                    "action": join_res.get("action") or "join_needed",
                    "detail": join_res.get("detail")
                    or block
                    or "กลุ่มปิด/ต้องเป็นสมาชิก — ยังคอมเมนต์ไม่ได้",
                    "join_status": join_res.get("join_status") or "needed",
                    "join_requested": join_res.get("action")
                    in {"join_requested", "join_pending", "join_clicked"},
                }

        # Scroll so lazy comment composer mounts (inside dialog if present)
        try:
            self.page.mouse.wheel(0, 700)
            self._human_delay(0.7, 1.4)
            self.page.mouse.wheel(0, 500)
            self._human_delay(0.5, 1.0)
        except Exception:  # noqa: BLE001
            pass

        self._dismiss_cookie_banners()
        self._open_comment_composer()
        self._dismiss_cookie_banners()

        wrong = self._reject_wrong_target(post_url)
        if wrong:
            return wrong

        box = self._find_comment_box()
        if box is None:
            try:
                self.page.keyboard.press("End")
                self._human_delay(1.0, 2.0)
            except Exception:  # noqa: BLE001
                pass
            self._dismiss_cookie_banners()
            self._open_comment_composer()
            box = self._find_comment_box()

        if box is None:
            join_res = self.try_request_join_group()
            block = self._detect_access_block()
            return {
                "ok": False,
                "error": "comment box not found",
                "action": join_res.get("action") or "comment_box_missing",
                "detail": (
                    join_res.get("detail")
                    or block
                    or "หาช่องคอมเมนต์ไม่เจอ — อาจเป็นกลุ่มปิด โพสต์ถูกลบ "
                    "หรือลิงก์แบบแชร์เปิดแค่รูป (ลองใส่ลิงก์โพสต์กลุ่มเต็ม ๆ /groups/...)"
                ),
                "join_status": join_res.get("join_status") or "",
                "join_requested": bool(join_res.get("ok")),
            }

        try:
            self._type_comment(box, text)
            self._human_delay(0.5, 1.2)

            wrong = self._reject_wrong_target(post_url)
            if wrong:
                return wrong

            # Prefer Enter to submit; then try Post button if still needed
            try:
                box.press("Enter")
            except Exception:  # noqa: BLE001
                self.page.keyboard.press("Enter")
            self._human_delay(2.0, 3.5)

            for sel in (
                'div[role="dialog"] [aria-label="โพสต์"][role="button"]',
                'div[role="dialog"] [aria-label="Post"][role="button"]',
                '[aria-label="โพสต์"][role="button"]',
                '[aria-label="Post"][role="button"]',
                'div[aria-label="Comment"][role="button"]',
            ):
                btn = self.page.locator(sel).first
                try:
                    if btn.count() > 0 and btn.is_visible():
                        self._safe_click(btn, timeout=1500)
                        self._human_delay(1.5, 2.8)
                        break
                except Exception:  # noqa: BLE001
                    continue

            final_url = self._current_url()
            if self._is_personal_post_url(final_url):
                logger.error("Comment may have hit personal post · {}", final_url)
                return {
                    "ok": False,
                    "error": "commented on personal post",
                    "action": "wrong_target",
                    "detail": (
                        "ตรวจพบว่าหน้าสุดท้ายเป็นโพสต์ส่วนตัว — "
                        "อาจคอมเมนต์ผิดเป้า กรุณาลบคอมเมนต์ด้วยมือถ้ามี "
                        "แล้วใส่ลิงก์โพสต์กลุ่มใหม่"
                    ),
                    "join_status": "",
                    "landed_url": final_url,
                }

            logger.success("Comment submitted (best-effort): {}", text[:80])
            return {
                "ok": True,
                "error": None,
                "action": "commented",
                "detail": f"คอมเมนต์สำเร็จ: {text[:80]}",
                "join_status": "",
                "landed_url": final_url,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"comment failed: {exc}",
                "action": "comment_failed",
                "detail": f"พิมพ์/ส่งคอมเมนต์ไม่สำเร็จ: {exc}",
                "join_status": "",
            }
