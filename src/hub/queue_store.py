"""Queue of jobs waiting to be posted — like Google Sheet tab รอโพสต์.

Fields per job:
- source_url     = ลิงก์ต้นทาง (โพสต์ทรัพย์จากฝั่งเจ้าของ) — ใช้ดึงข้อมูล
- owner_contact  = ติดต่อเจ้าของ (ลิงก์เฟส / เบอร์ / ข้อความ) — ไม่บังคับเป็น URL
- note           = หมายเหตุ

Legacy: source_url_2 / post_url → migrate into owner_contact
"""

from __future__ import annotations

import csv
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent.parent
QUEUE_PATH = BASE_DIR / "data" / "wait_post_queue.json"
SHEET_CSV = BASE_DIR / "data" / "wait_post_sheet.csv"

URL_RE = re.compile(r"https?://[^\s,，]+", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _is_url(s: str) -> bool:
    s = (s or "").strip()
    if not s.startswith("http"):
        return False
    host = urlparse(s).netloc.lower()
    return bool(host)


def _extract_urls(text: str) -> list[str]:
    found = URL_RE.findall(text or "")
    out: list[str] = []
    seen: set[str] = set()
    for u in found:
        u = u.rstrip(").,，]")
        if u not in seen and _is_url(u):
            seen.add(u)
            out.append(u)
    return out


def _normalize_item(item: dict) -> dict:
    """Migrate legacy fields → source_url + owner_contact."""
    if not item.get("source_url") and item.get("url"):
        item["source_url"] = item["url"]

    # Prefer explicit owner_contact; else legacy 2nd link fields
    if not item.get("owner_contact"):
        legacy = (item.get("source_url_2") or item.get("post_url") or "").strip()
        if legacy:
            item["owner_contact"] = legacy

    item.setdefault("source_url", "")
    item.setdefault("owner_contact", "")
    item.setdefault("note", "")
    item.setdefault("status", "pending")
    item.setdefault("done_at", "")

    # Keep legacy aliases in sync for older UI/clients
    item["source_url_2"] = item.get("owner_contact") or ""
    item["post_url"] = item.get("owner_contact") or ""
    item["url"] = item.get("source_url") or ""
    return item


def load_queue() -> list[dict]:
    if not QUEUE_PATH.exists():
        return []
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        items = data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [_normalize_item(x) for x in items]


def save_queue(items: list[dict]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = [_normalize_item(dict(x)) for x in items]
    QUEUE_PATH.write_text(
        json.dumps(
            {"items": normalized, "updated_at": _now()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def list_queue(include_done: bool = True) -> list[dict]:
    items = load_queue()
    if not include_done:
        items = [x for x in items if x.get("status") != "done"]
    order = {"pending": 0, "working": 1, "done": 2}
    return sorted(
        items,
        key=lambda x: (order.get(x.get("status") or "pending", 9), -(x.get("created_ts") or 0)),
    )


def _source_keys(items: list[dict]) -> set[str]:
    return {
        (x.get("source_url") or "").strip()
        for x in items
        if x.get("status") != "done" and (x.get("source_url") or "").strip()
    }


def add_job(
    source_url: str = "",
    owner_contact: str = "",
    note: str = "",
    raw: str = "",
    source_url_2: str = "",  # legacy → owner_contact
    post_url: str = "",  # legacy → owner_contact
) -> dict:
    """Create one queue job: source post URL + optional owner contact."""
    note = (note or "").strip()
    source_url = (source_url or "").strip()
    owner_contact = (owner_contact or source_url_2 or post_url or "").strip()

    if raw and not source_url:
        urls = _extract_urls(raw)
        if not note:
            first = (raw or "").strip().splitlines()[0].strip() if (raw or "").strip() else ""
            if first and not _is_url(first) and "http" not in first.lower():
                note = first
        if urls:
            source_url = urls[0]
        if not owner_contact and len(urls) >= 2:
            owner_contact = urls[1]

    if not source_url:
        raise ValueError("ต้องมีลิงก์ต้นทาง")
    if not _is_url(source_url):
        raise ValueError("ลิงก์ต้นทางไม่ถูกต้อง (ต้องเป็น URL)")

    items = load_queue()
    if source_url in _source_keys(items):
        raise ValueError("ลิงก์ต้นทางนี้มีในคิวรอโพสต์แล้ว")

    ts = int(datetime.now().timestamp())
    item = {
        "id": str(uuid.uuid4()),
        "source_url": source_url,
        "owner_contact": owner_contact,
        "source_url_2": owner_contact,
        "post_url": owner_contact,
        "url": source_url,
        "note": note,
        "status": "pending",
        "created_at": _now(),
        "created_ts": ts,
        "done_at": "",
    }
    items.insert(0, item)
    save_queue(items)
    return item


def add_links(raw: str, note: str = "") -> list[dict]:
    """Backward-compatible: raw text → one job."""
    item = add_job(raw=raw, note=note)
    return [item]


def update_item(
    item_id: str,
    status: str | None = None,
    note: str | None = None,
    source_url: str | None = None,
    owner_contact: str | None = None,
    source_url_2: str | None = None,
    post_url: str | None = None,
) -> dict:
    items = load_queue()
    item = next((x for x in items if x.get("id") == item_id), None)
    if not item:
        raise ValueError("ไม่พบรายการในคิว")
    if status is not None:
        if status not in ("pending", "working", "done"):
            raise ValueError("สถานะไม่ถูกต้อง")
        item["status"] = status
        item["done_at"] = _now() if status == "done" else ""
    if note is not None:
        item["note"] = note.strip()
    if source_url is not None:
        source_url = source_url.strip()
        if not source_url:
            raise ValueError("ลิงก์ต้นทางว่างไม่ได้")
        if not _is_url(source_url):
            raise ValueError("ลิงก์ต้นทางไม่ถูกต้อง")
        item["source_url"] = source_url
        item["url"] = source_url
    contact = owner_contact
    if contact is None:
        contact = source_url_2 if source_url_2 is not None else post_url
    if contact is not None:
        contact = contact.strip()
        item["owner_contact"] = contact
        item["source_url_2"] = contact
        item["post_url"] = contact
    save_queue(items)
    return _normalize_item(item)


def delete_item(item_id: str) -> None:
    items = load_queue()
    new_items = [x for x in items if x.get("id") != item_id]
    if len(new_items) == len(items):
        raise ValueError("ไม่พบรายการในคิว")
    save_queue(new_items)


def import_from_sheet_csv(path: Path | None = None, replace: bool = False) -> dict:
    """Import rows from รอโพสต์ CSV — URL1 = source, URL2/other = owner_contact."""
    csv_path = path or SHEET_CSV
    if not csv_path.exists():
        raise ValueError(f"ไม่พบไฟล์ {csv_path.name} — ดาวน์โหลดชีทก่อน")

    items = [] if replace else load_queue()
    existing = _source_keys(items)
    added = 0
    skipped = 0
    ts = int(datetime.now().timestamp())

    with csv_path.open(encoding="utf-8") as f:
        for row in csv.reader(f):
            cells = [c.strip() for c in row if c.strip()]
            if not cells:
                continue
            note = ""
            urls: list[str] = []
            other: list[str] = []
            for cell in cells:
                if _is_url(cell):
                    urls.append(cell)
                elif "http" in cell.lower():
                    urls.extend(_extract_urls(cell))
                    rest = URL_RE.sub(" ", cell).strip()
                    if rest and not note:
                        other.append(rest)
                elif not note:
                    note = cell
                else:
                    other.append(cell)
            if not urls:
                continue
            source_url = urls[0]
            owner_contact = urls[1] if len(urls) >= 2 else (other[0] if other else "")
            if source_url in existing:
                skipped += 1
                continue
            items.insert(
                0,
                {
                    "id": str(uuid.uuid4()),
                    "source_url": source_url,
                    "owner_contact": owner_contact,
                    "source_url_2": owner_contact,
                    "post_url": owner_contact,
                    "url": source_url,
                    "note": note,
                    "status": "pending",
                    "created_at": _now(),
                    "created_ts": ts,
                    "done_at": "",
                    "source": "sheet",
                },
            )
            existing.add(source_url)
            added += 1

    save_queue(items)
    return {"added": added, "skipped": skipped, "total": len(items)}


def queue_stats() -> dict:
    items = load_queue()
    return {
        "total": len(items),
        "pending": sum(1 for x in items if x.get("status") == "pending"),
        "working": sum(1 for x in items if x.get("status") == "working"),
        "done": sum(1 for x in items if x.get("status") == "done"),
    }
