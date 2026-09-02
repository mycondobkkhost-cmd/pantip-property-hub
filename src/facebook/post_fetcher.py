"""Fetch full Facebook post caption + gallery images via logged-in Playwright page."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

from loguru import logger
from playwright.sync_api import Page


class FacebookPostFetcher:
    """Open a Page/profile post while logged in and extract original text + photos."""

    def __init__(self, page: Page) -> None:
        self.page = page

    def _safe_click(self, loc, *, timeout: int = 2500) -> bool:
        try:
            if loc.count() <= 0:
                return False
        except Exception:  # noqa: BLE001
            return False
        try:
            loc.scroll_into_view_if_needed(timeout=timeout)
        except Exception:  # noqa: BLE001
            pass
        for force in (False, True):
            try:
                loc.click(timeout=timeout, force=force)
                return True
            except Exception:  # noqa: BLE001
                continue
        try:
            loc.evaluate("el => el.click()")
            return True
        except Exception:  # noqa: BLE001
            return False

    def _expand_see_more(self) -> None:
        labels = (
            "See more",
            "ดูเพิ่มเติม",
            "See More",
            "อ่านเพิ่มเติม",
            "Continue reading",
        )
        for _ in range(4):
            clicked = False
            for label in labels:
                locs = self.page.locator(
                    f'div[role="button"]:has-text("{label}"), span:has-text("{label}"), '
                    f'[aria-label="{label}"]'
                )
                try:
                    n = min(locs.count(), 6)
                except Exception:  # noqa: BLE001
                    n = 0
                for i in range(n):
                    loc = locs.nth(i)
                    try:
                        if not loc.is_visible():
                            continue
                        txt = (loc.inner_text(timeout=800) or "").strip()
                        if label.lower() not in txt.lower() and label not in txt:
                            continue
                        if self._safe_click(loc, timeout=1500):
                            clicked = True
                            time.sleep(0.4)
                    except Exception:  # noqa: BLE001
                        continue
            if not clicked:
                break

    def _open_post_from_share(self) -> None:
        for label in ("ดูโพสต์", "See post", "Open post", "ไปที่โพสต์", "ดูโพสต์ต้นฉบับ"):
            loc = self.page.locator(
                f'a:has-text("{label}"), div[role="link"]:has-text("{label}"), '
                f'span:has-text("{label}"), [aria-label="{label}"]'
            ).first
            try:
                if loc.count() > 0 and loc.is_visible():
                    self._safe_click(loc, timeout=2000)
                    time.sleep(1.2)
                    return
            except Exception:  # noqa: BLE001
                continue

    def fetch(self, url: str, *, limit_images: int = 12) -> dict[str, Any]:
        url = (url or "").strip()
        if not url.startswith("http"):
            return {"ok": False, "error": "URL ไม่ถูกต้อง", "caption": "", "image_urls": []}

        warnings: list[str] = []
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"เปิดลิงก์ไม่ได้: {exc}", "caption": "", "image_urls": []}

        time.sleep(1.5)
        if "/share/" in (self.page.url or "").lower():
            self._open_post_from_share()
            time.sleep(1.0)

        self._expand_see_more()
        time.sleep(0.5)

        try:
            payload = self.page.evaluate(
                """() => {
                  const clean = (s) => (s || '').replace(/\\u200b/g, '').replace(/[ \\t]+$/gm, '').trim();
                  const bad = (t) => {
                    const s = (t || '').trim();
                    if (!s || s.length < 40) return true;
                    if (/^(Log In|Sign Up|เข้าสู่ระบบ|สมัครใช้งาน)/i.test(s)) return true;
                    if (/cookie|คุกกี้/i.test(s) && s.length < 120) return true;
                    return false;
                  };
                  const pickText = () => {
                    const nodes = [
                      ...document.querySelectorAll('[data-ad-preview="message"]'),
                      ...document.querySelectorAll('[data-ad-comet-preview="message"]'),
                      ...document.querySelectorAll('div[data-ad-rendering-role="story_message"]'),
                      ...document.querySelectorAll('div[dir="auto"]'),
                    ];
                    let best = '';
                    for (const n of nodes) {
                      const t = clean(n.innerText || n.textContent || '');
                      if (bad(t)) continue;
                      if (t.length > best.length) best = t;
                    }
                    if (!best) {
                      const art = document.querySelector('[role="article"]') || document.querySelector('[role="dialog"]');
                      if (art) best = clean(art.innerText || '');
                    }
                    // Prefer first long block that looks like a listing
                    if (best.length > 4000) best = best.slice(0, 4000);
                    return best;
                  };
                  const imgScores = [];
                  const seen = new Set();
                  const push = (src) => {
                    if (!src || !src.startsWith('http')) return;
                    if (!/scontent|fbcdn/i.test(src)) return;
                    if (/static\\.xx\\.fbcdn|rsrc\\.php|emoji\\.php|p32x32|p50x50|_s\\.jpg/i.test(src)) return;
                    const m = src.match(/(\\d{10,})/g);
                    const key = m && m.length ? m.sort((a,b)=>b.length-a.length)[0] : src.split('?')[0];
                    if (seen.has(key)) return;
                    seen.add(key);
                    let score = 0;
                    if (/_n\\.(jpe?g|png)/i.test(src)) score += 5;
                    if (/t39\\.30808|\\/v\\/t39\\./i.test(src)) score += 3;
                    const sm = src.match(/s(\\d{3,4})x(\\d{3,4})/i);
                    if (sm) score += Math.min(+sm[1], +sm[2]) / 100;
                    imgScores.push({ src, score, key });
                  };
                  document.querySelectorAll('img').forEach((img) => {
                    push(img.currentSrc || img.src || '');
                    const ss = img.getAttribute('srcset') || '';
                    ss.split(',').forEach((part) => push((part.trim().split(/\\s+/)[0] || '')));
                  });
                  // background images in style attrs
                  document.querySelectorAll('[style*="background"]').forEach((el) => {
                    const st = el.getAttribute('style') || '';
                    const m = st.match(/url\\((["']?)(https:[^)'"]+)\\1\\)/i);
                    if (m) push(m[2]);
                  });
                  imgScores.sort((a, b) => b.score - a.score);
                  const images = [];
                  const keys = new Set();
                  for (const it of imgScores) {
                    if (keys.has(it.key)) continue;
                    keys.add(it.key);
                    images.push(it.src);
                    if (images.length >= 12) break;
                  }
                  return { caption: pickText(), images, href: location.href || '' };
                }"""
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"อ่านหน้าโพสไม่ได้: {exc}", "caption": "", "image_urls": []}

        caption = str((payload or {}).get("caption") or "").strip()
        images = [str(x).strip() for x in ((payload or {}).get("images") or []) if str(x).strip()]
        final_url = str((payload or {}).get("href") or self.page.url or url).strip()

        # Soft cleanup: drop trailing UI chrome lines if any
        if caption:
            lines = [ln.rstrip() for ln in caption.splitlines()]
            while lines and re.match(
                r"^(Like|Comment|Share|ถูกใจ|แสดงความคิดเห็น|แชร์|All reactions).*$",
                lines[-1],
                re.I,
            ):
                lines.pop()
            caption = "\n".join(lines).strip()

        if not caption:
            warnings.append("ยังดึงข้อความไม่ได้ครบ — ลองเปิดลิงก์คัดลอกเอง")
        if not images:
            warnings.append("ยังดึงรูปจากโพสไม่ได้ — อัปเองได้")

        limit = max(1, min(int(limit_images or 12), 12))
        images = images[:limit]
        ok = bool(caption or images)
        logger.info(
            "FB post fetch · ok={} · caption_len={} · images={} · url={}",
            ok,
            len(caption),
            len(images),
            (final_url or url)[:80],
        )
        return {
            "ok": ok,
            "caption": caption,
            "image_urls": images,
            "final_url": final_url,
            "warnings": warnings,
            "error": "" if ok else "ดึงต้นฉบับจากโพสไม่ได้",
        }

    def download_images_as_bytes(
        self,
        image_urls: list[str],
        *,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Download image bytes using the browser context (cookies)."""
        out: list[dict[str, Any]] = []
        for raw in (image_urls or [])[: max(1, min(int(limit or 12), 12))]:
            u = str(raw or "").strip()
            if not u.startswith("http"):
                continue
            try:
                resp = self.page.request.get(u, timeout=30000)
                if not resp.ok:
                    continue
                body = resp.body()
                if not body or len(body) < 800:
                    continue
                ctype = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    ctype = "image/jpeg"
                name = urlparse(u).path.rsplit("/", 1)[-1] or "photo.jpg"
                if "." not in name:
                    name += ".jpg"
                out.append({"name": name[:80], "content_type": ctype, "data": body})
            except Exception as exc:  # noqa: BLE001
                logger.debug("download image failed: {} · {}", u[:60], exc)
                continue
        return out
