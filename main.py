#!/usr/bin/env python3
"""
Pantip Property — Facebook Group Auto-Poster
=============================================
Automates property listing posts from Google Sheets to Facebook Groups.

Usage:
    python main.py              # Run scheduler (24/7 mode)
    python main.py --once       # Single posting run
    python main.py --login      # Login only (setup session / 2FA)
    python main.py --fetch      # Test Google Sheets connection
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from loguru import logger

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings  # noqa: E402
from src.facebook.auth import FacebookAuth  # noqa: E402
from src.facebook.poster import process_property_batch  # noqa: E402
from src.scheduler.runner import run_posting_job, run_scheduler  # noqa: E402
from src.sheets.client import fetch_properties_from_sheets  # noqa: E402


def setup_logging() -> None:
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")
    logger.add(
        settings.LOGS_DIR / "pantip_property_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
    )


# ---------------------------------------------------------------------------
# Core functions (also available as module-level API)
# ---------------------------------------------------------------------------


def connect_and_fetch_sheets(only_pending: bool = True) -> list[dict]:
    """Connect to Google Sheets and return property rows."""
    return fetch_properties_from_sheets(only_pending=only_pending)


def login_facebook(headless: bool | None = None) -> None:
    """
  Login to Facebook and persist session.

  Cookie/Session best practices:
    - First run: set HEADLESS=false, complete 2FA manually in the browser.
    - Session is stored in cookies/facebook_session/ (Chromium profile).
    - Backup cookies exported to cookies/facebook_cookies.json.
    - Avoid deleting the profile between runs.
    - Keep posting frequency low (POST_INTERVAL_MINUTES >= 60).
    - Use the same machine/IP consistently.
    """
    auth = FacebookAuth(headless=headless)
    try:
        auth.login()
        logger.success("Session ready — you can now run with HEADLESS=true if desired")
    finally:
        auth.close()


def post_properties_once(max_posts: int | None = None) -> None:
    """Fetch pending properties and post them in a single run."""
    properties = connect_and_fetch_sheets(only_pending=True)
    if not properties:
        logger.info("Nothing to post")
        return

    auth = FacebookAuth()
    try:
        page = auth.login()
        process_property_batch(properties, page, max_posts=max_posts)
    finally:
        auth.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    setup_logging()

    parser = argparse.ArgumentParser(description="Pantip Property Facebook Auto-Poster")
    parser.add_argument("--once", action="store_true", help="Run one posting cycle and exit")
    parser.add_argument("--login", action="store_true", help="Login only (session setup)")
    parser.add_argument("--fetch", action="store_true", help="Test Google Sheets fetch")
    parser.add_argument("--max-posts", type=int, default=None, help="Limit posts per run")
    args = parser.parse_args()

    if args.fetch:
        props = connect_and_fetch_sheets(only_pending=False)
        logger.info("Fetched {} total rows", len(props))
        for p in props[:5]:
            logger.info("  [{}] {} — {} images", p["row_id"], p["title"], len(p["image_urls"]))
        return

    if args.login:
        login_facebook(headless=False)
        return

    if args.once:
        post_properties_once(max_posts=args.max_posts)
        return

    run_scheduler()


if __name__ == "__main__":
    main()
