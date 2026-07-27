"""Rotated comment / emoji “sticker” payloads for FB group-post bumps.

Design goals (anti-spam):
- Short, natural Thai bump lines — never paste the full listing again
- Mix text vs emoji-only so runs don’t look identical
- Avoid repeating the same line on the same post (caller passes used texts)
"""

from __future__ import annotations

import random
from typing import Literal

CommentKind = Literal["text", "emoji"]

# Natural bump lines — keep short; vary punctuation / pronouns lightly
TEXT_TEMPLATES: list[str] = [
    "ยังว่างอยู่ครับ สนใจทักได้เลยครับ",
    "อัปเดตครับ ห้องยังว่างอยู่",
    "ยังว่างครับ ดูรายละเอียดทักมาได้เลย",
    "ห้องยังว่างอยู่ครับ สอบถามได้ครับ",
    "อัปเดตสถานะ — ยังว่างครับ",
    "ยังว่างอยู่ค่ะ สนใจทักได้เลยค่ะ",
    "ยังว่างค่ะ ดูรายละเอียดทักมาได้เลย",
    "อัปเดตค่ะ ห้องยังว่างอยู่",
    "ยังว่างอยู่ครับ 🙏",
    "ห้องยังว่างครับ สนใจทักได้เลย",
    "อัปเดตครับ ยังว่างอยู่",
    "ยังว่างอยู่ สอบถามเพิ่มเติมทักได้เลยครับ",
    "สถานะล่าสุด: ยังว่างครับ",
    "ยังว่างอยู่ครับ ดูต่อทักได้เลย",
    "ห้องนี้ยังว่างอยู่ครับ",
    "อัปเดต — ยังว่างอยู่ค่ะ",
    "ยังว่างค่ะ สนใจทักได้เลยนะคะ",
    "ยังว่างอยู่ครับ ✅",
    "อัปเดตครับ ว่างอยู่เหมือนเดิม",
    "ยังว่างครับ ทักมาได้เลยครับ",
]

# Emoji-only “sticker-like” comments (safer than FB sticker picker automation)
EMOJI_STICKERS: list[str] = [
    "👍",
    "🙏",
    "✅",
    "🏠",
    "✨",
    "💬",
    "📌",
    "👋",
    "👍🙏",
    "✅🏠",
]

# Rough mix: mostly text, occasional emoji bump
EMOJI_CHANCE = 0.22


def pick_comment(*, used_texts: list[str] | None = None) -> tuple[str, CommentKind]:
    """Return (text, kind) avoiding recently used lines when possible."""
    used = { (t or "").strip() for t in (used_texts or []) if (t or "").strip() }
    use_emoji = random.random() < EMOJI_CHANCE
    pool: list[str] = EMOJI_STICKERS if use_emoji else TEXT_TEMPLATES
    kind: CommentKind = "emoji" if use_emoji else "text"
    fresh = [t for t in pool if t not in used]
    if not fresh:
        # flip kind if this kind is exhausted
        alt_pool = TEXT_TEMPLATES if use_emoji else EMOJI_STICKERS
        alt_kind: CommentKind = "text" if use_emoji else "emoji"
        fresh = [t for t in alt_pool if t not in used] or alt_pool
        pool = fresh
        kind = alt_kind
    else:
        pool = fresh
    return random.choice(pool), kind
