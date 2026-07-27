"""Minimal LINE Messaging API webhook — Rich Menu keyword replies only.

Runs inside Property Hub on Fly (always-on). No OpenAI, ops, or case store.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

import requests

from src.hub.line_menu_replies import MENU_REPLIES, WELCOME_MESSAGE, menu_reply_for

_BOT_INFO_CACHE: dict[str, Any] = {"at": 0.0, "info": {}}


def line_credentials() -> tuple[str, str]:
    secret = (os.environ.get("LINE_CHANNEL_SECRET") or "").strip()
    token = (os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip()
    return secret, token


def line_menu_enabled() -> bool:
    flag = (os.environ.get("LINE_MENU_WEBHOOK") or "1").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    secret, token = line_credentials()
    return bool(secret and token)


def verify_signature(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature.strip())


def _bot_info(*, force: bool = False) -> dict:
    now = time.time()
    if not force and _BOT_INFO_CACHE.get("info") and (now - float(_BOT_INFO_CACHE["at"])) < 300:
        return dict(_BOT_INFO_CACHE["info"] or {})
    _, token = line_credentials()
    if not token:
        return {}
    try:
        r = requests.get(
            "https://api.line.me/v2/bot/info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code != 200:
            return dict(_BOT_INFO_CACHE.get("info") or {})
        info = r.json() if r.content else {}
        _BOT_INFO_CACHE["info"] = info
        _BOT_INFO_CACHE["at"] = now
        return dict(info)
    except Exception:  # noqa: BLE001
        return dict(_BOT_INFO_CACHE.get("info") or {})


def _reply(reply_token: str, text: str) -> None:
    _, token = line_credentials()
    r = requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": text[:4900]}],
        },
        timeout=10,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"LINE reply HTTP {r.status_code}: {r.text[:200]}")


def _push(user_id: str, text: str) -> None:
    _, token = line_credentials()
    r = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "to": user_id,
            "messages": [{"type": "text", "text": text[:4900]}],
        },
        timeout=10,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"LINE push HTTP {r.status_code}: {r.text[:200]}")


def deliver_text(
    *,
    reply_token: str | None,
    user_id: str | None,
    text: str,
    mode: str = "active",
) -> str:
    """Deliver reply. If OA chatMode=chat, prefer push (reply often invisible)."""
    body = (text or "")[:4900]
    if not body:
        return "skip"
    chat_mode = (_bot_info() or {}).get("chatMode")
    prefer_push = chat_mode == "chat"
    mode_str = str(mode or "active")

    if prefer_push and user_id and user_id != "unknown":
        try:
            _push(user_id, body)
            return "push"
        except Exception:
            pass

    if reply_token and mode_str != "standby":
        _reply(reply_token, body)
        return "reply"

    if user_id and user_id != "unknown":
        _push(user_id, body)
        return "push"
    return "skip"


def handle_line_events(payload: dict) -> dict:
    """Process webhook JSON. Returns summary counts."""
    events = payload.get("events") or []
    matched = 0
    replied = 0
    ignored = 0
    for event in events:
        if not isinstance(event, dict):
            ignored += 1
            continue
        etype = event.get("type")
        reply_token = event.get("replyToken")
        source = event.get("source") or {}
        user_id = source.get("userId") or "unknown"
        mode = event.get("mode") or "active"

        if etype == "follow":
            # Greeting is usually set in OA Manager; skip to avoid double message.
            ignored += 1
            continue

        if etype != "message":
            ignored += 1
            continue
        message = event.get("message") or {}
        if message.get("type") != "text":
            ignored += 1
            continue
        text = message.get("text") or ""
        answer = menu_reply_for(text)
        if not answer:
            ignored += 1
            continue
        matched += 1
        via = deliver_text(
            reply_token=reply_token,
            user_id=user_id,
            text=answer,
            mode=mode,
        )
        if via != "skip":
            replied += 1
    return {
        "events": len(events),
        "matched": matched,
        "replied": replied,
        "ignored": ignored,
    }


def process_webhook(body: bytes, signature: str) -> tuple[int, dict]:
    """Verify + handle. Returns (http_status, json_body)."""
    if not line_menu_enabled():
        return 503, {"ok": False, "error": "LINE menu webhook disabled or missing credentials"}
    secret, _ = line_credentials()
    if not verify_signature(body, signature, secret):
        return 400, {"ok": False, "error": "Invalid signature"}
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return 400, {"ok": False, "error": "Invalid JSON"}
    try:
        summary = handle_line_events(payload if isinstance(payload, dict) else {})
    except Exception as exc:  # noqa: BLE001
        return 500, {"ok": False, "error": str(exc)[:300]}
    return 200, {"ok": True, **summary}


def line_health_payload() -> dict:
    secret, token = line_credentials()
    info = _bot_info() if token else {}
    return {
        "ok": True,
        "service": "line-menu-webhook",
        "enabled": line_menu_enabled(),
        "credentials": bool(secret and token),
        "chat_mode": info.get("chatMode"),
        "display_name": info.get("displayName"),
        "basic_id": info.get("basicId"),
        "menu_triggers": list(MENU_REPLIES.keys()),
        "welcome_chars": len(WELCOME_MESSAGE),
    }
