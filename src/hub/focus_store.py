"""Hub Focus properties — shortlist for ops (ไม่ผูกคอลัมน์ชีท).

Store: data/focus_properties.json
Each item: property id (+ code snapshot) that the team is actively pushing.
Add/remove by property code (resolved against Hub properties).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FOCUS_PATH = BASE_DIR / "data" / "focus_properties.json"

_CODE_SPLIT_RE = re.compile(r"[,;\s]+")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _normalize_code(code: str) -> str:
    return str(code or "").strip().upper().replace(" ", "")


def parse_focus_codes(raw: str | list | None) -> list[str]:
    """Split one or many codes from a string / list (comma/space/semicolon)."""
    if raw is None:
        return []
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            parts.extend(parse_focus_codes(str(item)))
        return parts
    text = str(raw).strip()
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for part in _CODE_SPLIT_RE.split(text):
        code = _normalize_code(part)
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _normalize_item(item: dict) -> dict | None:
    pid = str(item.get("id") or "").strip()
    if not pid:
        return None
    return {
        "id": pid,
        "code": _normalize_code(item.get("code") or ""),
        "pinned_at": str(item.get("pinned_at") or "").strip() or _now(),
    }


def load_focus() -> list[dict]:
    if not FOCUS_PATH.exists():
        return []
    try:
        data = json.loads(FOCUS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        raw = data.get("items") or data.get("ids") or []
    elif isinstance(data, list):
        raw = data
    else:
        raw = []
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            entry = {"id": entry}
        if not isinstance(entry, dict):
            continue
        item = _normalize_item(entry)
        if not item or item["id"] in seen:
            continue
        seen.add(item["id"])
        out.append(item)
    return out


def save_focus(items: list[dict]) -> None:
    FOCUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = []
    seen: set[str] = set()
    for entry in items:
        item = _normalize_item(dict(entry))
        if not item or item["id"] in seen:
            continue
        seen.add(item["id"])
        normalized.append(item)
    FOCUS_PATH.write_text(
        json.dumps(
            {"items": normalized, "updated_at": _now()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def list_focus() -> list[dict]:
    items = load_focus()
    # newest pin first
    return sorted(items, key=lambda x: x.get("pinned_at") or "", reverse=True)


def focus_ids() -> set[str]:
    return {x["id"] for x in load_focus()}


def focus_stats() -> dict:
    items = load_focus()
    return {"total": len(items)}


def is_focused(property_id: str) -> bool:
    pid = (property_id or "").strip()
    return bool(pid) and pid in focus_ids()


def find_property_by_code(properties: list[dict], code: str) -> dict | None:
    want = _normalize_code(code)
    if not want:
        return None
    for prop in properties or []:
        if _normalize_code(prop.get("code") or "") == want:
            return prop
    return None


def find_focus_item(ref: str) -> dict | None:
    """Find a focus entry by property id or code."""
    key = (ref or "").strip()
    if not key:
        return None
    code = _normalize_code(key)
    for item in load_focus():
        if item["id"] == key or item.get("code") == code:
            return item
    return None


def add_focus(property_id: str, code: str = "") -> dict:
    pid = (property_id or "").strip()
    if not pid:
        raise ValueError("missing property id")
    items = load_focus()
    for it in items:
        if it["id"] == pid:
            if code and not it.get("code"):
                it["code"] = _normalize_code(code)
                save_focus(items)
            return it
    item = {
        "id": pid,
        "code": _normalize_code(code),
        "pinned_at": _now(),
    }
    items.append(item)
    save_focus(items)
    return item


def add_focus_by_code(code: str, properties: list[dict]) -> dict:
    """Resolve code → property, then add. Raises ValueError if not found."""
    codes = parse_focus_codes(code)
    if not codes:
        raise ValueError("กรุณาระบุรหัสทรัพย์")
    want = codes[0]
    prop = find_property_by_code(properties, want)
    if not prop:
        raise ValueError(f"ไม่พบรหัส {want}")
    pid = str(prop.get("id") or "").strip()
    if not pid:
        raise ValueError(f"ไม่พบรหัส {want}")
    return add_focus(pid, code=_normalize_code(prop.get("code") or want))


def add_focus_codes(raw_codes: str | list, properties: list[dict]) -> dict:
    """Add one or many codes. Returns {added, skipped, errors, items, stats}."""
    codes = parse_focus_codes(raw_codes)
    if not codes:
        raise ValueError("กรุณาระบุรหัสทรัพย์")
    added: list[dict] = []
    skipped: list[str] = []
    errors: list[dict] = []
    for code in codes:
        try:
            prop = find_property_by_code(properties, code)
            if not prop:
                errors.append({"code": code, "error": f"ไม่พบรหัส {code}"})
                continue
            pid = str(prop.get("id") or "").strip()
            if not pid:
                errors.append({"code": code, "error": f"ไม่พบรหัส {code}"})
                continue
            if is_focused(pid):
                skipped.append(code)
                continue
            item = add_focus(pid, code=_normalize_code(prop.get("code") or code))
            added.append(item)
        except ValueError as exc:
            errors.append({"code": code, "error": str(exc)})
    if not added and errors and not skipped:
        # all failed — surface first error as ValueError for simple clients
        raise ValueError(errors[0]["error"])
    return {
        "added": added,
        "skipped": skipped,
        "errors": errors,
        "items": list_focus(),
        "stats": focus_stats(),
    }


def remove_focus(property_id: str) -> bool:
    pid = (property_id or "").strip()
    if not pid:
        raise ValueError("missing property id")
    items = load_focus()
    next_items = [x for x in items if x["id"] != pid]
    if len(next_items) == len(items):
        return False
    save_focus(next_items)
    return True


def remove_focus_ref(ref: str) -> dict:
    """Remove by property id or code. Returns {removed, item, stats}."""
    key = (ref or "").strip()
    if not key:
        raise ValueError("กรุณาระบุรหัสหรือ id")
    item = find_focus_item(key)
    if not item:
        raise ValueError(f"ไม่พบใน Focus: {key}")
    remove_focus(item["id"])
    return {"removed": True, "item": item, "stats": focus_stats()}


def toggle_focus(property_id: str, code: str = "") -> dict:
    """Toggle pin. Returns {focused, item, stats}. Kept for compatibility."""
    pid = (property_id or "").strip()
    if not pid:
        raise ValueError("missing property id")
    if is_focused(pid):
        remove_focus(pid)
        return {"focused": False, "item": None, "stats": focus_stats()}
    item = add_focus(pid, code=code)
    return {"focused": True, "item": item, "stats": focus_stats()}
