"""Queue of jobs waiting to be posted — like Google Sheet tab รอโพสต์.

Fields per job:
- source_url     = ลิงก์ต้นทาง (โพสต์ทรัพย์จากฝั่งเจ้าของ) — ใช้ดึงข้อมูล
- owner_contact  = ติดต่อเจ้าของ (ลิงก์เฟส / เบอร์ / ข้อความ) — ไม่บังคับเป็น URL
- note           = หมายเหตุ
- project        = ชื่อโครงการ (จาก projects master หรือพิมพ์ใหม่)
- price          = ราคา (ข้อความ เช่น 25000 หรือ 2.5 ลบ.)
- queued_at      = วันที่มาใส่คิว (YYYY-MM-DD) — ตั้งอัตโนมัติตอนเพิ่ม

Sheet columns (header optional) — live tab often keeps col A blank:
  [A blank] | หมายเหตุ | ลิ้งต้นโพสต์ | ลิ้งเจ้าของ | โครงการ | ราคา | วันที่มาใส่คิว
Legacy 6-col without blank A also accepted by the parser.
Legacy aliases: note | source_url | owner_contact (cols A–C only)

Legacy aliases: source_url_2 / post_url → owner_contact
"""

from __future__ import annotations

import csv
import json
import os
import re
import tempfile
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent.parent
QUEUE_PATH = BASE_DIR / "data" / "wait_post_queue.json"
SHEET_CSV = BASE_DIR / "data" / "wait_post_sheet.csv"

_STORE_LOCK = threading.RLock()

URL_RE = re.compile(r"https?://[^\s,，]+", re.I)

# Sheet header labels (Thai) — keep append order stable for column B = source URL
SHEET_HEADERS = [
    "หมายเหตุ",
    "ลิ้งต้นโพสต์",
    "ลิ้งเจ้าของ",
    "โครงการ",
    "ราคา",
    "วันที่มาใส่คิว",
]


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    return date.today().isoformat()


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


def _looks_like_date(s: str) -> bool:
    s = (s or "").strip()[:10]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _normalize_queued_at(raw: str, fallback: str = "") -> str:
    s = (raw or "").strip()
    if _looks_like_date(s):
        return s[:10]
    # "2026-07-26 14:30" → date part
    if len(s) >= 10 and _looks_like_date(s[:10]):
        return s[:10]
    fb = (fallback or "").strip()
    if _looks_like_date(fb):
        return fb[:10]
    if len(fb) >= 10 and _looks_like_date(fb[:10]):
        return fb[:10]
    return _today()


def _normalize_item(item: dict) -> dict:
    """Migrate legacy fields → source_url + owner_contact + project/price/queued_at."""
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
    item.setdefault("project", "")
    item.setdefault("price", "")
    item.setdefault("status", "pending")
    item.setdefault("done_at", "")
    item["project"] = str(item.get("project") or "").strip()
    item["price"] = str(item.get("price") or "").strip()
    item["queued_at"] = _normalize_queued_at(
        str(item.get("queued_at") or ""),
        fallback=str(item.get("created_at") or ""),
    )

    # Keep legacy aliases in sync for older UI/clients
    item["source_url_2"] = item.get("owner_contact") or ""
    item["post_url"] = item.get("owner_contact") or ""
    item["url"] = item.get("source_url") or ""
    return item


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_queue_file() -> list[dict]:
    if not QUEUE_PATH.exists():
        return []
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[hub] wait_post_queue.json corrupt — refusing empty overwrite: {exc}")
        raise ValueError("ไฟล์คิวรอโพสต์เสียหาย — รีเฟรชแล้วลองใหม่ หรือแจ้งทีมเทค") from exc
    if isinstance(data, dict):
        items = data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [_normalize_item(x) for x in items]


def load_queue() -> list[dict]:
    with _STORE_LOCK:
        return _read_queue_file()


def _write_queue_file(items: list[dict]) -> None:
    normalized = [_normalize_item(dict(x)) for x in items]
    payload = json.dumps(
        {"items": normalized, "updated_at": _now()},
        ensure_ascii=False,
        indent=2,
    )
    _atomic_write_text(QUEUE_PATH, payload)


def save_queue(items: list[dict]) -> None:
    with _STORE_LOCK:
        _write_queue_file(items)


def list_queue(include_done: bool = True) -> list[dict]:
    items = load_queue()
    if not include_done:
        items = [x for x in items if x.get("status") != "done"]
    # เก่าสุด → ใหม่สุด (แถวบนชีท / ใส่คิวก่อนขึ้นก่อน)
    order = {"working": 0, "pending": 1, "done": 2}

    def sort_key(x: dict):
        sheet_order = x.get("sheet_order")
        if sheet_order is None:
            sheet_order = 10**9
        return (
            int(sheet_order),
            x.get("created_ts") or 0,
            order.get(x.get("status") or "pending", 9),
        )

    return sorted(items, key=sort_key)


def _source_keys(items: list[dict]) -> set[str]:
    return {
        (x.get("source_url") or "").strip()
        for x in items
        if x.get("status") != "done" and (x.get("source_url") or "").strip()
    }


def item_to_sheet_row(item: dict) -> list[str]:
    it = _normalize_item(dict(item))
    return [
        it.get("note") or "",
        it.get("source_url") or "",
        it.get("owner_contact") or "",
        it.get("project") or "",
        it.get("price") or "",
        it.get("queued_at") or "",
    ]


def add_job(
    source_url: str = "",
    owner_contact: str = "",
    note: str = "",
    raw: str = "",
    source_url_2: str = "",  # legacy → owner_contact
    post_url: str = "",  # legacy → owner_contact
    project: str = "",
    price: str = "",
    queued_at: str = "",
) -> dict:
    """Create one queue job: source post URL + optional owner contact + project/price."""
    note = (note or "").strip()
    source_url = (source_url or "").strip()
    owner_contact = (owner_contact or source_url_2 or post_url or "").strip()
    project = (project or "").strip()
    price = (price or "").strip()
    queued_at = _normalize_queued_at(queued_at)

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

    with _STORE_LOCK:
        items = _read_queue_file()
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
            "project": project,
            "price": price,
            "queued_at": queued_at,
            "status": "pending",
            "created_at": _now(),
            "created_ts": ts,
            "done_at": "",
            "source": "hub",
        }
        items.insert(0, item)
        _write_queue_file(items)
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
    project: str | None = None,
    price: str | None = None,
    queued_at: str | None = None,
) -> dict:
    with _STORE_LOCK:
        items = _read_queue_file()
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
        if project is not None:
            item["project"] = project.strip()
        if price is not None:
            item["price"] = price.strip()
        if queued_at is not None:
            item["queued_at"] = _normalize_queued_at(
                queued_at, fallback=item.get("queued_at") or ""
            )
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
        _write_queue_file(items)
        return _normalize_item(item)


def delete_item(item_id: str) -> None:
    with _STORE_LOCK:
        items = _read_queue_file()
        new_items = [x for x in items if x.get("id") != item_id]
        if len(new_items) == len(items):
            raise ValueError("ไม่พบรายการในคิว")
        _write_queue_file(new_items)


def _looks_like_price(s: str) -> bool:
    """True for values like 22000 / 15,000 / 2.5ลบ — not project names."""
    raw = (s or "").strip()
    if not raw:
        return False
    if re.fullmatch(r"[\d,]+(\.\d+)?", raw):
        return True
    if re.fullmatch(r"[\d,.]+\s*(ลบ\.?|ล้าน|บาท|k|K)?", raw):
        return True
    return False


def _align_wait_post_cells(cells: list[str]) -> list[str]:
    """Normalize sheet cells to [note, source, owner, project, price, queued_at].

    Live「รอโพสต์」tab keeps column A blank; Hub appends used to land shifted so
    project text sat where the parser expected note. Drop leading blanks until
    we see either note+URL or empty-note+URL.
    """
    cells = [(c or "").strip() for c in cells]
    while len(cells) >= 2 and cells[0] == "":
        # "", url, …  → empty note (canonical)
        if _is_url(cells[1]):
            break
        # "", "", url, …  or "", note, url, … → drop spacer col A
        if cells[1] == "" or (not _is_url(cells[1]) and any(_is_url(c) for c in cells[2:])):
            cells = cells[1:]
            continue
        break
    while len(cells) < 6:
        cells.append("")
    return cells[:8]


def _header_map(header_cells: list[str]) -> dict[str, int] | None:
    """Return col index map if row looks like a Thai/English header."""
    lower = [(c or "").strip().lower() for c in header_cells]
    joined = " ".join(lower)
    if not any(
        k in joined
        for k in ("ลิ้ง", "ลิงก์", "link", "source", "โครงการ", "project", "หมายเหตุ", "note")
    ):
        return None
    # Must not look like a data row (first URL cell)
    if any(_is_url(c) for c in header_cells):
        return None

    def idx(*names: str) -> int | None:
        for n in names:
            n_l = n.lower()
            for i, h in enumerate(lower):
                if n_l in h:
                    return i
        return None

    mapping = {
        "note": idx("หมายเหตุ", "note"),
        "source_url": idx("ลิ้งต้น", "ลิงก์ต้น", "source", "ต้นโพสต์", "ต้นทาง"),
        "owner_contact": idx("ลิ้งเจ้าของ", "ลิงก์เจ้าของ", "owner", "เจ้าของ"),
        "project": idx("โครงการ", "project"),
        "price": idx("ราคา", "price"),
        "queued_at": idx("วันที่มาใส่คิว", "queued", "วันที่ใส่คิว", "ใส่คิว"),
    }
    # Require at least a source column concept
    if mapping["source_url"] is None and mapping["note"] is None:
        return None
    return {k: v for k, v in mapping.items() if v is not None}


def _parse_sheet_row_positional(cells: list[str]) -> dict | None:
    """Parse note|url|contact|project|price|queued_at (legacy A–C + extras)."""
    cells = _align_wait_post_cells(list(cells))
    note = (cells[0] or "").strip()
    source_url = (cells[1] or "").strip()
    owner_contact = (cells[2] or "").strip()
    project = (cells[3] or "").strip()
    price = (cells[4] or "").strip()
    queued_at = (cells[5] or "").strip()

    if not _is_url(source_url):
        return None
    if project and _is_url(project):
        return None
    # Price landed in project (shifted row) — recover project from note when needed
    if _looks_like_price(project) and note and not _is_url(note) and not _looks_like_price(note):
        if not price or price == project:
            price = project
        project = note
        note = ""
    return {
        "source_url": source_url,
        "owner_contact": owner_contact,
        "note": note if not _is_url(note) else "",
        "project": project if not _is_url(project) else "",
        "price": price if not _is_url(price) else "",
        "queued_at": queued_at if _looks_like_date(queued_at) or queued_at else "",
    }


def _parse_sheet_row_scan(cells: list[str]) -> dict | None:
    """Fallback scan when columns are irregular."""
    raw = [(c or "").strip() for c in cells]
    aligned = _align_wait_post_cells(raw)
    if _is_url((aligned[1] if len(aligned) > 1 else "") or ""):
        pos = _parse_sheet_row_positional(aligned)
        if pos:
            return pos

    urls: list[str] = []
    text: list[str] = []
    for cell in raw:
        if not cell:
            continue
        if _is_url(cell):
            urls.append(cell)
        elif "http" in cell.lower():
            urls.extend(_extract_urls(cell))
            rest = URL_RE.sub(" ", cell).strip()
            if rest:
                text.append(rest)
        else:
            text.append(cell)
    if not urls:
        return None
    source_url = urls[0]
    owner_contact = urls[1] if len(urls) >= 2 else ""
    note = ""
    project = ""
    price = ""
    queued_at = ""
    remain = list(text)
    for extra in list(remain):
        if _looks_like_date(extra) and not queued_at:
            queued_at = extra[:10]
            remain.remove(extra)
        elif _looks_like_price(extra) and not price:
            price = extra
            remain.remove(extra)
    if len(remain) == 1:
        project = remain[0]
    elif len(remain) >= 2:
        note = remain[0]
        project = remain[1]
        if len(remain) > 2 and not price:
            price = remain[2]
    return {
        "source_url": source_url,
        "owner_contact": owner_contact,
        "note": note,
        "project": project,
        "price": price,
        "queued_at": queued_at,
    }


def repair_misaligned_queue_items(items: list[dict] | None = None) -> dict:
    """Fix rows where project name sat in note and price sat in project."""
    owned = items is not None
    items = list(items) if owned else load_queue()
    fixed = 0
    for it in items:
        note = (it.get("note") or "").strip()
        project = (it.get("project") or "").strip()
        price = (it.get("price") or "").strip()
        changed = False
        if _looks_like_price(project) and note and not _looks_like_price(note) and not _is_url(note):
            if not price or price == project:
                it["price"] = project
            it["project"] = note
            it["note"] = ""
            changed = True
        elif note and not _looks_like_price(note) and not _is_url(note):
            # Sheet users often typed project into the note column (col B).
            # Keep obvious remark keywords in note.
            remark_like = bool(
                re.search(r"เช็ค|ด่วน|โค|คอม\s*\d|โควต้า|หมายเหตุ|รอ|ติดต่อ", note, re.I)
            )
            if not remark_like:
                if not project:
                    it["project"] = note
                    it["note"] = ""
                    changed = True
                elif project == note:
                    it["note"] = ""
                    changed = True
        if changed:
            fixed += 1
    if fixed and not owned:
        save_queue(items)
    return {"ok": True, "fixed": fixed, "total": len(items)}



def _parse_sheet_row_header(cells: list[str], hmap: dict[str, int]) -> dict | None:
    def g(key: str) -> str:
        i = hmap.get(key)
        if i is None or i >= len(cells):
            return ""
        return (cells[i] or "").strip()

    source_url = g("source_url")
    if not source_url or not _is_url(source_url):
        # try scan as fallback for malformed header rows
        return None
    return {
        "source_url": source_url,
        "owner_contact": g("owner_contact"),
        "note": g("note"),
        "project": g("project"),
        "price": g("price"),
        "queued_at": g("queued_at"),
    }


def import_from_sheet_csv(path: Path | None = None, replace: bool = False) -> dict:
    """Import rows from รอโพสต์ CSV — URL1 = source, URL2/other = owner_contact.

    When replace=True the queue becomes the sheet contents (source of truth),
    but local ``working`` status is preserved for matching URLs, and in-progress
    jobs not yet on the sheet are kept so work is not lost mid-flow.
    """
    csv_path = path or SHEET_CSV
    if not csv_path.exists():
        raise ValueError(f"ไม่พบไฟล์ {csv_path.name} — ดาวน์โหลดชีทก่อน")

    sheet_rows: list[dict] = []
    with csv_path.open(encoding="utf-8") as f:
        reader = list(csv.reader(f))
    hmap: dict[str, int] | None = None
    start = 0
    if reader:
        hmap = _header_map(reader[0])
        if hmap:
            start = 1

    for row in reader[start:]:
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        parsed = None
        if hmap:
            parsed = _parse_sheet_row_header(cells, hmap)
        if parsed is None:
            parsed = _parse_sheet_row_positional(cells)
        if parsed is None:
            parsed = _parse_sheet_row_scan([c for c in cells if c])
        if not parsed:
            continue
        sheet_rows.append(parsed)

    ts = int(datetime.now().timestamp())
    added = 0
    skipped = 0
    preserved_working = 0

    with _STORE_LOCK:
        old_items = _read_queue_file()
        old_by_url = {
            (x.get("source_url") or "").strip(): x
            for x in old_items
            if (x.get("source_url") or "").strip()
        }

        if replace:
            items: list[dict] = []
            seen: set[str] = set()
            base_ts = ts - max(len(sheet_rows), 1)
            for idx, row in enumerate(sheet_rows):
                source_url = row["source_url"]
                if source_url in seen:
                    skipped += 1
                    continue
                seen.add(source_url)
                prev = old_by_url.get(source_url)
                status = "pending"
                item_id = str(uuid.uuid4())
                created_at = _now()
                created_ts = base_ts + idx
                if prev and prev.get("status") == "working":
                    status = "working"
                    item_id = prev.get("id") or item_id
                    created_at = prev.get("created_at") or created_at
                    preserved_working += 1
                elif prev and prev.get("status") == "pending":
                    item_id = prev.get("id") or item_id
                    created_at = prev.get("created_at") or created_at
                else:
                    added += 1
                project = row.get("project") or ((prev or {}).get("project") or "")
                price = row.get("price") or ((prev or {}).get("price") or "")
                queued_at = row.get("queued_at") or (
                    (prev or {}).get("queued_at") or (prev or {}).get("created_at") or ""
                )
                items.append(
                    {
                        "id": item_id,
                        "source_url": source_url,
                        "owner_contact": row["owner_contact"],
                        "source_url_2": row["owner_contact"],
                        "post_url": row["owner_contact"],
                        "url": source_url,
                        "note": row["note"],
                        "project": project,
                        "price": price,
                        "queued_at": _normalize_queued_at(queued_at, fallback=created_at),
                        "status": status,
                        "created_at": created_at,
                        "created_ts": created_ts,
                        "sheet_order": idx,
                        "done_at": "",
                        "source": "sheet",
                    }
                )
            local_only = 0
            preserved_pending = 0
            for prev in old_items:
                url = (prev.get("source_url") or "").strip()
                if not url or url in seen:
                    continue
                status = prev.get("status") or "pending"
                src = (prev.get("source") or "").strip()
                keep = status == "working" or (
                    status == "pending" and src in ("hub", "local", "")
                )
                if not keep:
                    continue
                prev = dict(prev)
                prev["sheet_order"] = 10**9 + local_only
                items.append(prev)
                local_only += 1
                if status == "working":
                    preserved_working += 1
                else:
                    preserved_pending += 1
            repair_misaligned_queue_items(items)
            _write_queue_file(items)
            total = len(items)
            replaced = True
        else:
            items = old_items
            existing = _source_keys(items)
            for row in sheet_rows:
                source_url = row["source_url"]
                if source_url in existing:
                    skipped += 1
                    continue
                items.insert(
                    0,
                    {
                        "id": str(uuid.uuid4()),
                        "source_url": source_url,
                        "owner_contact": row["owner_contact"],
                        "source_url_2": row["owner_contact"],
                        "post_url": row["owner_contact"],
                        "url": source_url,
                        "note": row["note"],
                        "project": row.get("project") or "",
                        "price": row.get("price") or "",
                        "queued_at": _normalize_queued_at(row.get("queued_at") or ""),
                        "status": "pending",
                        "created_at": _now(),
                        "created_ts": ts,
                        "done_at": "",
                        "source": "sheet",
                    },
                )
                existing.add(source_url)
                added += 1
            repair_misaligned_queue_items(items)
            _write_queue_file(items)
            total = len(items)
            replaced = False

    if replace:
        return {
            "added": added,
            "skipped": skipped,
            "preserved_working": preserved_working,
            "preserved_pending": preserved_pending,
            "total": total,
            "replaced": True,
        }
    return {"added": added, "skipped": skipped, "total": total, "replaced": False}


def queue_stats() -> dict:
    items = load_queue()
    return {
        "total": len(items),
        "pending": sum(1 for x in items if x.get("status") == "pending"),
        "working": sum(1 for x in items if x.get("status") == "working"),
        "done": sum(1 for x in items if x.get("status") == "done"),
    }
