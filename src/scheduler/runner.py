"""24/7 scheduling runner."""

from __future__ import annotations

import time

import schedule
from loguru import logger

from config.settings import settings
from src.facebook.auth import FacebookAuth
from src.facebook.poster import process_property_batch
from src.sheets.client import fetch_properties_from_sheets


def run_posting_job() -> None:
    """Single posting cycle: fetch sheet data -> login -> post -> update status."""
    logger.info("=== Starting posting job ===")

    try:
        properties = fetch_properties_from_sheets(only_pending=True)
    except Exception as exc:
        logger.error("Failed to fetch properties: {}", exc)
        return

    if not properties:
        logger.info("No pending properties to post")
        return

    auth = FacebookAuth()
    try:
        page = auth.login()
        results = process_property_batch(properties, page)
        posted = sum(1 for r in results if r.get("post_success"))
        logger.info("Job complete: {}/{} posted", posted, len(results))
    except Exception as exc:
        logger.error("Posting job failed: {}", exc)
    finally:
        auth.close()


def run_scheduler() -> None:
    """Run posting job on interval — suitable for Mac Mini 24/7 operation."""
    interval = settings.POST_INTERVAL_MINUTES
    logger.info("Scheduler started — every {} minutes", interval)

    schedule.every(interval).minutes.do(run_posting_job)
    run_posting_job()  # Run immediately on startup

    while True:
        schedule.run_pending()
        time.sleep(30)
