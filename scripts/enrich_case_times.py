#!/usr/bin/env python3
"""Backfill last message clock-times + calendar dates from audit threads."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from line_bot.case_store import load_cases, save_cases  # noqa: E402
from line_bot.chat_dates import last_talk_from_thread  # noqa: E402

THREADS = ROOT / "logs" / "line_study" / "full_audit_threads.json"


def clean_time(raw: str | None) -> str:
    if not raw:
        return ""
    t = raw.replace("\u00a0", " ").strip()
    m = re.search(r"(\d{1,2})[.:](\d{2})\s*น\.?", t)
    if m:
        return f"{int(m.group(1))}:{m.group(2)} น."
    return ""


def extract_date_hint(texts: list[str]) -> str:
    blob = " ".join(texts)
    patterns = [
        r"\d{1,2}/\d{1,2}/202\d",
        r"\d{1,2}/\d{1,2}/\d{2}",
        r"(จันทร์|อังคาร|พุธ|พฤหัส|ศุกร์|เสาร์|อาทิตย์)[^\n]{0,20}\d{1,2}/\d{1,2}",
    ]
    for p in patterns:
        m = re.search(p, blob)
        if m:
            return m.group(0).strip()
    return ""


def main() -> None:
    if not THREADS.exists():
        raise SystemExit(f"missing {THREADS}")
    threads = {t.get("name"): t for t in json.loads(THREADS.read_text(encoding="utf-8"))}
    data = load_cases()
    updated = 0
    with_date = 0
    for case in data["cases"].values():
        name = case.get("display_name")
        thread = threads.get(name) if name else None
        if not thread:
            continue
        msgs = thread.get("messages") or []
        last = msgs[-1] if msgs else {}
        last_cust = next((m for m in reversed(msgs) if m.get("role") == "customer"), {})
        last_oa = next((m for m in reversed(msgs) if m.get("role") == "oa"), {})
        preview = thread.get("preview") or ""
        preview_time = clean_time(preview.split("|")[-1]) if "|" in preview else ""

        case["scraped_at"] = thread.get("scraped_at") or case.get("scraped_at")
        case["last_msg_time"] = (
            clean_time(last.get("time")) or preview_time or case.get("last_msg_time") or ""
        )
        case["last_customer_time"] = (
            clean_time(last_cust.get("time")) or case.get("last_customer_time") or ""
        )
        case["last_oa_time"] = clean_time(last_oa.get("time")) or case.get("last_oa_time") or ""
        hint = extract_date_hint([preview] + [(m.get("text") or "") for m in msgs[-8:]])
        if hint:
            case["date_hint"] = hint

        talk = last_talk_from_thread(thread)
        case.update({k: v for k, v in talk.items() if v})
        if case.get("last_msg_date") or case.get("last_talk_at"):
            with_date += 1
        updated += 1

    save_cases(data)
    with_time = sum(1 for c in data["cases"].values() if c.get("last_msg_time"))
    print(
        f"enriched={updated} with_last_msg_time={with_time} "
        f"with_calendar_date={with_date} total={len(data['cases'])}"
    )


if __name__ == "__main__":
    main()
