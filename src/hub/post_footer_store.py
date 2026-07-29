"""Reusable post footer / CTA snippets for group captions."""

from __future__ import annotations

import json
import re
import secrets
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORE_PATH = BASE_DIR / "data" / "post_footer_snippets.json"
_LOCK = threading.Lock()
BANGKOK = ZoneInfo("Asia/Bangkok")

_DEFAULT_SNIPPETS: list[dict[str, str]] = [
    {
        "id": "line_cta_th",
        "label": "LINE + เบอร์ (ไทย)",
        "text": (
            "📲 LINE ID : @PTP.CONDO\n"
            "📞 คุณนัท : 064-949-5556\n"
            "📞 คุณเปิ้ล : 092-269-4554\n"
            "\n"
            "สนใจนัดชม / ขอรายละเอียด แคปหน้าจอแล้วแอดไลน์ตามไอดีด้านบนได้เลยครับ 🙏"
        ),
    },
    {
        "id": "line_only",
        "label": "LINE ID อย่างเดียว",
        "text": "📲 LINE ID : @PTP.CONDO\n\nสนใจแคปหน้าจอแล้วแอดไลน์ได้เลยครับ 🙏",
    },
    {
        "id": "line_cta_en",
        "label": "LINE + phones (EN)",
        "text": (
            "📲 LINE ID : @PTP.CONDO\n"
            "📞 Nut : 064-949-5556\n"
            "📞 Pleng : 092-269-4554\n"
            "\n"
            "Add LINE from the ID above for viewing / more info 🙏"
        ),
    },
]


def _now_iso() -> str:
    return datetime.now(tz=BANGKOK).strftime("%Y-%m-%d %H:%M:%S")


def _default_store() -> dict[str, Any]:
    now = _now_iso()
    items = []
    for raw in _DEFAULT_SNIPPETS:
        items.append(
            {
                "id": raw["id"],
                "label": raw["label"],
                "text": raw["text"],
                "created_at": now,
                "updated_at": now,
            }
        )
    return {"items": items, "updated_at": now}


def _load_raw() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return _default_store()
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_store()
    if not isinstance(data, dict):
        return _default_store()
    if not isinstance(data.get("items"), list):
        data["items"] = []
    return data


def _save_raw(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now_iso()
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or "").strip()
    text = str(raw.get("text") or "").strip()
    if not label or not text:
        return None
    return {
        "id": str(raw.get("id") or "").strip() or secrets.token_hex(6),
        "label": label[:80],
        "text": text[:4000],
        "created_at": str(raw.get("created_at") or _now_iso()),
        "updated_at": str(raw.get("updated_at") or _now_iso()),
        "last_used_at": str(raw.get("last_used_at") or "").strip(),
    }


def list_snippets() -> list[dict[str, Any]]:
    with _LOCK:
        data = _load_raw()
        if not data.get("items"):
            data = _default_store()
            _save_raw(data)
        out: list[dict[str, Any]] = []
        for raw in data.get("items") or []:
            item = _normalize(raw) if isinstance(raw, dict) else None
            if item:
                out.append(item)
        return out


def get_active_id() -> str:
    with _LOCK:
        data = _load_raw()
        return str(data.get("active_id") or "").strip()


def get_latest_snippet() -> dict[str, Any] | None:
    """Prefer most recently used; else most recently updated/saved."""
    items = list_snippets()
    if not items:
        return None
    active = get_active_id()
    if active:
        for it in items:
            if str(it.get("id") or "") == active:
                return it
    used = [i for i in items if i.get("last_used_at")]
    pool = used or items

    def sort_key(it: dict[str, Any]) -> str:
        return str(it.get("last_used_at") or it.get("updated_at") or it.get("created_at") or "")

    return max(pool, key=sort_key)


def format_footer_with_code(text: str, code: str, *, ensure_code_line: bool = False) -> str:
    """Inject property code into footer placeholders; optionally prepend a code line."""
    code_s = (code or "").strip().lstrip("#")
    out = (text or "").strip()
    if not out:
        return ""
    if code_s:
        out = out.replace("{code}", code_s).replace("{CODE}", code_s)
        out = out.replace("#{code}", f"#{code_s}").replace("#{CODE}", f"#{code_s}")
        out = re.sub(r"#RXT\?{2,}|#CODE\b|#รหัส\b", f"#{code_s}", out, flags=re.I)
        if ensure_code_line and f"#{code_s}" not in out and code_s not in out:
            out = f"📌 รหัสทรัพย์ : #{code_s}\n\n{out}"
    return out.strip()


def mark_snippet_used(snippet_id: str) -> dict[str, Any] | None:
    want = (snippet_id or "").strip()
    if not want:
        return None
    with _LOCK:
        data = _load_raw()
        items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
        now = _now_iso()
        found = None
        for i, raw in enumerate(items):
            if str(raw.get("id") or "") != want:
                continue
            raw["last_used_at"] = now
            raw["updated_at"] = str(raw.get("updated_at") or now)
            items[i] = raw
            found = _normalize(raw)
            break
        if not found:
            return None
        data["items"] = items
        data["active_id"] = want
        _save_raw(data)
        return found


def upsert_snippet(
    *,
    snippet_id: str = "",
    label: str,
    text: str,
    mark_used: bool = True,
) -> dict[str, Any]:
    label = (label or "").strip()
    text = (text or "").strip()
    if not label:
        raise ValueError("ต้องมีชื่อชุดข้อความ")
    if not text:
        raise ValueError("ต้องมีเนื้อหาข้อความท้าย")
    want = (snippet_id or "").strip()
    with _LOCK:
        data = _load_raw()
        items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
        now = _now_iso()
        found = None
        for i, raw in enumerate(items):
            if want and str(raw.get("id") or "") == want:
                raw["label"] = label[:80]
                raw["text"] = text[:4000]
                raw["updated_at"] = now
                if mark_used:
                    raw["last_used_at"] = now
                if not raw.get("created_at"):
                    raw["created_at"] = now
                items[i] = raw
                found = _normalize(raw)
                break
        if not found:
            row = {
                "id": want or secrets.token_hex(6),
                "label": label[:80],
                "text": text[:4000],
                "created_at": now,
                "updated_at": now,
                "last_used_at": now if mark_used else "",
            }
            items.append(row)
            found = _normalize(row)
        data["items"] = items
        if found and mark_used:
            data["active_id"] = found["id"]
        _save_raw(data)
        return found or {}


def delete_snippet(snippet_id: str) -> bool:
    want = (snippet_id or "").strip()
    if not want:
        return False
    with _LOCK:
        data = _load_raw()
        items = [x for x in (data.get("items") or []) if isinstance(x, dict)]
        nxt = [x for x in items if str(x.get("id") or "") != want]
        if len(nxt) == len(items):
            return False
        data["items"] = nxt
        if str(data.get("active_id") or "") == want:
            data["active_id"] = ""
        _save_raw(data)
        return True
