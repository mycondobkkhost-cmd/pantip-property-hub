from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import (
    FollowEvent,
    JoinEvent,
    MessageEvent,
    TextMessageContent,
)
from loguru import logger

from line_bot.case_store import find_cases, touch_live_message
from line_bot.chat_log import append_chat
from line_bot.openai_reply import reply_for_user
from line_bot.ops import (
    alert_new_unreplied,
    handle_ops_command,
    is_ops_source,
    ops_group_id,
    push_text,
)
from line_bot.prompt import MENU_REPLIES

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "").strip()
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
# ปิดไว้ก่อนจนกว่า FAQ/โทนจะผ่านตรวจ — เปิดด้วย LINE_AUTO_REPLY=1
AUTO_REPLY = os.getenv("LINE_AUTO_REPLY", "0").strip() in {"1", "true", "True", "yes"}
OPS_ALERT_LIVE = os.getenv("LINE_OPS_ALERT_LIVE", "1").strip() in {
    "1",
    "true",
    "True",
    "yes",
}

if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
    logger.warning(
        "LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN ยังไม่ครบ — "
        "ใส่ใน .env ก่อนทดสอบกับ LINE"
    )

handler = WebhookHandler(CHANNEL_SECRET or "missing")
configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN or "missing")

app = FastAPI(title="Pantip Property LINE Bot", docs_url=None, redoc_url=None)

_INVISIBLE = ("\u200b", "\u200c", "\u200d", "\ufeff", "\u00a0")


def _norm_text(text: str) -> str:
    """Normalize rich-menu / pasted text for MENU_REPLIES matching."""
    out = (text or "").replace("\r\n", "\n").strip()
    for ch in _INVISIBLE:
        out = out.replace(ch, "")
    return out.strip()


def _reply(reply_token: str, text: str) -> None:
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=text[:4900])],
            )
        )


def _deliver_user_text(
    *,
    reply_token: str | None,
    user_id: str | None,
    text: str,
    mode: str = "active",
) -> str:
    """Deliver text to user.

    When OA Response mode is Chat (chatMode=chat), prefer push — reply API may
    accept the token but the message never appears in the customer chat.
    """
    body = text[:4900]
    chat_mode = (_line_bot_info() or {}).get("chatMode")
    prefer_push = chat_mode == "chat"
    mode_str = str(getattr(mode, "value", mode) or "active")

    if prefer_push and user_id and user_id != "unknown":
        try:
            push_text(user_id, body)
            logger.info(
                "LINE push ok (chatMode=chat) to {} chars={}",
                user_id[:8],
                len(body),
            )
            return "push"
        except Exception:
            logger.exception("LINE push failed in chatMode=chat — try reply")

    can_reply = bool(reply_token) and mode_str != "standby"
    if can_reply:
        try:
            _reply(reply_token, body)  # type: ignore[arg-type]
            logger.info("LINE reply ok chars={}", len(body))
            return "reply"
        except Exception:
            logger.exception("LINE reply_message failed — fallback push")
    if user_id and user_id != "unknown":
        push_text(user_id, body)
        logger.info("LINE push ok to {} chars={}", user_id[:8], len(body))
        return "push"
    raise RuntimeError("no reply_token/user_id to deliver message")


def _source_meta(event: MessageEvent) -> tuple[str | None, str | None]:
    src = event.source
    st = getattr(src, "type", None)
    if st == "group":
        return "group", getattr(src, "group_id", None)
    if st == "room":
        return "room", getattr(src, "room_id", None)
    return "user", getattr(src, "user_id", None)


_bot_info_cache: dict = {"ts": 0.0, "data": {}}


def _line_bot_info() -> dict:
    """Best-effort bot info (chatMode etc.) for health / ops checks."""
    if not CHANNEL_ACCESS_TOKEN:
        return {}
    import time

    now = time.time()
    if _bot_info_cache["data"] and now - float(_bot_info_cache["ts"]) < 60:
        return dict(_bot_info_cache["data"])
    try:
        import json
        import urllib.request

        req = urllib.request.Request(
            "https://api.line.me/v2/bot/info",
            headers={"Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        _bot_info_cache["ts"] = now
        _bot_info_cache["data"] = data
        return data
    except Exception:
        logger.exception("failed to fetch LINE bot info")
        return dict(_bot_info_cache["data"] or {})


def _persist_env_var(key: str, value: str) -> None:
    """Write/update a key in .env and os.environ (no restart needed for ops group)."""
    env_path = ROOT / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    out: list[str] = []
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[key] = value


def _capture_ops_group(group_id: str, reply_token: str | None = None) -> None:
    logger.info("SETUP capture group_id={}", group_id)
    (ROOT / "logs" / "line_ops_group_id.txt").write_text(group_id + "\n", encoding="utf-8")
    try:
        _persist_env_var("LINE_OPS_GROUP_ID", group_id)
        logger.info("SETUP wrote LINE_OPS_GROUP_ID to .env")
    except Exception:
        logger.exception("SETUP failed writing LINE_OPS_GROUP_ID to .env")
    tip = (
        "รับทราบกลุ่มแอดมินแล้ว ✅\n"
        "ระบบจดกลุ่มนี้เป็นศูนย์ Ops ให้อัตโนมัติแล้ว\n\n"
        "ลองพิมพ์: สรุป"
    )
    if reply_token:
        _reply(reply_token, tip)
    else:
        try:
            push_text(group_id, tip)
        except Exception:
            logger.exception("push group id tip failed")


@app.get("/")
@app.get("/health")
def health() -> dict:
    info = _line_bot_info()
    chat_mode = info.get("chatMode")
    if chat_mode == "chat":
        logger.warning(
            "LINE chatMode=chat — ตั้ง Response mode เป็น Bot ใน LINE OA Manager "
            "ไม่งั้น Messaging API ตอบลูกค้าอาจไม่เสถียร"
        )
    return {
        "status": "ok",
        "service": "line-bot",
        "auto_reply": AUTO_REPLY,
        "ops_group_set": bool(ops_group_id()),
        "cases": len(find_cases(limit=10000)),
        "chat_mode": chat_mode,
        "display_name": info.get("displayName"),
        "basic_id": info.get("basicId"),
        "menu_triggers": list(MENU_REPLIES.keys()),
    }


@app.get("/ops/cases")
def ops_cases(
    status: Optional[str] = None,
    role: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 50,
) -> dict:
    items = find_cases(status=status, role=role, query=q, limit=min(limit, 200))
    return {"count": len(items), "cases": items}


@app.get("/webhook")
def webhook_info() -> PlainTextResponse:
    return PlainTextResponse(
        "LINE webhook endpoint — ตั้ง URL เป็น https://<โดเมน>/webhook แล้วเปิด Use webhook"
    )


@app.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: Optional[str] = Header(default=None, alias="X-Line-Signature"),
) -> JSONResponse:
    if not CHANNEL_SECRET or not CHANNEL_ACCESS_TOKEN:
        raise HTTPException(status_code=503, detail="LINE credentials not configured")
    if not x_line_signature:
        raise HTTPException(status_code=400, detail="Missing X-Line-Signature")

    body = (await request.body()).decode("utf-8")
    logger.info("webhook hit bytes={}", len(body))
    try:
        handler.handle(body, x_line_signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature") from None
    return JSONResponse({"ok": True})


@handler.add(MessageEvent, message=TextMessageContent)
def on_text_message(event: MessageEvent) -> None:
    text = _norm_text(event.message.text or "")
    if not text:
        return

    source_type, source_id = _source_meta(event)
    user_id = event.source.user_id or "unknown"
    mode = getattr(event, "mode", None) or "active"
    reply_token = getattr(event, "reply_token", None)

    # --- Setup helper: ถ้ายังไม่มี LINE_OPS_GROUP_ID แล้วมีคนพิมพ์ในกลุ่ม → บอก group id ---
    if source_type == "group" and source_id and not ops_group_id():
        _capture_ops_group(source_id, reply_token)
        return

    # --- Ops group / admin DM commands ---
    if is_ops_source(source_type, source_id):
        logger.info("OPS command from {}: {}", (source_id or "")[:10], text[:80])
        append_chat(user_id=source_id or user_id, role="admin", text=text, event="ops")
        answer = handle_ops_command(text, session_id=source_id or user_id)
        append_chat(
            user_id=source_id or user_id,
            role="assistant",
            text=answer,
            event="ops",
        )
        _deliver_user_text(
            reply_token=reply_token,
            user_id=source_id or user_id,
            text=answer,
            mode=mode,
        )
        return

    # --- Setup helper: ยังไม่มี admin — ถ้าทัก OA แบบ 1:1 ให้ส่ง user id กลับ ---
    from line_bot.ops import admin_user_ids

    if (
        source_type == "user"
        and user_id
        and user_id != "unknown"
        and not admin_user_ids()
        and not ops_group_id()
    ):
        logger.info("SETUP capture admin user_id={}", user_id)
        (ROOT / "logs" / "line_admin_user_id.txt").write_text(user_id + "\n", encoding="utf-8")
        tip = (
            "รับทราบครับ นี่คือโหมดตั้งค่าแอดมิน ✅\n"
            f"LINE user id ของคุณคือ:\n{user_id}\n\n"
            "ส่งรหัสนี้กลับมาใน Cursor ได้เลย "
            "หรือใส่ใน .env:\n"
            f"LINE_ADMIN_USER_IDS={user_id}\n"
            "แล้วรีสตาร์ทบอท จากนั้นพิมพ์ สรุป ที่แชทนี้ได้อีกครั้ง"
        )
        _deliver_user_text(
            reply_token=reply_token,
            user_id=user_id,
            text=tip,
            mode=mode,
        )
        return

    # --- Customer / co-agent chat ---
    logger.info(
        "LINE message from {} mode={} text={}",
        user_id[:8],
        mode,
        text[:80],
    )
    append_chat(user_id=user_id, role="user", text=text, event="message")

    # Rich Menu / คำทริกเกอร์ — ตอบทันทีก่อนงานช้า (ops alert / case store)
    menu_answer = MENU_REPLIES.get(text)
    if menu_answer:
        logger.info("MENU reply matched: {}", text[:40])
        via = _deliver_user_text(
            reply_token=reply_token,
            user_id=user_id,
            text=menu_answer,
            mode=mode,
        )
        append_chat(user_id=user_id, role="assistant", text=menu_answer, event="menu")
        try:
            touch_live_message(user_id=user_id, role="oa", text=menu_answer)
            touch_live_message(user_id=user_id, role="customer", text=text)
        except Exception:
            logger.exception("case touch after menu reply failed")
        logger.info("MENU delivered via={}", via)
        return

    case = touch_live_message(user_id=user_id, role="customer", text=text)
    if OPS_ALERT_LIVE and case.get("status") == "unreplied":
        try:
            alert_new_unreplied(case)
        except Exception:
            logger.exception("ops alert_new_unreplied failed")

    if not AUTO_REPLY:
        # ไม่ตอบลูกค้าอัตโนมัติ — แค่บันทึกเคส + แจ้งกลุ่มแอดมิน
        logger.info("AUTO_REPLY off — no reply for non-menu text")
        return

    try:
        answer = reply_for_user(user_id, text)
    except Exception:
        logger.exception("OpenAI reply failed")
        answer = (
            "ขอโทษค่ะ ระบบตอบช้าชั่วคราว "
            "ลองพิมพ์อีกครั้งหรือพิมพ์ว่า คุยแอดมิน ได้ค่ะ"
        )

    append_chat(user_id=user_id, role="assistant", text=answer, event="message")
    touch_live_message(user_id=user_id, role="oa", text=answer)
    _deliver_user_text(
        reply_token=reply_token,
        user_id=user_id,
        text=answer,
        mode=mode,
    )


@handler.add(FollowEvent)
def on_follow(event: FollowEvent) -> None:
    """แอดเพื่อน — ไม่ตอบจากบอท (ใช้ข้อความทักทายใน LINE Manager)"""
    user_id = event.source.user_id or "unknown"
    logger.info("LINE follow from {}", user_id[:8])
    append_chat(user_id=user_id, role="system", text="follow", event="follow")


@handler.add(JoinEvent)
def on_join(event: JoinEvent) -> None:
    """เมื่อ OA ถูกเชิญเข้ากลุ่ม — จับ group id อัตโนมัติ"""
    group_id = getattr(event.source, "group_id", None)
    logger.info("LINE join group {}", group_id)
    if not group_id:
        return
    if not ops_group_id():
        _capture_ops_group(group_id, event.reply_token)
    else:
        _reply(
            event.reply_token,
            f"เข้ากลุ่มแล้วครับ พิมพ์ สรุป เพื่อดูเคสค้าง\n(group: {group_id})",
        )
