from __future__ import annotations

import re
from typing import Literal

Role = Literal["end_customer", "co_agent", "owner_list", "unknown"]
Status = Literal[
    "unreplied",
    "pending_followup",
    "closed",
    "waiting_customer",
    "active",
]

AGENT_RE = re.compile(
    r"เอเจ้น|เอเจนต์|agent|Co-?Agent|รับโค|มีลูกค้า|Property\s*Scout|"
    r"property\s*scout|จากproperty|โคไหม|โคได้|#\s*ptp\d+|PTP\d+",
    re.I,
)
OWNER_RE = re.compile(
    r"ฝากขาย|ฝากเช่า|เสนอทรัพย์|อยากลงประกาศ|ให้ช่วยขาย|ให้ช่วยเช่า",
    re.I,
)
ACK_RE = re.compile(
    r"^(ขอบคุณ|รับทราบ|ไม่เป็นไร|thanks?|thank you|ok|ค่ะ|ครับ|ได้ครับ|ได้ค่ะ|ka|ครับผม|\[sticker\])[\s!.]*$",
    re.I,
)
PENDING_OA_RE = re.compile(
    r"ตรวจสอบ|เช็ค|สอบถามเจ้าของ|คุยกับ(?:ทาง)?เจ้าของ|ลองคุย|"
    r"ประสาน(?:งาน)?|ขอข้อมูลผู้เช่า|สักครู่|มาอัปเดต|"
    r"เดี๋ยว(?:นัท|แอดมิน)?.{0,20}เจ้าของ|รอ(?:ทาง)?เจ้าของ|"
    r"Let me check|I('ll| will) check",
    re.I,
)
UNAVAILABLE_RE = re.compile(r"ไม่ว่าง|ขอโทษ|ขออภัย", re.I)
AUTO_MENU_RE = re.compile(
    r"Pantip Property\s*|01\s*[–-]\s*หาซื้อ|Looking to Buy",
    re.I,
)
SPAM_RE = re.compile(
    r"Livinginsider|CookieRun|voucher|แพ็กเกจเครดิต|โปรโมชันพิเศษ",
    re.I,
)


def classify_role(display_name: str, early_customer_texts: list[str]) -> Role:
    blob = " ".join(early_customer_texts[:5])
    name = display_name or ""
    if OWNER_RE.search(blob):
        return "owner_list"
    if AGENT_RE.search(blob) or AGENT_RE.search(name):
        return "co_agent"
    if early_customer_texts:
        return "end_customer"
    return "unknown"


def is_ack(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if ACK_RE.search(t):
        return True
    return bool(re.search(r"ขอบคุณ|รับทราบ|thanks?", t, re.I) and len(t) < 40)


def is_spam(text: str) -> bool:
    return bool(SPAM_RE.search(text or ""))


def classify_from_last(
    *,
    last_role: str | None,
    last_text: str,
) -> Status:
    """Classify case status from the last meaningful human message."""
    text = (last_text or "").strip()
    if not last_role or not text:
        return "active"
    if last_role == "customer":
        if is_spam(text):
            return "closed"
        if is_ack(text):
            return "closed"
        return "unreplied"
    # oa
    if AUTO_MENU_RE.search(text):
        return "waiting_customer"
    if UNAVAILABLE_RE.search(text):
        return "closed"
    if PENDING_OA_RE.search(text):
        return "pending_followup"
    return "waiting_customer"


def role_label(role: Role | str) -> str:
    return {
        "end_customer": "ลูกค้าตัวจริง",
        "co_agent": "Co-Agent",
        "owner_list": "ฝากทรัพย์",
        "unknown": "ไม่ทราบ",
    }.get(role, role)


def status_label(status: Status | str) -> str:
    return {
        "unreplied": "ลืมตอบ — ลูกค้าทักล่าสุด แอดมินยังไม่ตอบ",
        "pending_followup": "ลืมกลับมาอัปเดต — แอดมินบอกว่าจะเช็คแล้วยังไม่กลับ",
        "closed": "จบแล้ว",
        "waiting_customer": "รอลูกค้า",
        "active": "กำลังคุย",
    }.get(status, status)
