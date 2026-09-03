"""Facebook group publish job queue (property × group × FB account)."""

from __future__ import annotations

import hashlib
import json
import random
import re
import secrets
import threading
from datetime import datetime, timedelta
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
STATUS_RUNNING = "running"
STATUS_POSTED = "posted"
STATUS_FAILED = "failed"
STATUS_RESTRICTED = "restricted"
STATUS_CANCELLED = "cancelled"
STATUS_AWAITING_JOIN = "awaiting_join"
STATUS_NEEDS_RECONCILE = "needs_reconcile"

LEASE_SECONDS = 15 * 60
CLAIMABLE_STATUSES = {STATUS_PENDING, STATUS_DUE, STATUS_FAILED, STATUS_AWAITING_JOIN}
TERMINAL_STATUSES = {STATUS_POSTED, STATUS_CANCELLED, STATUS_RESTRICTED, STATUS_NEEDS_RECONCILE}

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


def make_idempotency_key(*, property_id: str, group_url: str, campaign_id: str = "") -> str:
    pid = (property_id or "").strip()
    gurl = normalize_group_url(group_url or "")
    if not pid or not gurl:
        return ""
    raw = f"{pid}|{gurl}|{(campaign_id or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


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
    property_id = str(raw.get("property_id") or "").strip()
    campaign_id = str(raw.get("campaign_id") or "").strip()
    idem = str(raw.get("idempotency_key") or "").strip()
    if not idem and property_id:
        idem = make_idempotency_key(
            property_id=property_id, group_url=group_url, campaign_id=campaign_id
        )
    return {
        "id": jid,
        "property_id": property_id,
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
        "campaign_id": campaign_id,
        "needs_manual_join": bool(raw.get("needs_manual_join")),
        "join_status": str(raw.get("join_status") or "").strip(),
        "idempotency_key": idem,
        "attempt_id": str(raw.get("attempt_id") or "").strip(),
        "attempt_count": int(raw.get("attempt_count") or 0),
        "claimed_at": str(raw.get("claimed_at") or ""),
        "claimed_by": str(raw.get("claimed_by") or ""),
        "lease_until": str(raw.get("lease_until") or ""),
        "external_action_started_at": str(raw.get("external_action_started_at") or ""),
        "external_action_confirmed_at": str(raw.get("external_action_confirmed_at") or ""),
        "external_post_url": str(raw.get("external_post_url") or raw.get("permalink") or ""),
        "last_error_class": str(raw.get("last_error_class") or ""),
        "reconciled_at": str(raw.get("reconciled_at") or ""),
        "reconciliation_action": str(raw.get("reconciliation_action") or ""),
        "reconciled_by": str(raw.get("reconciled_by") or ""),
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
    property_id: str = "",
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
    from src.hub.project_store import load_properties
    from src.hub.property_resolve import resolve_for_action

    props = load_properties()
    resolved = resolve_for_action(
        props,
        property_id=property_id,
        property_code=property_code,
    )
    if not resolved.ok or not resolved.record:
        if resolved.error_code == "PROPERTY_CODE_AMBIGUOUS":
            raise ValueError(
                "รหัสทรัพย์ซ้ำหลายรายการ — ระบุ property_id หรือเลือกทรัพย์จากรายการ"
            )
        raise ValueError("ไม่พบทรัพย์")
    prop = resolved.record
    code = str(prop.get("code") or property_code or "").strip().upper()
    pid = str(prop.get("id") or "").strip()
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
                "property_id": pid,
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
                "idempotency_key": make_idempotency_key(
                    property_id=pid, group_url=g["url"], campaign_id=campaign_id
                ),
                "attempt_id": "",
                "attempt_count": 0,
                "claimed_at": "",
                "claimed_by": "",
                "lease_until": "",
                "external_action_started_at": "",
                "external_action_confirmed_at": "",
                "external_post_url": "",
                "last_error_class": "",
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
    """List claimable due jobs (does NOT claim). Excludes running/needs_reconcile/posted."""
    now = now or _now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    due: list[dict[str, Any]] = []
    for job in list_jobs(agent_id=agent_id, limit=2000):
        if job["status"] not in CLAIMABLE_STATUSES:
            continue
        nxt = job.get("next_post_at") or ""
        if nxt and nxt > now_s and job["status"] != STATUS_DUE:
            continue
        due.append(job)
    due.sort(key=lambda j: (j.get("next_post_at") or "", j.get("created_at") or ""))
    return due[: max(1, min(int(limit or 5), 20))]


def recover_expired_leases(*, now: datetime | None = None) -> dict[str, int]:
    """Expire running leases safely.

    - No external_action_started_at → return to pending (safe retry)
    - external_action_started_at set → needs_reconcile (never blind repost)
    """
    now = now or _now()
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    to_pending = 0
    to_reconcile = 0
    with _LOCK:
        data = _load_raw()
        jobs = data.get("jobs") or []
        changed = False
        for i, raw in enumerate(jobs):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("status") or "") != STATUS_RUNNING:
                continue
            lease = str(raw.get("lease_until") or "")
            if lease and lease > now_s:
                continue
            started = str(raw.get("external_action_started_at") or "").strip()
            if started:
                raw["status"] = STATUS_NEEDS_RECONCILE
                raw["last_error_class"] = "lease_expired_after_external_start"
                raw["detail"] = "lease หมดอายุหลังเริ่มโพส — ต้อง reconcile"
                to_reconcile += 1
            else:
                raw["status"] = STATUS_PENDING
                raw["attempt_id"] = ""
                raw["claimed_at"] = ""
                raw["claimed_by"] = ""
                raw["lease_until"] = ""
                raw["last_error_class"] = "lease_expired_pre_external"
                to_pending += 1
            raw["updated_at"] = _now_iso()
            jobs[i] = raw
            changed = True
        if changed:
            data["jobs"] = jobs
            _save_raw(data)
    return {"requeued_pending": to_pending, "needs_reconcile": to_reconcile}


def claim_due_for_publish(
    *,
    agent_id: str | None = None,
    limit: int = 5,
    now: datetime | None = None,
    claimed_by: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Atomically claim due publish jobs. needs_reconcile / posted never claimed."""
    from src.hub.project_store import load_properties
    from src.hub.property_resolve import resolve_job_property

    now = now or _now()
    recover_expired_leases(now=now)
    props = load_properties()
    blocked = 0
    claimed: list[dict[str, Any]] = []
    claimer = (claimed_by or agent_id or "agent").strip() or "agent"
    limit = max(1, min(int(limit or 5), 20))
    now_s = now.strftime("%Y-%m-%d %H:%M:%S")
    lease_until = (now + timedelta(seconds=LEASE_SECONDS)).strftime("%Y-%m-%d %H:%M:%S")

    with _LOCK:
        data = _load_raw()
        jobs = data.get("jobs") or []
        candidates: list[int] = []
        for i, raw in enumerate(jobs):
            if not isinstance(raw, dict):
                continue
            job = _normalize_job(raw)
            if not job:
                continue
            if agent_id and job["agent_id"] != agent_id:
                continue
            if job["status"] not in CLAIMABLE_STATUSES:
                continue
            nxt = job.get("next_post_at") or ""
            if nxt and nxt > now_s and job["status"] != STATUS_DUE:
                continue
            candidates.append(i)
        candidates.sort(
            key=lambda i: (
                str(jobs[i].get("next_post_at") or ""),
                str(jobs[i].get("created_at") or ""),
            )
        )

        for i in candidates:
            if len(claimed) >= limit:
                break
            raw = jobs[i]
            job = _normalize_job(raw) or {}
            res = resolve_job_property(props, job)
            if not (res.ok and res.record):
                blocked += 1
                # Fail closed: never auto-claim legacy/ambiguous identity jobs.
                raw["status"] = STATUS_NEEDS_RECONCILE
                raw["last_error_class"] = "legacy_or_ambiguous_identity"
                raw["detail"] = "legacy/ambiguous identity — blocked from auto publish"
                raw["updated_at"] = _now_iso()
                jobs[i] = raw
                continue
            pid = str(res.record.get("id") or "")
            code = str(res.record.get("code") or job.get("property_code") or "")
            attempt_id = secrets.token_hex(8)
            idem = make_idempotency_key(
                property_id=pid,
                group_url=str(job.get("group_url") or ""),
                campaign_id=str(job.get("campaign_id") or ""),
            )
            raw["property_id"] = pid
            raw["property_code"] = code
            raw["idempotency_key"] = idem
            raw["status"] = STATUS_RUNNING
            raw["attempt_id"] = attempt_id
            raw["attempt_count"] = int(raw.get("attempt_count") or 0) + 1
            raw["claimed_at"] = now_s
            raw["claimed_by"] = claimer
            raw["lease_until"] = lease_until
            raw["external_action_started_at"] = ""
            raw["external_action_confirmed_at"] = ""
            raw["updated_at"] = _now_iso()
            jobs[i] = raw
            row = _normalize_job(raw) or dict(raw)
            row["identity_status"] = "ok"
            claimed.append(row)

        data["jobs"] = jobs
        _save_raw(data)
    return claimed, blocked


def list_due_for_publish(
    *,
    agent_id: str | None = None,
    limit: int = 5,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Backward-compatible name: atomically claims due jobs (Phase G)."""
    return claim_due_for_publish(agent_id=agent_id, limit=limit, now=now)


def mark_external_action_started(
    job_id: str,
    *,
    attempt_id: str = "",
) -> dict[str, Any]:
    """Mark that Facebook publish action may have begun."""
    want = (job_id or "").strip()
    if not want:
        raise ValueError("missing job id")
    with _LOCK:
        data = _load_raw()
        jobs = data.get("jobs") or []
        for i, raw in enumerate(jobs):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("id") or "") != want:
                continue
            if attempt_id and str(raw.get("attempt_id") or "") and str(raw.get("attempt_id")) != attempt_id:
                raise ValueError("stale attempt_id")
            if str(raw.get("status") or "") != STATUS_RUNNING:
                raise ValueError("job is not running")
            if not str(raw.get("external_action_started_at") or "").strip():
                raw["external_action_started_at"] = _now_iso()
            raw["updated_at"] = _now_iso()
            jobs[i] = raw
            data["jobs"] = jobs
            _save_raw(data)
            return _normalize_job(raw) or dict(raw)
    raise ValueError("ไม่พบงานโพส")


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
    attempt_id: str = "",
    ambiguous: bool = False,
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

            current_status = str(raw.get("status") or "")
            current_attempt = str(raw.get("attempt_id") or "")

            if current_status == STATUS_POSTED:
                found = _normalize_job(raw)
                break

            if attempt_id and current_attempt and attempt_id != current_attempt:
                found = _normalize_job(raw)
                break

            if ok:
                raw["status"] = STATUS_POSTED
                raw["posted_at"] = _now_iso()
                raw["permalink"] = (permalink or "").strip()
                raw["external_post_url"] = raw["permalink"]
                raw["external_action_confirmed_at"] = _now_iso()
                if not str(raw.get("external_action_started_at") or "").strip():
                    raw["external_action_started_at"] = raw["external_action_confirmed_at"]
                raw["error"] = ""
                raw["action"] = action or "posted"
                raw["detail"] = detail or "โพสสำเร็จ"
                raw["needs_manual_join"] = False
                raw["join_status"] = join_status or "joined"
                raw["last_error_class"] = ""
                raw["lease_until"] = ""
                key = f"{raw.get('fb_account_id')}|{normalize_group_url(str(raw.get('group_url') or ''))}"
                last_map = data.get("group_last_post") if isinstance(data.get("group_last_post"), dict) else {}
                last_map[key] = raw["posted_at"]
                last_map[normalize_group_url(str(raw.get("group_url") or ""))] = raw["posted_at"]
                data["group_last_post"] = last_map
            else:
                act = (action or "").strip()
                started = str(raw.get("external_action_started_at") or "").strip()
                if act in {"awaiting_join", "join_pending", "join_requested"} or needs_manual_join:
                    raw["status"] = STATUS_AWAITING_JOIN
                    raw["needs_manual_join"] = bool(needs_manual_join) if needs_manual_join is not None else True
                    raw["join_status"] = join_status or act or "needed"
                    mins = retry_minutes if retry_minutes is not None else random.randint(45, 90)
                    nxt = _now() + timedelta(minutes=max(15, int(mins)))
                    raw["next_post_at"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
                    raw["last_error_class"] = "awaiting_join"
                elif act == "restricted" or "restrict" in (error or "").lower():
                    raw["status"] = STATUS_RESTRICTED
                    raw["needs_manual_join"] = False
                    nxt = policy.schedule_next_slot(account=None)
                    raw["next_post_at"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
                    raw["last_error_class"] = "restricted"
                elif ambiguous or (started and act not in {"switch_failed", "pre_external_failed"}):
                    raw["status"] = STATUS_NEEDS_RECONCILE
                    raw["last_error_class"] = "ambiguous_external_result"
                    raw["detail"] = detail or error or "ผลโพสไม่ชัด — ห้าม retry อัตโนมัติ"
                else:
                    raw["status"] = STATUS_FAILED
                    raw["needs_manual_join"] = False
                    nxt = policy.schedule_next_slot(account=None)
                    raw["next_post_at"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
                    raw["last_error_class"] = "pre_external_failure"
                raw["error"] = (error or "").strip()
                raw["action"] = act or "failed"
                if detail and not (raw.get("detail") and raw["status"] == STATUS_NEEDS_RECONCILE):
                    if raw["status"] != STATUS_NEEDS_RECONCILE:
                        raw["detail"] = detail or error or "โพสไม่สำเร็จ"
                elif raw["status"] != STATUS_NEEDS_RECONCILE:
                    raw["detail"] = detail or error or "โพสไม่สำเร็จ"
                if join_status:
                    raw["join_status"] = join_status
                raw["lease_until"] = ""
            raw["updated_at"] = _now_iso()
            jobs[i] = raw
            found = _normalize_job(raw)
            break
        if not found:
            raise ValueError("ไม่พบงานโพส")
        data["jobs"] = jobs
        _save_raw(data)
        return found


class ReconcileError(Exception):
    """Invalid reconciliation request."""

    def __init__(self, message: str, *, code: str = "invalid", http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


ACTION_CONFIRM_POSTED = "confirm_posted"
ACTION_CONFIRM_NOT_POSTED = "confirm_not_posted"
ACTION_CANCEL = "cancel"
ACTION_KEEP_UNRESOLVED = "keep_unresolved"

RECONCILE_ACTIONS = {
    ACTION_CONFIRM_POSTED,
    ACTION_CONFIRM_NOT_POSTED,
    ACTION_CANCEL,
    ACTION_KEEP_UNRESOLVED,
}


def list_needs_reconcile(*, limit: int = 100) -> list[dict[str, Any]]:
    """Jobs requiring operator attention (never auto-claimable)."""
    jobs = list_jobs(status=STATUS_NEEDS_RECONCILE, limit=max(1, min(int(limit or 100), 500)))
    out: list[dict[str, Any]] = []
    for j in jobs:
        out.append(
            {
                "id": j.get("id"),
                "property_id": j.get("property_id"),
                "property_code": j.get("property_code"),
                "group_url": j.get("group_url"),
                "group_name": j.get("group_name"),
                "status": j.get("status"),
                "attempt_count": j.get("attempt_count"),
                "attempt_id": j.get("attempt_id"),
                "idempotency_key": j.get("idempotency_key"),
                "claimed_at": j.get("claimed_at"),
                "external_action_started_at": j.get("external_action_started_at"),
                "external_post_url": j.get("external_post_url") or j.get("permalink"),
                "last_error_class": j.get("last_error_class"),
                "detail": j.get("detail"),
                "error": j.get("error"),
                "updated_at": j.get("updated_at"),
            }
        )
    return out


def reconcile_publish_job(
    job_id: str,
    *,
    action: str,
    external_post_url: str = "",
    operator: str = "",
) -> dict[str, Any]:
    """Explicit operator reconciliation. Never posts to Facebook."""
    want = (job_id or "").strip()
    act = (action or "").strip().lower()
    if not want:
        raise ReconcileError("job_id is required", code="missing_job_id", http_status=400)
    if act not in RECONCILE_ACTIONS:
        raise ReconcileError("invalid action", code="invalid_action", http_status=400)
    if act == ACTION_KEEP_UNRESOLVED:
        job = get_job(want)
        if not job:
            raise ReconcileError("job not found", code="not_found", http_status=404)
        if job.get("status") != STATUS_NEEDS_RECONCILE:
            raise ReconcileError("job is not awaiting reconciliation", code="invalid_state", http_status=409)
        return job

    evidence = (external_post_url or "").strip()
    if act == ACTION_CONFIRM_POSTED and not evidence:
        raise ReconcileError(
            "external_post_url is required for confirm_posted",
            code="missing_evidence",
            http_status=400,
        )

    with _LOCK:
        data = _load_raw()
        jobs = data.get("jobs") or []
        for i, raw in enumerate(jobs):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("id") or "") != want:
                continue
            st = str(raw.get("status") or "")
            if st == STATUS_POSTED and act == ACTION_CONFIRM_POSTED:
                # Duplicate confirm — harmless; preserve existing evidence.
                return _normalize_job(raw) or dict(raw)
            if st != STATUS_NEEDS_RECONCILE:
                raise ReconcileError(
                    "job is not awaiting reconciliation",
                    code="invalid_state",
                    http_status=409,
                )

            # Preserve identity fields; never mutate by property_code.
            pid = str(raw.get("property_id") or "")
            idem = str(raw.get("idempotency_key") or "")
            raw["reconciled_at"] = _now_iso()
            raw["reconciliation_action"] = act
            raw["reconciled_by"] = (operator or "")[:80]
            raw["property_id"] = pid
            if idem:
                raw["idempotency_key"] = idem

            if act == ACTION_CONFIRM_POSTED:
                raw["status"] = STATUS_POSTED
                raw["permalink"] = evidence
                raw["external_post_url"] = evidence
                raw["external_action_confirmed_at"] = _now_iso()
                if not str(raw.get("external_action_started_at") or "").strip():
                    raw["external_action_started_at"] = raw["external_action_confirmed_at"]
                raw["posted_at"] = _now_iso()
                raw["error"] = ""
                raw["last_error_class"] = ""
                raw["detail"] = "operator confirmed posted"
                raw["lease_until"] = ""
            elif act == ACTION_CONFIRM_NOT_POSTED:
                raw["status"] = STATUS_PENDING
                raw["attempt_id"] = ""
                raw["claimed_at"] = ""
                raw["claimed_by"] = ""
                raw["lease_until"] = ""
                raw["external_action_started_at"] = ""
                raw["external_action_confirmed_at"] = ""
                raw["next_post_at"] = _now_iso()
                raw["last_error_class"] = "operator_confirmed_not_posted"
                raw["detail"] = "operator confirmed not posted — safe retry"
                raw["error"] = ""
            elif act == ACTION_CANCEL:
                raw["status"] = STATUS_CANCELLED
                raw["lease_until"] = ""
                raw["detail"] = "operator cancelled after reconcile"
                raw["last_error_class"] = "operator_cancelled"

            raw["updated_at"] = _now_iso()
            jobs[i] = raw
            data["jobs"] = jobs
            _save_raw(data)
            return _normalize_job(raw) or dict(raw)
    raise ReconcileError("job not found", code="not_found", http_status=404)


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


_OPEN_STATUSES = {STATUS_PENDING, STATUS_DUE, STATUS_FAILED, STATUS_AWAITING_JOIN, STATUS_RUNNING, STATUS_NEEDS_RECONCILE}


def cancel_open_jobs(*, agent_id: str | None = None) -> dict[str, Any]:
    """Cancel all unfinished publish jobs for an agent (or all agents)."""
    want_agent = str(agent_id).strip() if agent_id else None
    cancelled = 0
    with _LOCK:
        data = _load_raw()
        jobs = data.get("jobs") or []
        now = _now_iso()
        for i, raw in enumerate(jobs):
            if not isinstance(raw, dict):
                continue
            if want_agent is not None and str(raw.get("agent_id") or "owner") != want_agent:
                continue
            st = str(raw.get("status") or "").strip().lower()
            if st not in _OPEN_STATUSES:
                continue
            raw["status"] = STATUS_CANCELLED
            raw["updated_at"] = now
            raw["detail"] = str(raw.get("detail") or "") or "ล้างคิวจาก Hub"
            jobs[i] = raw
            cancelled += 1
        data["jobs"] = jobs
        _save_raw(data)
    return {"cancelled": cancelled, "agent_id": want_agent or ""}


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
    next_job = None
    next_at = ""
    for j in jobs:
        st = j.get("status") or ""
        if st not in (STATUS_PENDING, STATUS_DUE, STATUS_FAILED, STATUS_AWAITING_JOIN):
            continue
        at = str(j.get("next_post_at") or "").strip()
        if not at:
            continue
        if not next_at or at < next_at:
            next_at = at
            next_job = {
                "id": j.get("id"),
                "property_code": j.get("property_code"),
                "group_name": j.get("group_name") or j.get("group_url"),
                "status": st,
                "next_post_at": at,
                "needs_manual_join": bool(j.get("needs_manual_join")),
            }
    recent = [
        j
        for j in jobs
        if (j.get("status") or "") in (STATUS_POSTED, STATUS_FAILED, STATUS_RESTRICTED, STATUS_AWAITING_JOIN)
    ][:40]
    return {
        "total": len(jobs),
        "pending": pending,
        "awaiting_join": awaiting_join,
        "needs_manual_join": needs_manual,
        "posted_today": posted_today,
        "by_status": by_status,
        "by_account_today": by_account,
        "next_post_at": next_at or None,
        "next_job": next_job,
        "recent": recent,
    }
