"""Facebook Group posting automation."""

from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from loguru import logger
from playwright.sync_api import Page

from config.settings import settings


class FacebookGroupPoster:
    """Upload images and publish property posts to a Facebook Group."""

    def __init__(self, page: Page, image_cache_dir: Path | None = None) -> None:
        self.page = page
        self.image_cache_dir = image_cache_dir or settings.IMAGE_CACHE_DIR
        self.image_cache_dir.mkdir(parents=True, exist_ok=True)

    def _human_delay(self, min_s: float = 1.0, max_s: float = 2.5) -> None:
        time.sleep(random.uniform(min_s, max_s))

    def _download_image(self, url: str, property_id: str) -> Path | None:
        try:
            parsed = urlparse(url)
            suffix = Path(parsed.path).suffix or ".jpg"
            dest = self.image_cache_dir / f"{property_id}_{hash(url) & 0xFFFFFFFF}{suffix}"

            if dest.exists():
                return dest

            response = requests.get(url, timeout=30)
            response.raise_for_status()
            dest.write_bytes(response.content)
            logger.debug("Cached image: {}", dest.name)
            return dest
        except requests.RequestException as exc:
            logger.error("Failed to download {}: {}", url, exc)
            return None

    def _resolve_image_paths(
        self, image_urls: list[str], property_id: str
    ) -> list[Path]:
        paths: list[Path] = []
        for item in image_urls:
            if item.startswith(("http://", "https://")):
                cached = self._download_image(item, property_id)
                if cached:
                    paths.append(cached)
            else:
                local = Path(item)
                if local.exists():
                    paths.append(local)
                else:
                    logger.warning("Local image not found: {}", item)
        return paths

    def navigate_to_group(self, group_url: str) -> None:
        logger.info("Navigating to group: {}", group_url)
        self.page.goto(group_url, wait_until="domcontentloaded")
        self._human_delay(2.0, 4.0)

    def post_to_group(
        self,
        caption: str,
        image_urls: list[str],
        property_id: str = "property",
        group_url: str | None = None,
    ) -> bool:
        """
        Create a new group post with images and caption.

        Args:
            caption: Full post text (Below Market Value, yield highlights, etc.)
            image_urls: Remote URLs or local file paths
            property_id: Used for image cache naming
            group_url: Target group; uses settings default if omitted
        """
        group_url = group_url or settings.FACEBOOK_GROUP_URL
        if not group_url:
            raise ValueError("FACEBOOK_GROUP_URL is not configured")

        image_paths = self._resolve_image_paths(image_urls, property_id)
        if not image_paths:
            logger.error("No valid images for property {}", property_id)
            return False

        self.navigate_to_group(group_url)

        # Open composer — Facebook UI varies; try common selectors
        composer_triggers = [
            'div[role="button"]:has-text("เขียนอะไรสักหน่อย")',
            'div[role="button"]:has-text("Write something")',
            '[aria-label="สร้างโพสต์สาธารณะ"]',
            '[aria-label="Create a public post"]',
        ]

        opened = False
        for selector in composer_triggers:
            locator = self.page.locator(selector).first
            if locator.count() > 0:
                locator.click()
                opened = True
                break

        if not opened:
            logger.error("Could not open group post composer")
            return False

        self._human_delay(1.5, 3.0)

        # Upload photos
        file_input = self.page.locator('input[type="file"]').first
        file_input.set_input_files([str(p) for p in image_paths])
        self._human_delay(3.0, 6.0)

        # Type caption
        textbox_selectors = [
            '[role="textbox"][contenteditable="true"]',
            'div[aria-label="สร้างโพสต์สาธารณะ"]',
            'div[aria-label="Create a public post"]',
        ]

        for selector in textbox_selectors:
            textbox = self.page.locator(selector).first
            if textbox.count() > 0:
                textbox.click()
                self._human_delay(0.5, 1.0)
                textbox.fill(caption)
                break
        else:
            logger.error("Could not find caption textbox")
            return False

        self._human_delay(1.0, 2.0)

        # Submit post
        post_buttons = [
            'div[aria-label="โพสต์"]',
            'div[aria-label="Post"]',
            'span:has-text("โพสต์")',
            'span:has-text("Post")',
        ]

        for selector in post_buttons:
            btn = self.page.locator(selector).first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                self._human_delay(4.0, 8.0)
                logger.success("Posted property {} to group", property_id)
                return True

        logger.error("Could not find Post button")
        return False


def process_property_batch(
    properties: list[dict[str, Any]],
    page: Page,
    max_posts: int | None = None,
) -> list[dict[str, Any]]:
    """Post a batch of properties and return results."""
    from src.sheets.client import mark_property_status

    max_posts = max_posts or settings.MAX_POSTS_PER_RUN
    poster = FacebookGroupPoster(page)
    results: list[dict[str, Any]] = []

    for prop in properties[:max_posts]:
        prop_id = prop.get("row_id", "unknown")
        logger.info("Posting property: {} — {}", prop_id, prop.get("title", ""))

        success = poster.post_to_group(
            caption=prop["caption"],
            image_urls=prop["image_urls"],
            property_id=str(prop_id),
            group_url=prop.get("group_url"),
        )

        status = "posted" if success else "failed"
        try:
            mark_property_status(prop["row_index"], status)
        except Exception as exc:
            logger.warning("Could not update sheet status for row {}: {}", prop["row_index"], exc)

        results.append({**prop, "post_success": success, "final_status": status})

        # Rate limiting between posts
        time.sleep(random.uniform(30, 90))

    return results
