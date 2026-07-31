"""Temporary image uploads for publish campaigns (purged after TTL)."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOAD_DIR = BASE_DIR / "data" / "publish_uploads"
_LOCK = threading.Lock()
BANGKOK = ZoneInfo("Asia/Bangkok")
TTL_DAYS = 7
MAX_BYTES = 8 * 1024 * 1024  # 8MB per file
MAX_FILES_PER_BATCH = 12
ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def _now() -> datetime:
    return datetime.now(tz=BANGKOK)


def ensure_dir() -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR


def purge_expired(*, max_age_days: int = TTL_DAYS) -> int:
    """Delete files older than max_age_days. Returns count removed."""
    ensure_dir()
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    with _LOCK:
        for p in UPLOAD_DIR.iterdir():
            if not p.is_file():
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
    return removed


def save_upload(
    data: bytes,
    *,
    filename: str = "",
    content_type: str = "",
) -> dict[str, Any]:
    if not data:
        raise ValueError("ไฟล์ว่าง")
    if len(data) > MAX_BYTES:
        raise ValueError(f"ไฟล์ใหญ่เกิน {MAX_BYTES // (1024 * 1024)}MB")
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        if "png" in (content_type or "").lower():
            ext = ".png"
        elif "webp" in (content_type or "").lower():
            ext = ".webp"
        elif "gif" in (content_type or "").lower():
            ext = ".gif"
        else:
            ext = ".jpg"
    ensure_dir()
    purge_expired()
    digest = hashlib.sha256(data).hexdigest()[:12]
    name = f"{_now().strftime('%Y%m%d')}_{secrets.token_hex(4)}_{digest}{ext}"
    path = UPLOAD_DIR / name
    with _LOCK:
        path.write_bytes(data)
    # Public path served by Hub under /api/publish-uploads/<name>
    return {
        "ok": True,
        "id": name,
        "url": f"/api/publish-uploads/{name}",
        "bytes": len(data),
        "expires_at": (_now() + timedelta(days=TTL_DAYS)).strftime("%Y-%m-%d"),
    }


def resolve_file(name: str) -> Path | None:
    safe = Path(name or "").name
    if not safe or ".." in safe or "/" in safe:
        return None
    path = UPLOAD_DIR / safe
    if path.is_file():
        return path
    return None
