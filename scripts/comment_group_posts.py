#!/usr/bin/env python3
"""
Auto-comment on Facebook group posts (personal account).

Links are stored in Hub (data/group_post_links.json). This script uses the
persistent Facebook session to leave rotated short comments / emoji bumps
with human-like delays to reduce spam risk.

Usage:
    python scripts/comment_group_posts.py --login
    python scripts/comment_group_posts.py --once
    python scripts/comment_group_posts.py --once --max 2 --dry-run
    python scripts/comment_group_posts.py              # loop until Ctrl+C
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import settings  # noqa: E402
from src.facebook.auth import FacebookAuth  # noqa: E402
from src.facebook.comment_templates import pick_comment  # noqa: E402
from src.facebook.commenter import FacebookPostCommenter  # noqa: E402
from src.hub.group_post_store import (  # noqa: E402
    comments_today_count,
    comments_today_count_for_code,
    get_code_by_code,
    list_due,
    mark_comment_failed,
    mark_comment_success,
    stats,
)


def setup_logging() -> None:
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")
    logger.add(
        settings.LOGS_DIR / "fb_comment_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
    )


def _hub_base() -> str:
    return (os.getenv("HUB_URL") or "").strip().rstrip("/")


def _hub_token() -> str:
    return (os.getenv("COMMENT_AGENT_TOKEN") or "").strip()


def _use_remote_hub() -> bool:
    return bool(_hub_base() and _hub_token())


def _hub_request(method: str, path: str, *, body: dict | None = None, timeout: float = 60) -> dict:
    url = _hub_base() + path
    token = _hub_token()
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Agent-Token": token,
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Hub HTTP {exc.code}: {detail}") from exc


def _fetch_due_bundle(*, limit: int = 100) -> dict:
    """Fetch due queue from Hub (Fly) so Mac/Windows agents share the same data."""
    if _use_remote_hub():
        return _hub_request("GET", f"/api/fb-agent/due?limit={int(limit)}")
    agent_id = (os.getenv("COMMENT_AGENT_ID") or "owner").strip() or "owner"
    due = list_due(limit=limit, agent_id=agent_id)
    code_settings: dict[str, dict] = {}
    code_today: dict[str, int] = {}
    for it in due:
        code = str(it.get("property_code") or "").strip().upper()
        if not code or code in code_settings:
            continue
        row = get_code_by_code(code) or {}
        code_settings[code] = (row.get("settings") or {}) if isinstance(row, dict) else {}
        code_today[code] = comments_today_count_for_code(code)
    return {
        "ok": True,
        "due": due,
        "comments_today": comments_today_count(),
        "code_today": code_today,
        "code_settings": code_settings,
        "stats": stats(),
    }


def _report_result(
    item_id: str,
    *,
    ok: bool,
    comment_text: str = "",
    comment_kind: str = "text",
    error: str = "",
    action: str = "",
    detail: str = "",
    join_status: str = "",
) -> None:
    if _use_remote_hub():
        payload: dict = {"id": item_id, "ok": ok}
        if ok:
            payload["comment_text"] = comment_text
            payload["comment_kind"] = comment_kind
        else:
            payload["error"] = error
            payload["action"] = action
            payload["detail"] = detail
            payload["join_status"] = join_status
        _hub_request("POST", "/api/fb-agent/comment-result", body=payload)
        return
    if ok:
        mark_comment_success(item_id, comment_text=comment_text, comment_kind=comment_kind)
    else:
        mark_comment_failed(item_id, error, action=action, detail=detail, join_status=join_status)


def _delay_between_comments() -> float:
    return random.uniform(
        float(settings.COMMENT_MIN_DELAY_SEC),
        float(settings.COMMENT_MAX_DELAY_SEC),
    )


def run_once(
    *,
    max_comments: int | None = None,
    dry_run: bool = False,
    auth: FacebookAuth | None = None,
    keep_open: bool = False,
    headless: bool = False,
    on_status=None,
) -> dict:
    """Process due group-post links. Returns summary dict."""
    def say(msg: str) -> None:
        logger.info(msg)
        if on_status:
            try:
                on_status(msg)
            except Exception:  # noqa: BLE001
                pass

    max_n = max_comments if max_comments is not None else settings.MAX_COMMENTS_PER_RUN
    max_n = max(1, min(int(max_n), 20))

    try:
        bundle = _fetch_due_bundle(limit=100)
    except Exception as exc:  # noqa: BLE001
        logger.error("ดึงคิวจาก Hub ไม่สำเร็จ: {}", exc)
        return {"ok": False, "done": 0, "failed": 0, "error": str(exc)}

    today = int(bundle.get("comments_today") or 0)
    remaining_today = max(0, settings.MAX_COMMENTS_PER_DAY - today)
    if remaining_today <= 0:
        logger.warning(
            "Daily comment cap reached ({}/{}) — stop",
            today,
            settings.MAX_COMMENTS_PER_DAY,
        )
        return {"ok": True, "done": 0, "failed": 0, "skipped": "daily_cap"}

    due = list(bundle.get("due") or [])
    code_settings = bundle.get("code_settings") if isinstance(bundle.get("code_settings"), dict) else {}
    code_today = bundle.get("code_today") if isinstance(bundle.get("code_today"), dict) else {}
    if not due:
        logger.info("No due group posts to comment")
        return {"ok": True, "done": 0, "failed": 0, "due": 0}

    selected: list[dict] = []
    code_used: dict[str, int] = {}
    for it in due:
        code = (it.get("property_code") or "").strip().upper()
        s = code_settings.get(code) if isinstance(code_settings.get(code), dict) else {}
        cap = int(s.get("max_per_run") or settings.MAX_COMMENTS_PER_RUN)
        daily_cap = int(s.get("max_per_day") or settings.MAX_COMMENTS_PER_DAY)
        if int(code_today.get(code) or 0) >= daily_cap:
            continue
        if code_used.get(code, 0) >= cap:
            continue
        selected.append(it)
        code_used[code] = code_used.get(code, 0) + 1
        if len(selected) >= max_n or len(selected) >= remaining_today:
            break
    due = selected
    take = len(due)
    if not due:
        logger.info("No due group posts within per-code caps")
        return {"ok": True, "done": 0, "failed": 0, "due": 0}
    logger.info(
        "Comment run: {} due (cap run={} day_left={}) · hub={}",
        len(due),
        max_n,
        remaining_today,
        "remote" if _use_remote_hub() else "local",
    )

    if dry_run:
        for it in due:
            text, kind = pick_comment(
                used_texts=[h.get("text") for h in (it.get("history") or []) if isinstance(h, dict)]
            )
            logger.info(
                "[dry-run] {} · {} · would comment ({}) {}",
                it.get("property_code") or "—",
                it.get("post_url"),
                kind,
                text,
            )
        return {"ok": True, "done": 0, "failed": 0, "dry_run": take}

    own_auth = auth is None
    if own_auth:
        auth = FacebookAuth(headless=headless)
    assert auth is not None
    done = 0
    failed = 0
    try:
        if auth._page is not None:  # noqa: SLF001
            page = auth._page  # noqa: SLF001
            if not auth._is_logged_in(page, navigate=False):  # noqa: SLF001
                say("เซสชันหลุด — กำลังล็อกอินใหม่")
                page = auth.login()
        else:
            say("กำลังเปิด Chrome เพื่อคอมเมนต์ — จะเห็นหน้าต่างทำงาน")
            page = auth.login()
        commenter = FacebookPostCommenter(page)
        for i, it in enumerate(due):
            used = [h.get("text") for h in (it.get("history") or []) if isinstance(h, dict)]
            text, kind = pick_comment(used_texts=used)
            post_url = str(it.get("post_url") or "")
            code = it.get("property_code") or "—"
            say(f"[{i + 1}/{len(due)}] กำลังเปิดโพสต์ {code} …")
            logger.info(
                "[{}/{}] {} · {} · {}",
                i + 1,
                len(due),
                code,
                kind,
                text,
            )
            result = commenter.comment_on_post(post_url, text)
            if result.get("ok"):
                _report_result(
                    it["id"],
                    ok=True,
                    comment_text=text,
                    comment_kind=kind,
                )
                done += 1
                say(f"คอมเมนต์สำเร็จ {code} · {text[:40]}")
            else:
                err = str(result.get("error") or "unknown")
                detail = str(result.get("detail") or err)
                action = str(result.get("action") or "failed")
                join_status = str(result.get("join_status") or "")
                logger.error("Comment failed: {} · {}", err, detail)
                _report_result(
                    it["id"],
                    ok=False,
                    error=err,
                    action=action,
                    detail=detail,
                    join_status=join_status,
                )
                failed += 1
                say(f"{code}: {detail}")

            if i < len(due) - 1:
                s = code_settings.get(str(it.get("property_code") or "").strip().upper()) or {}
                min_s = int(s.get("min_delay_sec") or settings.COMMENT_MIN_DELAY_SEC)
                max_s = int(s.get("max_delay_sec") or settings.COMMENT_MAX_DELAY_SEC)
                wait_s = random.uniform(float(min_s), float(max(min_s, max_s)))
                say(f"รอ {wait_s:.0f} วินาที ก่อนโพสต์ถัดไป (Chrome ยังเปิดอยู่)")
                logger.info("Waiting {:.0f}s before next comment…", wait_s)
                time.sleep(wait_s)
    finally:
        if own_auth and not keep_open:
            auth.close()

    logger.info("Comment run finished · ok={} failed={}", done, failed)
    say(f"จบรอบนี้ · สำเร็จ {done} · ไม่สำเร็จ {failed} · Chrome ยังเปิดค้างให้ดูได้")
    return {"ok": True, "done": done, "failed": failed, "due": take, "auth": auth if keep_open else None}


def run_loop() -> None:
    """Keep commenting on a schedule similar to the posting scheduler."""
    logger.info(
        "Comment loop started · delay {}–{}s · max/run={} · max/day={}",
        settings.COMMENT_MIN_DELAY_SEC,
        settings.COMMENT_MAX_DELAY_SEC,
        settings.MAX_COMMENTS_PER_RUN,
        settings.MAX_COMMENTS_PER_DAY,
    )
    while True:
        try:
            run_once()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Comment loop error: {}", exc)
        # Between batches: 45–90 minutes
        pause = random.uniform(45 * 60, 90 * 60)
        logger.info("Sleeping {:.0f} min until next batch…", pause / 60)
        time.sleep(pause)


def main() -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description="Facebook group-post auto-commenter")
    parser.add_argument("--login", action="store_true", help="Login only (session / 2FA setup)")
    parser.add_argument("--once", action="store_true", help="One comment batch then exit")
    parser.add_argument("--max", type=int, default=None, help="Max comments this run")
    parser.add_argument("--dry-run", action="store_true", help="Show due items without commenting")
    parser.add_argument("--stats", action="store_true", help="Print queue stats and exit")
    args = parser.parse_args()

    if args.stats:
        logger.info("Queue stats: {}", stats())
        logger.info("Comments today: {}", comments_today_count())
        due = list_due(limit=20)
        for it in due:
            logger.info(
                "  due · {} · {} · next={}",
                it.get("property_code") or "—",
                it.get("post_url"),
                it.get("next_comment_at"),
            )
        return

    if args.login:
        auth = FacebookAuth(headless=False)
        try:
            auth.login()
            logger.success("Facebook session ready for commenting")
        finally:
            auth.close()
        return

    if args.once or args.dry_run:
        run_once(max_comments=args.max, dry_run=args.dry_run)
        return

    run_loop()


if __name__ == "__main__":
    main()
