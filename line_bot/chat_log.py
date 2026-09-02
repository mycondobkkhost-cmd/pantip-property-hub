from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "data" / "line_chats.jsonl"

_lock = Lock()


def append_chat(
    *,
    user_id: str,
    role: str,
    text: str,
    event: str = "message",
) -> None:
    """Append one chat turn to data/line_chats.jsonl for later review."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "role": role,
        "event": event,
        "text": text,
    }
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
