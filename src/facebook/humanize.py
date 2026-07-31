"""Human-like browser interactions to reduce Facebook automation fingerprints."""

from __future__ import annotations

import math
import random
import time
from typing import Any

from loguru import logger


def pause(min_s: float = 0.4, max_s: float = 1.2) -> None:
    time.sleep(random.uniform(min_s, max_s))


def _bezier(t: float, p0: float, p1: float, p2: float, p3: float) -> float:
    u = 1.0 - t
    return (u * u * u * p0) + (3 * u * u * t * p1) + (3 * u * t * t * p2) + (t * t * t * p3)


def move_mouse_to(page: Any, x: float, y: float, *, steps: int | None = None) -> None:
    """Curve the cursor toward (x, y) instead of teleporting."""
    try:
        steps = steps or random.randint(12, 28)
        # Approximate current position — Playwright has no get; start from a soft offset.
        sx = max(0.0, x + random.uniform(-180, -40))
        sy = max(0.0, y + random.uniform(-120, 80))
        c1x = sx + (x - sx) * random.uniform(0.2, 0.5) + random.uniform(-40, 40)
        c1y = sy + (y - sy) * random.uniform(0.1, 0.4) + random.uniform(-50, 50)
        c2x = sx + (x - sx) * random.uniform(0.5, 0.85) + random.uniform(-30, 30)
        c2y = sy + (y - sy) * random.uniform(0.5, 0.9) + random.uniform(-30, 30)
        for i in range(1, steps + 1):
            t = i / steps
            # ease-in-out
            te = 0.5 - 0.5 * math.cos(math.pi * t)
            px = _bezier(te, sx, c1x, c2x, x)
            py = _bezier(te, sy, c1y, c2y, y)
            page.mouse.move(px, py)
            time.sleep(random.uniform(0.008, 0.028))
    except Exception as exc:  # noqa: BLE001
        logger.debug("move_mouse_to skipped: {}", exc)


def human_click(page: Any, locator: Any, *, timeout: float = 4000) -> bool:
    """Hover with curved mouse, short pause, then click."""
    try:
        locator.wait_for(state="visible", timeout=timeout)
        box = locator.bounding_box()
        if box:
            tx = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            ty = box["y"] + box["height"] * random.uniform(0.3, 0.7)
            move_mouse_to(page, tx, ty)
            pause(0.15, 0.45)
            page.mouse.click(tx, ty, delay=random.randint(40, 120))
            return True
        locator.click(timeout=timeout, delay=random.randint(40, 120))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("human_click failed: {}", exc)
        try:
            locator.click(timeout=timeout)
            return True
        except Exception:  # noqa: BLE001
            return False


def soft_scroll(page: Any, *, times: int | None = None) -> None:
    """Short feed scroll like a person glancing at the group."""
    n = times if times is not None else random.randint(1, 3)
    for _ in range(n):
        try:
            page.mouse.wheel(0, random.randint(280, 720))
        except Exception:  # noqa: BLE001
            break
        pause(0.45, 1.1)


def type_human(locator: Any, text: str, *, page: Any | None = None) -> bool:
    """Type in uneven bursts with variable key delay."""
    try:
        locator.click(timeout=3000)
        pause(0.2, 0.5)
        i = 0
        while i < len(text):
            chunk = random.randint(2, 9)
            piece = text[i : i + chunk]
            locator.type(piece, delay=random.randint(18, 55))
            i += chunk
            if random.random() < 0.18:
                pause(0.12, 0.4)
            if random.random() < 0.04 and page is not None:
                # rare tiny mouse wiggle
                try:
                    page.mouse.move(
                        random.uniform(200, 600),
                        random.uniform(200, 500),
                    )
                except Exception:  # noqa: BLE001
                    pass
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("type_human failed: {}", exc)
        try:
            locator.fill(text)
            return True
        except Exception:  # noqa: BLE001
            return False
