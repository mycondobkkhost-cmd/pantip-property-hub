from __future__ import annotations

import os
import re
from typing import Optional

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)
from loguru import logger

from line_bot.case_classifier import role_label, status_label
from line_bot.case_store import find_cases, get_case, link_user, upsert_case

FOLLOWUP_TEMPLATES = {
    "unreplied": (
        "สวัสดีค่ะ Admin นัท กลับมาอัปเดตเคสนะคะ "
        "รบกวนสอบถามเพิ่มเติมได้ไหมคะ ยังสนใจห้องนี้อยู่ไหมคะ "
        "หรืออยากให้ช่วยหาห้องอื่นที่งบ/โซนใกล้เคียงบ้างคะ"
    ),
    "pending_followup": (
        "สวัสดีค่ะ ขออัปเดตสถานะห้องให้นะคะ "
        "นัทเช็คกับทางเจ้าของแล้ว เดี๋ยวสรุปให้ค่ะ "
        "ระหว่างรอถ้ามีงบหรือวันนัดชมที่สะดวก ฝากไว้ได้เลยนะคะ"
    ),
}


def _config() -> Configuration:
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    return Configuration(access_token=token or "missing")


def ops_group_id() -> str:
    return os.getenv("LINE_OPS_GROUP_ID", "").strip()


def admin_user_ids() -> set[str]:
    raw = os.getenv("LINE_ADMIN_USER_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def is_ops_source(source_type: str | None, source_id: str | None) -> bool:
    if not source_id:
        return False
    if source_type == "group" and source_id == ops_group_id():
        return True
    if source_type == "user" and source_id in admin_user_ids():
        return True
    return False


def push_text(to: str, text: str) -> None:
    if not to:
        raise ValueError("missing push target")
    with ApiClient(_config()) as api_client:
        MessagingApi(api_client).push_message(
            PushMessageRequest(
                to=to,
                messages=[TextMessage(text=text[:4900])],
            )
        )


def notify_ops(text: str) -> bool:
    gid = ops_group_id()
    if not gid:
        logger.warning("LINE_OPS_GROUP_ID ยังไม่ตั้ง — ข้ามแจ้งกลุ่ม")
        return False
    push_text(gid, text)
    return True


def format_digest(limit: int = 15) -> str:
    unreplied = find_cases(status="unreplied", limit=10000)
    pending = find_cases(status="pending_followup", limit=10000)
    prio = [c for c in unreplied if c.get("role") == "end_customer"]

    lines = [
        "📋 สรุปเคส LINE OA",
        f"ลืมตอบ (ลูกค้าทักแล้วยังไม่มีคนตอบ): {len(unreplied)} | ลูกค้าตัวจริง: {len(prio)}",
        f"ลืมกลับมาอัปเดต (บอกว่าจะเช็คแล้วยังไม่กลับ): {len(pending)}",
        "",
    ]
    if prio:
        lines.append("🔴 ลืมตอบ — ลูกค้าตัวจริงทักล่าสุด")
        for c in prio[:limit]:
            name = c.get("display_name") or c.get("id")
            last = (c.get("last_text") or "")[:60].replace("\n", " ")
            uid = c.get("user_id") or "-"
            lines.append(f"• {name} | uid:{uid[:8]}… | {last}")
        lines.append("")
    if pending:
        lines.append("🟡 ลืมกลับมาอัปเดต — แอดมินบอกว่าจะเช็คแล้วยังไม่กลับ")
        for c in pending[: min(10, limit)]:
            name = c.get("display_name") or c.get("id")
            last = (c.get("last_text") or "")[:60].replace("\n", " ")
            lines.append(f"• {name} ({role_label(c.get('role') or '')}) | {last}")
        lines.append("")
    lines.append(
        "คำสั่ง: สรุป | เคสค้าง | ฟอโล่ว <ชื่อ> | ทัก <userId> <ข้อความ> | "
        "ปิดเคส <ชื่อ> | ลิงก์ <ชื่อ> <userId>"
    )
    return "\n".join(lines)


def _find_one(query: str) -> Optional[dict]:
    hits = find_cases(query=query, limit=5)
    if not hits:
        return None
    # prefer exact display_name
    for h in hits:
        if (h.get("display_name") or "").strip().lower() == query.strip().lower():
            return h
    return hits[0]


def handle_ops_command(text: str, *, session_id: str | None = None) -> str:
    """Parse admin/ops commands. Unknown text → AI analyst chat."""
    raw = (text or "").strip()
    if not raw:
        return "พิมพ์ สรุป หรือถามเป็นประโยคได้ เช่น ใน 7 วันนี้มีเคสไหนควรทักบ้าง"

    lower = raw.lower()
    if lower in {"สรุป", "สรุปเคส", "เคสค้าง", "digest", "help", "ช่วยเหลือ", "?"}:
        if lower in {"help", "ช่วยเหลือ", "?"}:
            return (
                "คำสั่งกลุ่มแอดมิน:\n"
                "• สรุป / เคสค้าง — รายการต้องฟอโล่ว\n"
                "• ฟอโล่ว <ชื่อ> — ดูเคส + ข้อความแนะนำ\n"
                "• ทัก <userId> <ข้อความ> — ส่งหาลูกค้าทันที\n"
                "• ปิดเคส <ชื่อ> — ปิดเคส\n"
                "• ลิงก์ <ชื่อ> <userId> — ผูกชื่อจาก audit กับ LINE user id\n"
                "\n"
                "หรือพิมพ์ถามภาษาธรรมชาติได้เลย เช่น\n"
                "“ในช่วง 7 วันนี้ มีเคสไหนที่ควรทักฟอโล่วบ้าง”"
            )
        return format_digest()

    m = re.match(r"^(ฟอโล่ว|followup|follow)\s+(.+)$", raw, re.I)
    if m:
        case = _find_one(m.group(2).strip())
        if not case:
            return f"ไม่พบเคสที่ตรงกับ “{m.group(2).strip()}”"
        status = case.get("status") or "active"
        tmpl = FOLLOWUP_TEMPLATES.get(status, FOLLOWUP_TEMPLATES["unreplied"])
        uid = case.get("user_id")
        lines = [
            f"📌 {case.get('display_name')} | {status_label(status)} | {role_label(case.get('role') or '')}",
            f"ท้ายแชท: {(case.get('last_text') or '')[:120]}",
            f"user_id: {uid or '(ยังไม่มี — ใช้คำสั่ง ลิงก์ ชื่อ userId ก่อน)'}",
            "",
            "ข้อความแนะนำ:",
            tmpl,
        ]
        if uid:
            lines.append("")
            lines.append(f"ถ้าจะส่งเลย พิมพ์:\nทัก {uid} {tmpl}")
        return "\n".join(lines)

    m = re.match(r"^(ทัก|push|ส่ง)\s+(\S+)\s+(.+)$", raw, re.S)
    if m:
        to = m.group(2).strip()
        body = m.group(3).strip()
        try:
            push_text(to, body)
        except Exception as exc:
            logger.exception("push failed")
            return f"ส่งไม่สำเร็จ: {exc}"
        # mark case waiting_customer if known
        case = None
        for c in find_cases(limit=500):
            if c.get("user_id") == to:
                case = c
                break
        if case:
            case["status"] = "waiting_customer"
            case["last_role"] = "oa"
            case["last_text"] = body[:500]
            case["last_oa_text"] = body[:500]
            upsert_case(case)
        return f"ส่งแล้ว → {to[:12]}…"

    m = re.match(r"^(ปิดเคส|ปิด|close)\s+(.+)$", raw, re.I)
    if m:
        case = _find_one(m.group(2).strip())
        if not case:
            return f"ไม่พบเคส “{m.group(2).strip()}”"
        case["status"] = "closed"
        upsert_case(case)
        return f"ปิดเคสแล้ว: {case.get('display_name')}"

    m = re.match(r"^(ลิงก์|link)\s+(.+?)\s+(U[0-9a-fA-F]{32})$", raw)
    if m:
        name = m.group(1).strip()
        uid = m.group(2).strip()
        case = link_user(name, uid)
        if not case:
            return f"ไม่พบชื่อ “{name}” ในเคส"
        return f"ลิงก์แล้ว: {case.get('display_name')} → {uid}"

    # คำสั่งลัดไม่ตรง → คุย/วิเคราะห์ด้วย AI จากข้อมูลเคสจริง
    from line_bot.ops_analyst import reply_ops_chat

    sid = session_id or ops_group_id() or "ops"
    try:
        return reply_ops_chat(sid, raw)
    except Exception as exc:
        logger.exception("ops analyst failed")
        return (
            "วิเคราะห์ไม่สำเร็จตอนนี้ "
            f"({exc}) — ลองพิมพ์ สรุป หรือ ช่วยเหลือ"
        )


def alert_new_unreplied(case: dict) -> None:
    """Notify ops group when a live customer message needs attention."""
    if case.get("status") != "unreplied":
        return
    if case.get("role") not in {"end_customer", "unknown", "co_agent"}:
        return
    name = case.get("display_name") or case.get("user_id") or "?"
    uid = case.get("user_id") or "-"
    last = (case.get("last_text") or "")[:120].replace("\n", " ")
    text = (
        f"⚠️ แชทใหม่รอตอบ\n"
        f"{name} ({role_label(case.get('role') or 'unknown')})\n"
        f"uid: {uid}\n"
        f"{last}\n\n"
        f"พิมพ์: ฟอโล่ว {name}"
    )
    try:
        notify_ops(text)
    except Exception:
        logger.exception("ops alert failed")
