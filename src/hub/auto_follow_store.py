"""Auto-follow property codes for publish / comment campaigns.

Store: data/auto_follow.json
Lists under keys publish | comment — used by Follow sub-tabs and
pulled into โพสกลุ่มอัตโนมัติ / คอมเมนต์กลุ่ม.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from src.hub.focus_store import (
    _normalize_code,
    _now,
    find_property_by_code,
    parse_focus_codes,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
AUTO_FOLLOW_PATH = BASE_DIR / "data" / "auto_follow.json"

KINDS = ("publish", "comment")

_LOCK = threading.RLock()


def _empty() -> dict[str, Any]:
    return {"publish": [], "comment": [], "updated_at": ""}


def _normalize_item(item: dict) -> dict | None:
    code = _normalize_code(item.get("code") or "")
    pid = str(item.get("id") or "").strip()
    if not code and not pid:
        return None
    return {
        "id": pid or code,
        "code": code or _normalize_code(pid),
        "note": str(item.get("note") or "").strip(),
        "pinned_at": str(item.get("pinned_at") or "").strip() or _now(),
    }


def _load_raw() -> dict[str, Any]:
    if not AUTO_FOLLOW_PATH.exists():
        return _empty()
    try:
        data = json.loads(AUTO_FOLLOW_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    out = _empty()
    for kind in KINDS:
        raw = data.get(kind) or []
        if not isinstance(raw, list):
            continue
        items: list[dict] = []
        seen: set[str] = set()
        for entry in raw:
            if isinstance(entry, str):
                entry = {"code": entry}
            if not isinstance(entry, dict):
                continue
            item = _normalize_item(entry)
            if not item:
                continue
            key = item["code"] or item["id"]
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
        out[kind] = items
    out["updated_at"] = str(data.get("updated_at") or "")
    return out


def _save_raw(data: dict[str, Any]) -> None:
    AUTO_FOLLOW_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "publish": data.get("publish") or [],
        "comment": data.get("comment") or [],
        "updated_at": _now(),
    }
    AUTO_FOLLOW_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _norm_kind(kind: str | None) -> str:
    k = str(kind or "").strip().lower()
    if k in {"post", "posts", "group_post", "group-post"}:
        return "publish"
    if k in {"comments", "group_comment", "group-comment"}:
        return "comment"
    if k not in KINDS:
        raise ValueError("kind ต้องเป็น publish หรือ comment")
    return k


def list_auto_follow(kind: str | None = None) -> dict[str, Any]:
    with _LOCK:
        data = _load_raw()
    if kind:
        k = _norm_kind(kind)
        items = sorted(data.get(k) or [], key=lambda x: x.get("pinned_at") or "", reverse=True)
        return {
            "kind": k,
            "items": items,
            "codes": [x["code"] for x in items if x.get("code")],
            "stats": {"total": len(items)},
            "updated_at": data.get("updated_at") or "",
        }
    result: dict[str, Any] = {"updated_at": data.get("updated_at") or "", "lists": {}}
    for k in KINDS:
        items = sorted(data.get(k) or [], key=lambda x: x.get("pinned_at") or "", reverse=True)
        result["lists"][k] = {
            "items": items,
            "codes": [x["code"] for x in items if x.get("code")],
            "stats": {"total": len(items)},
        }
    result["stats"] = {
        "publish": len(result["lists"]["publish"]["items"]),
        "comment": len(result["lists"]["comment"]["items"]),
    }
    return result


def list_codes(kind: str) -> list[str]:
    row = list_auto_follow(kind)
    return list(row.get("codes") or [])


def add_codes(kind: str, raw_codes: str | list, properties: list[dict]) -> dict[str, Any]:
    k = _norm_kind(kind)
    codes = parse_focus_codes(raw_codes)
    if not codes:
        raise ValueError("กรุณาระบุรหัสทรัพย์")
    added: list[dict] = []
    skipped: list[str] = []
    errors: list[dict] = []
    with _LOCK:
        data = _load_raw()
        items = list(data.get(k) or [])
        by_code = {_normalize_code(x.get("code") or ""): x for x in items}
        for code in codes:
            prop = find_property_by_code(properties, code)
            if not prop:
                errors.append({"code": code, "error": f"ไม่พบรหัส {code}"})
                continue
            want = _normalize_code(prop.get("code") or code)
            pid = str(prop.get("id") or "").strip() or want
            if want in by_code:
                skipped.append(want)
                continue
            item = {
                "id": pid,
                "code": want,
                "note": "",
                "pinned_at": _now(),
            }
            items.append(item)
            by_code[want] = item
            added.append(item)
        data[k] = items
        _save_raw(data)
    snap = list_auto_follow(k)
    return {
        "kind": k,
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "items": snap["items"],
        "codes": snap["codes"],
        "stats": snap["stats"],
    }


def remove_ref(kind: str, *, property_id: str = "", code: str = "") -> dict[str, Any]:
    k = _norm_kind(kind)
    pid = str(property_id or "").strip()
    want = _normalize_code(code)
    if not pid and not want:
        raise ValueError("ระบุ id หรือ code")
    removed = False
    with _LOCK:
        data = _load_raw()
        before = list(data.get(k) or [])
        after: list[dict] = []
        for it in before:
            if pid and str(it.get("id") or "") == pid:
                removed = True
                continue
            if want and _normalize_code(it.get("code") or "") == want:
                removed = True
                continue
            after.append(it)
        if not removed:
            raise ValueError("ไม่พบรายการในฟอโล่ว")
        data[k] = after
        _save_raw(data)
    snap = list_auto_follow(k)
    return {
        "kind": k,
        "removed": True,
        "items": snap["items"],
        "codes": snap["codes"],
        "stats": snap["stats"],
    }
