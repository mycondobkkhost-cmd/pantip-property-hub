"""Facebook group publish job queue (property × group × FB account)."""

from __future__ import annotations

import json
import random
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from src.hub import publish_policy as policy

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORE_PATH = BASE_DIR / "data" / "group_publish_jobs.json"
_LOCK = threading.Lock()
BANGKOK = ZoneInfo("Asia/Bangkok")

STATUS_PENDING = "pending"
STATUS_DUE = "due"
STATUS_POSTED = "posted"
STATUS_FAILED = "failed"
STATUS_RESTRICTED = "restricted"
STATUS_CANCELLED = "cancelled"
STATUS_AWAITING_JOIN = "awaiting_join"

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)


def _now() -> datetime:
    return datetime.now(tz=BANGKOK)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return secrets.token_hex(8)


def _default_store() -> dict[str, Any]:
    return {"jobs": [], "group_last_post": {}, "updated_at": _now_iso()}


def _load_raw() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return _default_store()
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_store()
    if not isinstance(data, dict):
        return _default_store()
    if not isinstance(data.get("jobs"), list):
        data["jobs"] = []
    if not isinstance(data.get("group_last_post"), dict):
        data["group_last_post"] = {}
    return data


def _save_raw(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


def normalize_group_url(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("www.") or s.startswith("facebook.com") or s.startswith("m.facebook.com"):
        s = "https://" + s
    try:
        p = urlparse(s)
    except ValueError:
        return s
    host = (p.netloc or "").lower().replace("www.", "").replace("m.", "")
    if "facebook.com" not in host and "fb.com" not in host:
        return s
    path = re.sub(r"/+$", "", p.path or "")
    return f"https://www.facebook.com{path}"


def sanitize_caption_no_links(text: str) -> str:
    """Strip http(s) URLs; keep LINE ID / phone text."""
    out = _URL_RE.sub("", text or "")
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _normalize_job(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    jid = str(raw.get("id") or "").strip() or _new_id()
    code = str(raw.get("property_code") or "").strip().upper()
    group_url = normalize_group_url(str(raw.get("group_url") or ""))
    if not code or not group_url:
        return None
    images = raw.get("image_urls") or []
    if not isinstance(images, list):
        images = []
    images = [str(x).strip() for x in images if str(x).strip()]
    status = str(raw.get("status") or STATUS_PENDING).strip() or STATUS_PENDING
    return {
        "id": jid,
        "property_code": code,
        "group_url": group_url,
        "group_name": str(raw.get("group_name") or "").strip(),
        "fb_account_id": str(raw.get("fb_account_id") or "").strip(),
        "agent_id": str(raw.get("agent_id") or "owner").strip() or "owner",
        "caption": sanitize_caption_no_links(str(raw.get("caption") or "")),
        "image_urls": images[:12],
        "status": status,
        "next_post_at": str(raw.get("next_post_at") or ""),
        "posted_at": str(raw.get("posted_at") or ""),
        "permalink": str(raw.get("permalink") or ""),
        "error": str(raw.get("error") or ""),
        "action": str(raw.get("action") or ""),
        "detail": str(raw.get("detail") or ""),
        "created_at": str(raw.get("created_at") or _now_iso()),
        "updated_at": str(raw.get("updated_at") or _now_iso()),
        "campaign_id": str(raw.get("campaign_id") or "").strip(),
        "needs_manual_join": bool(raw.get("needs_manual_join")),
        "join_status": str(raw.get("join_status") or "").strip(),
    }


def list_jobs(
    *,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load_raw()
    out: list[dict[str, Any]] = []
    for raw in data.get("jobs") or []:
        job = _normalize_job(raw) if isinstance(raw, dict) else None
        if not job:
            continue
        if agent_id and job["agent_id"] != agent_id:
            continue
        if status and job["status"] != status:
            continue
        out.append(job)
    out.sort(key=lambda j: (j.get("next_post_at") or "", j.get("created_at") or ""))
    return out[: max(1, min(int(limit or 200), 1000))]


def get_job(job_id: str) -> dict[str, Any] | None:
    want = (job_id or "").strip()
    if not want:
        return None
    for job in list_jobs(limit=2000):
        if job["id"] == want:
            return job
    return None


def _posts_today_for_account(jobs: list[dict], account_id: str, *, today: str) -> int:
    n = 0
    for j in jobs:
        if j.get("fb_account_id") != account_id:
            continue
        if j.get("status") != STATUS_POSTED:
            continue
        posted = str(j.get("posted_at") or "")
        if posted.startswith(today):
            n += 1
    return n


def create_campaign(
    *,
    property_code: str,
    groups: list[dict[str, Any]],
    caption: str,
    image_urls: list[str],
    agent_id: str = "owner",
    fb_accounts: list[dict[str, Any]] | None = None,
    schedule_spread: bool = True,
    start_at: str | None = None,
    caption_variants: list[str] | None = None,
    vary_captions: bool = True,
) -> dict[str, Any]:
    """Create one job per group, assign accounts round-robin, schedule next_post_at."""
    code = (property_code or "").strip().upper()
    if not code:
        raise ValueError("ต้องระบุรหัสทรัพย์")
    caption_clean = sanitize_caption_no_links(caption)
    if not caption_clean:
        raise ValueError("ต้องมีข้อความโพส (ไม่มีลิงก์)")
    imgs = [str(x).strip() for x in (image_urls or []) if str(x).strip()]
    if not imgs:
        raise ValueError("ต้องมีอย่างน้อย 1 รูป")

    variants = [sanitize_caption_no_links(str(v)) for v in (caption_variants or []) if str(v).strip()]
    if not variants:
        variants = [caption_clean]

    clean_groups: list[dict[str, str]] = []
    seen: set[str] = set()
    for g in groups or []:
        if not isinstance(g, dict):
            continue
        url = normalize_group_url(str(g.get("url") or g.get("group_url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        clean_groups.append(
            {
                "url": url,
                "name": str(g.get("name") or g.get("group_name") or "").strip(),
            }
        )
    if not clean_groups:
        raise ValueError("ต้องเลือกอย่างน้อย 1 กลุ่ม")

    accounts = [a for a in (fb_accounts or []) if isinstance(a, dict) and str(a.get("id") or "").strip()]
    if not accounts:
        accounts = [{"id": "default", "label": "บัญชีปัจจุบัน", "daily_cap": policy.DEFAULT_DAILY_CAP}]

    campaign_id = _new_id()
    created: list[dict[str, Any]] = []
    # Optional fixed start; else now
    if start_at and str(start_at).strip():
        try:
            cursor = datetime.strptime(str(start_at).strip()[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=BANGKOK)
        except ValueError:
            try:
                cursor = datetime.strptime(str(start_at).strip()[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=BANGKOK)
            except ValueError:
                cursor = _now()
    else:
        cursor = _now()

    with _LOCK:
        data = _load_raw()
        jobs = [x for x in (data.get("jobs") or []) if isinstance(x, dict)]
        last_map = data.get("group_last_post") if isinstance(data.get("group_last_post"), dict) else {}
        today = _now().strftime("%Y-%m-%d")

        usable = []
        for acc in accounts:
            if policy.account_is_paused(acc):
                continue
            aid = str(acc.get("id") or "")
            posted = 0
            for j in jobs:
                if str(j.get("fb_account_id") or "") != aid:
                    continue
                if str(j.get("status") or "") != STATUS_POSTED:
                    continue
                if str(j.get("posted_at") or "").startswith(today):
                    posted += 1
            cap = policy.effective_daily_cap(acc)
            if posted < cap:
                usable.append(acc)
        if not usable:
            usable = [a for a in accounts if not policy.account_is_paused(a)] or accounts

        try:
            from src.hub.publish_caption import micro_vary_caption
        except Exception:  # noqa: BLE001
            micro_vary_caption = None  # type: ignore[assignment]

        rr = 0
        for gi, g in enumerate(clean_groups):
            last_at = str(last_map.get(f"{usable[rr % len(usable)].get('id')}|{g['url']}") or last_map.get(g["url"]) or "")
            if last_at and not policy.group_cooldown_ok(last_at):
                pass
            acc = usable[rr % len(usable)]
            rr += 1
            if schedule_spread:
                cursor = policy.schedule_next_slot(after=cursor, account=acc)
                next_at = cursor.strftime("%Y-%m-%d %H:%M:%S")
            else:
                next_at = cursor.strftime("%Y-%m-%d %H:%M:%S") if gi == 0 else _now_iso()

            base_cap = variants[gi % len(variants)]
            if vary_captions and micro_vary_caption:
                try:
                    job_caption = micro_vary_caption(
                        base_cap, property_code=code, group_url=g["url"], index=gi
                    ) or base_cap
                except Exception:  # noqa: BLE001
                    job_caption = base_cap
            else:
                job_caption = base_cap

            job = {
                "id": _new_id(),
                "property_code": code,
                "group_url": g["url"],
                "group_name": g["name"],
                "fb_account_id": str(acc.get("id") or ""),
                "agent_id": (agent_id or "owner").strip() or "owner",
                "caption": job_caption,
                "image_urls": imgs[:12],
                "status": STATUS_PENDING,
                "next_post_at": next_at,
                "posted_at": "",
                "permalink": "",
                "error": "",
                "action": "",
                "detail": "",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "campaign_id": campaign_id,
                "needs_manual_join": False,
                "join_status": "",
            }
            jobs.append(job)
            created.append(_normalize_job(job) or job)

        data["jobs"] = jobs
        _save_raw(data)

    return {
        "ok": True,
        "campaign_id": campaign_id,
        "created": len(created),
        "jobs": created,
    }


def list_due(
    *,
    agent_id: str | None = None,
    limit: int = 5,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or _now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    due: list[dict[str, Any]] = []
    for job in list_jobs(agent_id=agent_id, limit=2000):
        if job["status"] not in {STATUS_PENDING, STATUS_DUE, STATUS_FAILED, STATUS_AWAITING_JOIN}:
            continue
        nxt = job.get("next_post_at") or ""
        if nxt and nxt > now_s and job["status"] != STATUS_DUE:
            continue
        due.append(job)
    due.sort(key=lambda j: (j.get("next_post_at") or "", j.get("created_at") or ""))
    return due[: max(1, min(int(limit or 5), 20))]


def mark_result(
    job_id: str,
    *,
    ok: bool,
    permalink: str = "",
    error: str = "",
    action: str = "",
    detail: str = "",
    join_status: str = "",
    needs_manual_join: bool | None = None,
    retry_minutes: int | None = None,
) -> dict[str, Any]:
    want = (job_id or "").strip()
    if not want:
        raise ValueError("missing job id")
    with _LOCK:
        data = _load_raw()
        jobs = data.get("jobs") or []
        found = None
        for i, raw in enumerate(jobs):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("id") or "") != want:
                continue
            if ok:
                raw["status"] = STATUS_POSTED
                raw["posted_at"] = _now_iso()
                raw["permalink"] = (permalink or "").strip()
                raw["error"] = ""
                raw["action"] = action or "posted"
                raw["detail"] = detail or "โพสสำเร็จ"
                raw["needs_manual_join"] = False
                raw["join_status"] = join_status or "joined"
                key = f"{raw.get('fb_account_id')}|{normalize_group_url(str(raw.get('group_url') or ''))}"
                last_map = data.get("group_last_post") if isinstance(data.get("group_last_post"), dict) else {}
                last_map[key] = raw["posted_at"]
                last_map[normalize_group_url(str(raw.get("group_url") or ""))] = raw["posted_at"]
                data["group_last_post"] = last_map
            else:
                act = (action or "").strip()
                if act in {"awaiting_join", "join_pending", "join_requested"} or needs_manual_join:
                    raw["status"] = STATUS_AWAITING_JOIN
                    raw["needs_manual_join"] = bool(needs_manual_join) if needs_manual_join is not None else True
                    raw["join_status"] = join_status or act or "needed"
                    # Recheck later (default 45–90 min) — do not spam join clicks
                    from datetime import timedelta

                    mins = retry_minutes if retry_minutes is not None else random.randint(45, 90)
                    nxt = _now() + timedelta(minutes=max(15, int(mins)))
                    raw["next_post_at"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
                elif act == "restricted" or "restrict" in (error or "").lower():
                    raw["status"] = STATUS_RESTRICTED
                    raw["needs_manual_join"] = False
                    nxt = policy.schedule_next_slot(account=None)
                    raw["next_post_at"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    raw["status"] = STATUS_FAILED
                    raw["needs_manual_join"] = False
                    nxt = policy.schedule_next_slot(account=None)
                    raw["next_post_at"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
                raw["error"] = (error or "").strip()
                raw["action"] = act or "failed"
                raw["detail"] = detail or error or "โพสไม่สำเร็จ"
                if join_status:
                    raw["join_status"] = join_status
            raw["updated_at"] = _now_iso()
            jobs[i] = raw
            found = _normalize_job(raw)
            break
        if not found:
            raise ValueError("ไม่พบงานโพส")
        data["jobs"] = jobs
        _save_raw(data)
        return found


def cancel_job(job_id: str) -> bool:
    want = (job_id or "").strip()
    with _LOCK:
        data = _load_raw()
        jobs = data.get("jobs") or []
        for i, raw in enumerate(jobs):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("id") or "") != want:
                continue
            raw["status"] = STATUS_CANCELLED
            raw["updated_at"] = _now_iso()
            jobs[i] = raw
            data["jobs"] = jobs
            _save_raw(data)
            return True
    return False


def stats(*, agent_id: str | None = None) -> dict[str, Any]:
    jobs = list_jobs(agent_id=agent_id, limit=5000)
    today = _now().strftime("%Y-%m-%d")
    by_status: dict[str, int] = {}
    posted_today = 0
    by_account: dict[str, int] = {}
    for j in jobs:
        st = j.get("status") or ""
        by_status[st] = by_status.get(st, 0) + 1
        if st == STATUS_POSTED and str(j.get("posted_at") or "").startswith(today):
            posted_today += 1
            aid = j.get("fb_account_id") or "—"
            by_account[aid] = by_account.get(aid, 0) + 1
    pending = sum(
        by_status.get(s, 0)
        for s in (STATUS_PENDING, STATUS_DUE, STATUS_FAILED, STATUS_AWAITING_JOIN)
    )
    awaiting_join = by_status.get(STATUS_AWAITING_JOIN, 0)
    needs_manual = sum(1 for j in jobs if j.get("needs_manual_join") and j.get("status") == STATUS_AWAITING_JOIN)
    return {
        "total": len(jobs),
        "pending": pending,
        "awaiting_join": awaiting_join,
        "needs_manual_join": needs_manual,
        "posted_today": posted_today,
        "by_status": by_status,
        "by_account_today": by_account,
    }
