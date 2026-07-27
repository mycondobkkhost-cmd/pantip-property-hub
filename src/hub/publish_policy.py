"""Anti-ban pacing policy for Facebook group publishing."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

BANGKOK = ZoneInfo("Asia/Bangkok")

# Defaults aligned with plan (per FB account)
DEFAULT_DAILY_CAP = 15  # warmup start; Hub can raise toward 30–35
DEFAULT_DAILY_CAP_MAX = 35
MIN_DELAY_SEC = 180  # 3 min
MAX_DELAY_SEC = 480  # 8 min
GROUP_COOLDOWN_DAYS = 3
WORK_START_HOUR = 9
WORK_END_HOUR = 21
RESTRICT_PAUSE_HOURS = 48
WARMUP_WEEKLY_GROWTH = 0.30


def now_bkk() -> datetime:
    return datetime.now(tz=BANGKOK)


def _parse_ts(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[:19] if "T" not in text else text, fmt.replace("%z", ""))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BANGKOK)
            return dt.astimezone(BANGKOK)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BANGKOK)
        return dt.astimezone(BANGKOK)
    except ValueError:
        return None


def effective_daily_cap(account: dict[str, Any] | None) -> int:
    row = account or {}
    try:
        cap = int(row.get("daily_cap") or DEFAULT_DAILY_CAP)
    except (TypeError, ValueError):
        cap = DEFAULT_DAILY_CAP
    return max(1, min(cap, DEFAULT_DAILY_CAP_MAX))


def account_is_paused(account: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    row = account or {}
    if bool(row.get("paused")):
        return True
    until = _parse_ts(str(row.get("paused_until") or ""))
    if until and (now or now_bkk()) < until:
        return True
    return False


def random_post_delay_sec(account: dict[str, Any] | None = None) -> float:
    row = account or {}
    try:
        lo = int(row.get("min_delay_sec") or MIN_DELAY_SEC)
    except (TypeError, ValueError):
        lo = MIN_DELAY_SEC
    try:
        hi = int(row.get("max_delay_sec") or MAX_DELAY_SEC)
    except (TypeError, ValueError):
        hi = MAX_DELAY_SEC
    lo = max(60, min(lo, 3600))
    hi = max(lo, min(hi, 7200))
    return random.uniform(float(lo), float(hi))


def schedule_next_slot(
    *,
    after: datetime | None = None,
    delay_sec: float | None = None,
    account: dict[str, Any] | None = None,
) -> datetime:
    """Pick next post time inside the daily work window with random delay."""
    base = after or now_bkk()
    wait = delay_sec if delay_sec is not None else random_post_delay_sec(account)
    candidate = base + timedelta(seconds=float(wait))

    start_h = WORK_START_HOUR
    end_h = WORK_END_HOUR
    row = account or {}
    try:
        start_h = int(row.get("work_start_hour") or WORK_START_HOUR)
    except (TypeError, ValueError):
        pass
    try:
        end_h = int(row.get("work_end_hour") or WORK_END_HOUR)
    except (TypeError, ValueError):
        pass
    start_h = max(0, min(start_h, 23))
    end_h = max(start_h + 1, min(end_h, 24))

    # If outside window, push to next window start + small jitter
    def in_window(dt: datetime) -> bool:
        return start_h <= dt.hour < end_h

    if not in_window(candidate):
        day = candidate.date()
        if candidate.hour >= end_h:
            day = day + timedelta(days=1)
        candidate = datetime(
            day.year,
            day.month,
            day.day,
            start_h,
            random.randint(0, 25),
            random.randint(0, 59),
            tzinfo=BANGKOK,
        )
        candidate += timedelta(seconds=random.uniform(30, 180))
    return candidate


def group_cooldown_ok(
    last_posted_at: str,
    *,
    now: datetime | None = None,
    days: int = GROUP_COOLDOWN_DAYS,
) -> bool:
    last = _parse_ts(last_posted_at)
    if not last:
        return True
    return (now or now_bkk()) >= last + timedelta(days=max(1, int(days)))


def restriction_pause_until(*, hours: int = RESTRICT_PAUSE_HOURS) -> str:
    return (now_bkk() + timedelta(hours=max(1, int(hours)))).strftime("%Y-%m-%d %H:%M:%S")


def bump_warmup_cap(current_cap: int) -> int:
    """Increase daily cap by ~30% week-over-week, capped."""
    try:
        cur = int(current_cap)
    except (TypeError, ValueError):
        cur = DEFAULT_DAILY_CAP
    nxt = int(round(cur * (1.0 + WARMUP_WEEKLY_GROWTH)))
    return max(cur + 1, min(nxt, DEFAULT_DAILY_CAP_MAX))
