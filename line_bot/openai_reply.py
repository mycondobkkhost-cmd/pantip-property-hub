from __future__ import annotations

import os
from collections import defaultdict, deque

from openai import OpenAI

from line_bot.prompt import HANDOFF_KEYWORDS, SYSTEM_PROMPT

_history: dict[str, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=12))


def _client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=key)


def wants_handoff(text: str) -> bool:
    lowered = text.lower().strip()
    return any(k.lower() in lowered for k in HANDOFF_KEYWORDS)


def reply_for_user(user_id: str, user_text: str) -> str:
    """Generate a Thai reply with short per-user memory."""
    if wants_handoff(user_text):
        msg = (
            "รับทราบครับ เดี๋ยวแอดมินติดต่อกลับโดยเร็วที่สุด "
            "ระหว่างรอ ถ้ามีงบหรือทำเลที่สนใจ ฝากไว้ได้เลยครับ"
        )
        _history[user_id].append({"role": "user", "content": user_text})
        _history[user_id].append({"role": "assistant", "content": msg})
        return msg

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(list(_history[user_id]))
    messages.append({"role": "user", "content": user_text})

    completion = _client().chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.6,
        max_tokens=400,
    )
    reply = (completion.choices[0].message.content or "").strip()
    if not reply:
        reply = "ขอโทษครับ ตอนนี้ตอบไม่ทัน ช่วยพิมพ์งบกับทำเลมาอีกครั้งได้ไหมครับ"

    _history[user_id].append({"role": "user", "content": user_text})
    _history[user_id].append({"role": "assistant", "content": reply})
    return reply
