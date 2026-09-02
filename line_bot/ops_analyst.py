from __future__ import annotations

import os
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any

from openai import OpenAI

from line_bot.case_classifier import role_label, status_label
from line_bot.case_store import find_cases, load_cases

OPS_SYSTEM_PROMPT = """คุณเป็นผู้ช่วยวิเคราะห์เคส LINE OA ของ Pantip Property ให้แอดมิน (นัท/เพลง/เจ้าของระบบ)
คุยเหมือนเพื่อนร่วมงานที่ฉลาด — อ่านคำถาม แล้ววิเคราะห์จากข้อมูลเคสที่ให้มา

สไตล์:
- ภาษาไทย กระชับ ชัด ตรงประเด็น
- ตอบเป็นรายการสั้นๆ เมื่อแนะนำเคสที่ควรทำ
- บอกเหตุผลสั้นๆ ว่าทำไมควรทัก/ฟอโล่ว
- ถ้าข้อมูลไม่พอหรือไม่มีวันที่ชัด ให้บอกข้อจำกัดตรงๆ อย่าแต่งข้อมูล

กติกา:
- ใช้เฉพาะข้อมูลในบริบทเคสที่แนบมา ห้ามสมมติชื่อ/ข้อความที่ไม่มี
- ห้ามอ้างว่า “ไม่มีวัน/เวลา” ถ้าเคสนั้นมี last_talk_at หรือ last_msg_date ในบริบท — ต้องตอบค่านั้น
- ห้ามบอกว่า “ไม่มีรายละเอียดเคส” ถ้าในบริบทมีรายการชื่อเคสอยู่แล้ว — ต้องสรุปรายชื่อจากรายการนั้น
- ถ้าถามเคสค้าง / แอดมินบอกว่าจะเช็ค/ตรวจสอบแล้วยังไม่กลับมา ให้ใช้สถานะ “เคสค้าง (pending_followup)” และลิสต์ชื่อ+คุยล่าสุด+ข้อความท้าย
- ถ้าถามต่อว่า “รายละเอียดเพิ่มเติม” ให้ขยายจากหัวข้อก่อนหน้าทันที (เช่น ลิสต์เคสค้าง) อย่าปฏิเสธ
- ถ้าถามต่อจากรายชื่อที่เพิ่งแนะนำ ให้ตอบวันเวลาของชื่อเหล่านั้นจากบริบททันที
- เคส audit ใช้ last_talk_at (วัน+เวลาที่อนุมานจากตัวแบ่งวันที่ LINE) เป็นหลัก
- ถ้าถาม “7 วันล่าสุด”:
  1) ใช้เคสที่มี last_talk_at / updated_at ในช่วงนั้นก่อน
  2) ถ้าไม่มี/น้อย ให้วิเคราะห์จากคิวค้าง และบอกข้อจำกัดสั้นๆ
- มี 2 สถานะภายใน แต่สำหรับแอดมินให้มองรวมเป็น “งานค้างกับลูกค้า” ได้:
  1) unreplied = ลูกค้าทักล่าสุด แอดมินยังไม่พิมพ์ตอบ
  2) pending_followup = แอดมินตอบว่าจะเช็ค/คุยเจ้าของ แล้วยังไม่กลับมาอัปเดต
- ถ้าผู้ใช้พูดว่า “ลืมตอบ” / “ไม่ได้ตอบกลับ” / “ค้าง” / “ยังไม่จบ” โดยไม่ระบุแบบ
  → รวมทั้งสองแบบเป็นรายการเดียว เรียงใหม่→เก่า ติดป้ายสั้นๆ ว่าเป็นแบบไหน
- อย่าสอนศัพท์เทคนิคนานๆ — ตอบรายชื่อให้ทำต่อได้เลย
- ตัวอย่าง: แอดมินพิมพ์ “ขอตรวจสอบ…” หรือ “ขอลองคุยกับเจ้าของ…” แล้วเงียบ = งานค้าง (แบบ 2)
- เมื่อแนะนำเคสที่ควรทัก ให้ใส่วันเวลาคุยล่าสุดติดชื่อเสมอถ้ามีในบริบท
- อย่าสั่งส่งข้อความหาลูกค้าเอง — แนะนำคำสั่ง เช่น ฟอโล่ว <ชื่อ> หรือ ทัก <userId> <ข้อความ>
- อย่ายืดเกินความจำเป็น (ประมาณ 8–20 บรรทัด)
"""

_history: dict[str, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=8))
TH_MONTH = {
    1: "ม.ค.",
    2: "ก.พ.",
    3: "มี.ค.",
    4: "เม.ย.",
    5: "พ.ค.",
    6: "มิ.ย.",
    7: "ก.ค.",
    8: "ส.ค.",
    9: "ก.ย.",
    10: "ต.ค.",
    11: "พ.ย.",
    12: "ธ.ค.",
}


def clear_ops_history(session_id: str | None = None) -> None:
    if session_id:
        _history.pop(session_id, None)
    else:
        _history.clear()


def _fmt_talk_at(value: str | None) -> str:
    if not value:
        return "-"
    dt = _parse_dt(value)
    if not dt:
        return value
    local = dt.astimezone(timezone(timedelta(hours=7)))
    return f"{local.day} {TH_MONTH[local.month]} {local.year} {local.hour}:{local.minute:02d} น."


def _names_from_text(text: str) -> list[str]:
    names: list[str] = []
    for m in re.finditer(r"(?:^|\n)\s*(?:\d+[\).]\s*|[-•]\s*)\**([^*\n|]+?)\**\s*(?:\||-|–|:)", text):
        name = m.group(1).strip()
        if 1 < len(name) < 60:
            names.append(name)
    # bare mentions like Non / Purchase (Asakan)
    for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9_ .()'-]{1,40})\b", text):
        cand = m.group(1).strip()
        if cand.lower() in {"non", "nun"} or "(" in cand:
            names.append(cand)
    return names


def _format_case_line(c: dict[str, Any]) -> str:
    name = c.get("display_name") or c.get("id") or "?"
    uid = c.get("user_id") or "-"
    last = (c.get("last_text") or "").replace("\n", " ")[:80]
    notes = (c.get("notes") or "").replace("\n", " ")[:60]
    talk_raw = c.get("last_talk_at") or ""
    talk_at = _fmt_talk_at(talk_raw) if talk_raw else (c.get("last_msg_date") or "-")
    msg_t = c.get("last_msg_time") or "-"
    friend = "friend" if c.get("has_friend_marker") else "-"
    return (
        f"- {name} | {status_label(c.get('status') or '')} | "
        f"{role_label(c.get('role') or '')} | uid:{uid} | {friend} | "
        f"คุยล่าสุด:{talk_at} | เวลาLINE:{msg_t} | last:{last}"
        + (f" | note:{notes}" if notes else "")
    )


def _client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=key)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _priority(case: dict[str, Any]) -> tuple:
    status = case.get("status") or ""
    role = case.get("role") or ""
    status_rank = {
        "unreplied": 0,
        "pending_followup": 1,
        "waiting_customer": 3,
        "active": 4,
        "closed": 9,
    }.get(status, 5)
    role_rank = {
        "end_customer": 0,
        "unknown": 1,
        "co_agent": 2,
        "owner_list": 3,
    }.get(role, 4)
    has_uid = 0 if case.get("user_id") else 1
    friend = 0 if case.get("has_friend_marker") else 1
    return (status_rank, role_rank, friend, has_uid, case.get("display_name") or "")


def _guess_days(question: str) -> int | None:
    m = re.search(r"(\d+)\s*วัน", question)
    if m:
        return max(1, min(int(m.group(1)), 90))
    m = re.search(r"(\d+)\s*เดือน", question)
    if m:
        return max(1, min(int(m.group(1)) * 30, 365))
    if re.search(r"วันนี้|24\s*ชม|ตลอดวัน", question):
        return 1
    if re.search(r"เมื่อวาน", question):
        return 2
    if re.search(r"สัปดาห์|7\s*วัน|อาทิตย์นี้", question):
        return 7
    return None


def _wants_pending(question: str, history_blob: str = "") -> bool:
    blob = f"{question}\n{history_blob}"
    return bool(
        re.search(
            r"เคสค้าง|pending|ตรวจสอบ|เช็คให้|เช็คก่อน|ยังไม่กลับ|ยังไม่ได้ตอบ|"
            r"จะตรวจ|รอแอดมิน|รายละเอียดเพิ่มเติม|ขอรายละเอียด|"
            r"ลืมตอบ|งานค้าง|ค้างกับลูกค้า|ไม่ได้ตอบกลับ|ยังไม่จบ",
            blob,
            re.I,
        )
    )


def _wants_all_backlog(question: str, history_blob: str = "") -> bool:
    """User thinks of everything as 'admin forgot' — treat as combined backlog."""
    blob = f"{question}\n{history_blob}"
    if re.search(r"เฉพาะ(?:แบบ)?\s*(?:ลืมตอบ|ลูกค้าทัก)|แค่ลูกค้าทัก|ยังไม่พิมพ์ตอบ", blob):
        return False
    if re.search(r"เฉพาะ.{0,10}(?:เช็ค|ตรวจสอบ|กลับมาอัปเดต)", blob):
        return False
    return bool(
        re.search(
            r"ลืมตอบ|ไม่ได้ตอบกลับ|งานค้าง|ค้างกับลูกค้า|ยังไม่จบ|ควรทัก|ควรฟอโล่ว",
            blob,
            re.I,
        )
    )


def _exclude_co_agent(question: str) -> bool:
    return bool(re.search(r"ไม่(?:เอา|รวม)\s*co[- ]?agent|ไม่(?:เอา|รวม)\s*เอเจ้น", question, re.I))


def build_ops_case_context(
    *,
    question: str,
    limit: int = 70,
    pin_names: list[str] | None = None,
    focus_pending: bool = False,
    focus_backlog: bool = False,
) -> str:
    days = _guess_days(question)
    all_cases = list(load_cases()["cases"].values())
    now = datetime.now(timezone.utc)
    skip_co = _exclude_co_agent(question)

    dated = []
    for c in all_cases:
        dt = _parse_dt(c.get("last_talk_at") or c.get("updated_at") or c.get("created_at"))
        if dt is not None:
            dated.append((dt, c))

    in_window: list[dict[str, Any]] = []
    if days is not None:
        cutoff = now - timedelta(days=days)
        in_window = [c for dt, c in dated if dt >= cutoff]

    if days is not None and in_window:
        working = in_window
        window_note = f"กรองเคสที่มีวันคุยใน {days} วันล่าสุดได้ {len(in_window)} เคส"
    else:
        working = [
            c
            for c in all_cases
            if (c.get("status") or "")
            in {"unreplied", "pending_followup", "waiting_customer", "active"}
        ]
        if days is not None:
            window_note = (
                f"คำถามระบุ ~{days} วัน — พบเคสที่มีวันคุยในช่วงนั้น {len(in_window)} เคส "
                f"จึงใช้คิวค้างปัจจุบันประกอบ (มี last_talk_at {len(dated)}/{len(all_cases)})"
            )
        else:
            window_note = f"วิเคราะห์จากคิวค้างปัจจุบัน (ทั้งหมด {len(all_cases)} เคส)"

    if skip_co:
        working = [c for c in working if c.get("role") != "co_agent"]

    pinned: list[dict[str, Any]] = []
    for raw_name in pin_names or []:
        qn = raw_name.strip().lower()
        if not qn:
            continue
        for c in all_cases:
            dn = (c.get("display_name") or "").strip()
            if dn.lower() == qn or qn in dn.lower():
                if c not in pinned:
                    pinned.append(c)
                break

    unreplied = [c for c in working if c.get("status") == "unreplied"]
    pending = [c for c in working if c.get("status") == "pending_followup"]
    prio = [c for c in unreplied if c.get("role") == "end_customer"]
    pending_sorted = sorted(
        pending,
        key=lambda c: c.get("last_talk_at") or "",
        reverse=True,
    )
    backlog = [c for c in working if c.get("status") in {"unreplied", "pending_followup"}]
    backlog_sorted = sorted(
        backlog,
        key=lambda c: c.get("last_talk_at") or "",
        reverse=True,
    )

    ranked = sorted(working, key=_priority)
    if focus_backlog:
        ranked = backlog_sorted + [
            c for c in ranked if c.get("status") not in {"unreplied", "pending_followup"}
        ]
        limit = max(limit, min(len(backlog_sorted) + 10, 140))
    elif focus_pending:
        ranked = pending_sorted + [c for c in ranked if c.get("status") != "pending_followup"]
        limit = max(limit, min(len(pending_sorted) + 15, 120))

    seen_ids: set[str] = set()
    ordered: list[dict[str, Any]] = []
    for c in pinned + ranked:
        cid = str(c.get("id"))
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        ordered.append(c)

    lines = [
        f"อัปเดตบริบท: {now.astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        window_note,
        (
            f"งานค้างรวม (ที่แอดมินยังไม่จบกับลูกค้า): {len(backlog)} "
            f"| ลูกค้าทักแล้วยังไม่ตอบ: {len(unreplied)} "
            f"| บอกว่าจะเช็คแล้วยังไม่กลับ: {len(pending)} "
            f"| ลูกค้าตัวจริงในกลุ่มลืมตอบ: {len(prio)}"
        ),
        "",
    ]
    if focus_backlog:
        lines.append(
            f"รายการงานค้างรวม ({len(backlog_sorted)} เคส — ใหม่→เก่า; "
            "ป้ายสถานะบอกสั้นๆ ว่าเป็นแบบไหน):"
        )
        for c in backlog_sorted[:100]:
            lines.append(_format_case_line(c))
        lines.append("")
    elif focus_pending or pending_sorted:
        lines.append(
            f"รายการที่แอดมินบอกว่าจะเช็ค/คุยเจ้าของแล้วยังไม่กลับ ({len(pending_sorted)} เคส):"
        )
        for c in pending_sorted[:80]:
            lines.append(_format_case_line(c))
        lines.append("")

    lines.append("รายการอื่นๆ (เรียงความสำคัญ):")
    other = [
        c
        for c in ordered
        if not (
            (focus_backlog and c.get("status") in {"unreplied", "pending_followup"})
            or (focus_pending and c.get("status") == "pending_followup")
        )
    ]
    for c in other[:limit]:
        lines.append(_format_case_line(c))
    if len(other) > limit:
        lines.append(f"... และอีก {len(other) - limit} เคส")
    return "\n".join(lines)


def reply_ops_chat(session_id: str, question: str) -> str:
    """Natural-language ops analysis reply for admin group/DM."""
    q = (question or "").strip()
    if not q:
        return (
            "ถามมาได้เลย เช่น\n"
            "งานค้างกับลูกค้า 2 เดือนล่าสุด ไม่รวม co-agent เรียงใหม่ไปเก่า"
        )

    hist = list(_history[session_id])
    history_blob = "\n".join(m.get("content") or "" for m in hist[-4:])
    focus_backlog = _wants_all_backlog(q, history_blob)
    focus_pending = (not focus_backlog) and _wants_pending(q, history_blob)

    pin_names = _names_from_text(q)
    for msg in hist[-4:]:
        if msg.get("role") == "assistant":
            pin_names.extend(_names_from_text(msg.get("content") or ""))

    if re.search(r"วัน|เวลา|รายละเอียด|เคสค้าง|ตรวจสอบ|ลืมตอบ|งานค้าง", q) and any(
        re.search(r"ไม่มีข้อมูล|ไม่มีรายละเอียด|ตรวจสอบในระบบหลัก", m.get("content") or "")
        for m in hist
        if m.get("role") == "assistant"
    ):
        clear_ops_history(session_id)
        hist = []
        history_blob = ""
        focus_backlog = _wants_all_backlog(q, history_blob)
        focus_pending = (not focus_backlog) and _wants_pending(q, history_blob)

    context = build_ops_case_context(
        question=q,
        pin_names=pin_names,
        focus_pending=focus_pending,
        focus_backlog=focus_backlog,
    )
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    messages: list[dict[str, str]] = [
        {"role": "system", "content": OPS_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": "ข้อมูลเคสปัจจุบัน:\n" + context,
        },
    ]
    messages.extend(list(_history[session_id]))
    messages.append({"role": "user", "content": q})

    completion = _client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        max_tokens=900,
    )
    reply = (completion.choices[0].message.content or "").strip()
    if not reply:
        reply = "วิเคราะห์ไม่สำเร็จ ลองพิมพ์: งานค้างกับลูกค้า เรียงใหม่ไปเก่า"

    _history[session_id].append({"role": "user", "content": q})
    _history[session_id].append({"role": "assistant", "content": reply})
    return reply[:4900]
