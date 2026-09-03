#!/usr/bin/env python3
"""In-memory login brute-force rate limiter (single-machine Hub)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

# Policy: 5 failures / 10 minutes → lockout ~15 minutes
WINDOW_SEC = 10 * 60
MAX_FAILURES = 5
LOCKOUT_SEC = 15 * 60


@dataclass
class _Bucket:
    failures: list[float] = field(default_factory=list)
    locked_until: float = 0.0


_LOCK = threading.RLock()
_BUCKETS: dict[str, _Bucket] = {}


def rate_limit_key(*, ip: str, username: str = "") -> str:
    """Key by client IP; username normalized only as secondary salt (no enumeration)."""
    ip_n = (ip or "").strip() or "unknown"
    # Do not key solely by username — avoids username existence probes via timing of lockouts alone.
    return f"ip:{ip_n}"


def _purge_old(bucket: _Bucket, *, now: float) -> None:
    cutoff = now - WINDOW_SEC
    bucket.failures = [t for t in bucket.failures if t >= cutoff]
    if bucket.locked_until and bucket.locked_until <= now:
        bucket.locked_until = 0.0


def check_login_allowed(*, ip: str, username: str = "", now: float | None = None) -> dict[str, Any]:
    """Return {allowed, retry_after_sec}. Never indicates whether username exists."""
    now = time.time() if now is None else float(now)
    key = rate_limit_key(ip=ip, username=username)
    with _LOCK:
        bucket = _BUCKETS.setdefault(key, _Bucket())
        _purge_old(bucket, now=now)
        if bucket.locked_until > now:
            return {
                "allowed": False,
                "retry_after_sec": int(max(1, bucket.locked_until - now)),
                "reason": "rate_limited",
            }
        return {"allowed": True, "retry_after_sec": 0, "reason": ""}


def record_login_failure(*, ip: str, username: str = "", now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else float(now)
    key = rate_limit_key(ip=ip, username=username)
    with _LOCK:
        bucket = _BUCKETS.setdefault(key, _Bucket())
        _purge_old(bucket, now=now)
        bucket.failures.append(now)
        if len(bucket.failures) >= MAX_FAILURES:
            bucket.locked_until = now + LOCKOUT_SEC
            bucket.failures = []
            return {
                "locked": True,
                "retry_after_sec": LOCKOUT_SEC,
                "failures_in_window": MAX_FAILURES,
            }
        return {
            "locked": False,
            "retry_after_sec": 0,
            "failures_in_window": len(bucket.failures),
        }


def record_login_success(*, ip: str, username: str = "", now: float | None = None) -> None:
    now = time.time() if now is None else float(now)
    key = rate_limit_key(ip=ip, username=username)
    with _LOCK:
        bucket = _BUCKETS.setdefault(key, _Bucket())
        bucket.failures = []
        bucket.locked_until = 0.0


def reset_all_for_tests() -> None:
    with _LOCK:
        _BUCKETS.clear()
