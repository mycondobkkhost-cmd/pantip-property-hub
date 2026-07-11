#!/usr/bin/env python3
"""Import actionable cases from LINE chat audit into data/line_cases.json."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from line_bot.case_classifier import classify_role, is_spam  # noqa: E402
from line_bot.case_store import load_cases, save_cases  # noqa: E402

ACTIONABLE = ROOT / "logs" / "line_study" / "audit_actionable.json"
THREADS = ROOT / "logs" / "line_study" / "full_audit_threads.json"


def main() -> None:
    if not ACTIONABLE.exists():
        raise SystemExit(f"missing {ACTIONABLE}")

    actionable = json.loads(ACTIONABLE.read_text(encoding="utf-8"))
    threads_by_name = {}
    if THREADS.exists():
        for t in json.loads(THREADS.read_text(encoding="utf-8")):
            threads_by_name[t.get("name")] = t

    data = load_cases()
    imported = 0
    skipped = 0
    for row in actionable:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        last = (row.get("last") or "").strip()
        if is_spam(last):
            skipped += 1
            continue
        # soft-skip obvious closed acks / spammy invites already filtered mostly
        if re.search(r"CookieRun|Livinginsider AA", name):
            skipped += 1
            continue

        thread = threads_by_name.get(name) or {}
        early = [
            m.get("text", "")
            for m in (thread.get("messages") or [])
            if m.get("role") == "customer"
        ][:5]
        role = row.get("who") or classify_role(name, early)
        status = row.get("status") or "unreplied"
        case_id = f"audit:{name}"
        msgs = thread.get("messages") or []
        last_msg = msgs[-1] if msgs else {}
        last_cust = next((m for m in reversed(msgs) if m.get("role") == "customer"), {})
        last_oa = next((m for m in reversed(msgs) if m.get("role") == "oa"), {})

        def _clean_time(raw: str | None) -> str:
            if not raw:
                return ""
            t = str(raw).replace("\u00a0", " ").strip()
            m = re.search(r"(\d{1,2}[.:]\d{2}\s*น\.?)", t)
            return m.group(1) if m else ""

        preview = (thread.get("preview") or "")[:200]
        preview_time = _clean_time(preview.split("|")[-1]) if "|" in preview else ""
        data["cases"][case_id] = {
            **data["cases"].get(case_id, {}),
            "id": case_id,
            "display_name": name,
            "user_id": data["cases"].get(case_id, {}).get("user_id"),
            "role": role,
            "status": status,
            "source": "audit",
            "last_text": last[:500],
            "last_role": "customer" if status == "unreplied" else "oa",
            "preview": preview,
            "has_friend_marker": bool(thread.get("has_friend_marker")),
            "notes": row.get("reason") or "",
            "scraped_at": thread.get("scraped_at"),
            "last_msg_time": _clean_time(last_msg.get("time")) or preview_time,
            "last_customer_time": _clean_time(last_cust.get("time")),
            "last_oa_time": _clean_time(last_oa.get("time")),
        }
        imported += 1

    save_cases(data)
    print(f"imported={imported} skipped={skipped} total_cases={len(data['cases'])}")
    print(f"wrote {ROOT / 'data' / 'line_cases.json'}")


if __name__ == "__main__":
    main()
