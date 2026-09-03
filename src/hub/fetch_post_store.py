"""Queue for Agent to fetch full Facebook page-post caption + images (logged-in)."""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORE_PATH = BASE_DIR / "data" / "fetch_post_jobs.json"
_LOCK = threading.Lock()
BANGKOK = ZoneInfo("Asia/Bangkok")

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"


def _now_iso() -> str:
    return datetime.now(tz=BANGKOK).strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return secrets.token_hex(8)


def _default() -> dict[str, Any]:
    return {"jobs": [], "updated_at": _now_iso()}


def _load() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return _default()
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default()
    if not isinstance(data, dict):
        return _default()
    if not isinstance(data.get("jobs"), list):
        data["jobs"] = []
    return data


def _save(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


def enqueue_fetch_post(
    *,
    url: str,
    code: str = "",
    agent_id: str = "owner",
) -> dict[str, Any]:
    url = (url or "").strip()
    if not url.startswith("http"):
        raise ValueError("ต้องมีลิงก์โพสเพจหรือโพสโปรไฟล์")
    code = (code or "").strip().upper()
    agent_id = (agent_id or "owner").strip() or "owner"
    with _LOCK:
        data = _load()
        # Cancel older pending jobs for same code/url
        for j in data["jobs"]:
            if not isinstance(j, dict):
                continue
            if j.get("status") not in (STATUS_PENDING, STATUS_RUNNING):
                continue
            same_code = code and str(j.get("code") or "").upper() == code
            same_url = str(j.get("url") or "").strip() == url
            if same_code or same_url:
                j["status"] = STATUS_CANCELLED
                j["updated_at"] = _now_iso()
        job = {
            "id": _new_id(),
            "status": STATUS_PENDING,
            "code": code,
            "url": url,
            "agent_id": agent_id,
            "caption": "",
            "image_urls": [],
            "image_count": 0,
            "final_url": "",
            "warnings": [],
            "error": "",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        data["jobs"].insert(0, job)
        # Keep last 80 jobs
        data["jobs"] = [j for j in data["jobs"] if isinstance(j, dict)][:80]
        _save(data)
        return dict(job)


def get_fetch_post(job_id: str) -> dict[str, Any] | None:
    want = (job_id or "").strip()
    if not want:
        return None
    with _LOCK:
        data = _load()
        for j in data["jobs"]:
            if isinstance(j, dict) and str(j.get("id") or "") == want:
                return dict(j)
    return None


def list_fetch_post_due(*, agent_id: str = "owner", limit: int = 1) -> list[dict[str, Any]]:
    agent_id = (agent_id or "owner").strip() or "owner"
    limit = max(1, min(int(limit or 1), 3))
    out: list[dict[str, Any]] = []
    with _LOCK:
        data = _load()
        changed = False
        for j in data["jobs"]:
            if not isinstance(j, dict):
                continue
            if j.get("status") != STATUS_PENDING:
                continue
            if str(j.get("agent_id") or "owner") not in (agent_id, "", "any"):
                continue
            j["status"] = STATUS_RUNNING
            j["updated_at"] = _now_iso()
            changed = True
            out.append(dict(j))
            if len(out) >= limit:
                break
        if changed:
            _save(data)
    return out


def mark_fetch_post_result(
    job_id: str,
    *,
    ok: bool,
    caption: str = "",
    image_urls: list[str] | None = None,
    final_url: str = "",
    warnings: list[str] | None = None,
    error: str = "",
) -> dict[str, Any]:
    want = (job_id or "").strip()
    if not want:
        raise ValueError("ต้องระบุ id")
    imgs = [str(x).strip() for x in (image_urls or []) if str(x).strip()][:12]
    with _LOCK:
        data = _load()
        job = None
        for j in data["jobs"]:
            if isinstance(j, dict) and str(j.get("id") or "") == want:
                job = j
                break
        if not job:
            raise ValueError("ไม่พบงานดึงโพส")
        if ok:
            job["status"] = STATUS_DONE
            job["caption"] = (caption or "").strip()
            job["image_urls"] = imgs
            job["image_count"] = len(imgs)
            job["final_url"] = (final_url or "").strip()
            job["warnings"] = [str(w) for w in (warnings or []) if w][:12]
            job["error"] = ""
        else:
            job["status"] = STATUS_FAILED
            job["error"] = (error or "ดึงไม่สำเร็จ").strip()
            job["warnings"] = [str(w) for w in (warnings or []) if w][:12]
        job["updated_at"] = _now_iso()
        _save(data)
        return dict(job)
