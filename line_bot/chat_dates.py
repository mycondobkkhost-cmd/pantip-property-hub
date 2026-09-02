from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

THAI_MONTHS = {
    "ม.ค.": 1,
    "ก.พ.": 2,
    "มี.ค.": 3,
    "เม.ย.": 4,
    "พ.ค.": 5,
    "มิ.ย.": 6,
    "ก.ค.": 7,
    "ส.ค.": 8,
    "ก.ย.": 9,
    "ต.ค.": 10,
    "พ.ย.": 11,
    "ธ.ค.": 12,
}

DATE_SEP_RE = re.compile(
    r"^(?:วันนี้|เมื่อวาน|"
    r"(\d{1,2})\s*"
    r"(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)"
    r"(?:\s*\([^)]*\))?)$"
)
TIME_RE = re.compile(r"(\d{1,2})[.:](\d{2})\s*น\.?")


def parse_scraped_at(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            # treat as Asia/Bangkok local naive → attach +07
            dt = dt.replace(tzinfo=timezone(timedelta(hours=7)))
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def resolve_date_separator(text: str, scraped: datetime) -> datetime | None:
    t = (text or "").strip()
    if not t:
        return None
    local = scraped.astimezone(timezone(timedelta(hours=7)))
    if t == "วันนี้":
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    if t == "เมื่อวาน":
        d = local - timedelta(days=1)
        return d.replace(hour=0, minute=0, second=0, microsecond=0)
    m = DATE_SEP_RE.match(t)
    if not m or not m.group(1):
        return None
    day = int(m.group(1))
    month = THAI_MONTHS[m.group(2)]
    year = local.year
    # if separator month is after scrape month, likely previous year
    if month > local.month + 1:
        year -= 1
    try:
        return datetime(year, month, day, tzinfo=timezone(timedelta(hours=7)))
    except ValueError:
        return None


def parse_clock(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    m = TIME_RE.search(str(raw).replace("\u00a0", " "))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def annotate_messages_with_dates(
    messages: list[dict[str, Any]],
    scraped_at: str | None,
) -> list[dict[str, Any]]:
    """Attach inferred ISO date to each message using LINE date separators."""
    scraped = parse_scraped_at(scraped_at)
    current_day: datetime | None = None
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        text = (msg.get("text") or "").strip()
        if role == "system":
            resolved = resolve_date_separator(text, scraped)
            if resolved is not None:
                current_day = resolved
            out.append({**msg})
            continue
        item = {**msg}
        if current_day is not None:
            hhmm = parse_clock(msg.get("time"))
            if hhmm:
                dt = current_day.replace(hour=hhmm[0], minute=hhmm[1], second=0, microsecond=0)
            else:
                dt = current_day
            item["inferred_date"] = dt.date().isoformat()
            item["inferred_at"] = dt.isoformat()
        out.append(item)
    return out


def last_talk_from_thread(thread: dict[str, Any]) -> dict[str, str]:
    msgs = annotate_messages_with_dates(
        thread.get("messages") or [],
        thread.get("scraped_at"),
    )
    last_any = next(
        (m for m in reversed(msgs) if m.get("role") in {"customer", "oa"} and m.get("inferred_date")),
        None,
    )
    last_cust = next(
        (m for m in reversed(msgs) if m.get("role") == "customer" and m.get("inferred_date")),
        None,
    )
    last_oa = next(
        (m for m in reversed(msgs) if m.get("role") == "oa" and m.get("inferred_date")),
        None,
    )
    result: dict[str, str] = {}
    if last_any:
        result["last_msg_date"] = last_any.get("inferred_date") or ""
        result["last_talk_at"] = last_any.get("inferred_at") or ""
    if last_cust:
        result["last_customer_date"] = last_cust.get("inferred_date") or ""
        result["last_customer_at"] = last_cust.get("inferred_at") or ""
    if last_oa:
        result["last_oa_date"] = last_oa.get("inferred_date") or ""
        result["last_oa_at"] = last_oa.get("inferred_at") or ""
    return result
