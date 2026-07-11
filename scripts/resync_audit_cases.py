#!/usr/bin/env python3
"""Re-scan audit threads and upsert pending/unreplied cases into line_cases.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from line_bot.case_classifier import classify_from_last, classify_role, is_spam  # noqa: E402
from line_bot.case_store import load_cases, save_cases  # noqa: E402
from line_bot.chat_dates import last_talk_from_thread  # noqa: E402

THREADS = ROOT / "logs" / "line_study" / "full_audit_threads.json"


def main() -> None:
    threads = json.loads(THREADS.read_text(encoding="utf-8"))
    data = load_cases()
    added = 0
    updated = 0
    for thread in threads:
        name = (thread.get("name") or "").strip()
        if not name:
            continue
        last = (thread.get("last_text") or "").strip()
        last_role = thread.get("last_role")
        if is_spam(last):
            continue
        status = classify_from_last(last_role=last_role, last_text=last)
        if status not in {"unreplied", "pending_followup"}:
            continue

        early = [
            m.get("text", "")
            for m in (thread.get("messages") or [])
            if m.get("role") == "customer"
        ][:5]
        role = classify_role(name, early)
        case_id = f"audit:{name}"
        prev = data["cases"].get(case_id, {})
        talk = last_talk_from_thread(thread)
        msgs = thread.get("messages") or []
        last_msg = msgs[-1] if msgs else {}
        case = {
            **prev,
            "id": case_id,
            "display_name": name,
            "user_id": prev.get("user_id"),
            "role": role,
            "status": status,
            "source": "audit",
            "last_text": last[:500],
            "last_role": last_role,
            "preview": (thread.get("preview") or "")[:200],
            "has_friend_marker": bool(thread.get("has_friend_marker")),
            "notes": prev.get("notes") or "",
            "scraped_at": thread.get("scraped_at"),
            **{k: v for k, v in talk.items() if v},
        }
        if not case.get("last_msg_time") and last_msg.get("time"):
            import re

            m = re.search(r"(\d{1,2}[.:]\d{2}\s*น\.?)", str(last_msg.get("time")))
            if m:
                case["last_msg_time"] = m.group(1).replace(".", ":")

        if case_id in data["cases"]:
            updated += 1
        else:
            added += 1
        data["cases"][case_id] = case

    save_cases(data)
    pending = sum(1 for c in data["cases"].values() if c.get("status") == "pending_followup")
    unreplied = sum(1 for c in data["cases"].values() if c.get("status") == "unreplied")
    mei = data["cases"].get("audit:Mei²⁸⁹")
    print(f"added={added} updated={updated} total={len(data['cases'])}")
    print(f"unreplied={unreplied} pending_followup={pending}")
    if mei:
        print(
            "Mei²⁸⁹",
            mei.get("status"),
            mei.get("last_talk_at"),
            (mei.get("last_text") or "")[:60],
        )
    else:
        print("Mei²⁸⁹ still missing")


if __name__ == "__main__":
    main()
