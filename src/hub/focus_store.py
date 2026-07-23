"""Hub Focus properties — pinned shortlist for ops (ไม่ผูกคอลัมน์ชีท).

Store: data/focus_properties.json
Each item: property id (+ code snapshot) that the team is actively pushing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
FOCUS_PATH = BASE_DIR / "data" / "focus_properties.json"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _normalize_item(item: dict) -> dict | None:
    pid = str(item.get("id") or "").strip()
    if not pid:
        return None
    return {
        "id": pid,
        "code": str(item.get("code") or "").strip().upper(),
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


def add_focus(property_id: str, code: str = "") -> dict:
    pid = (property_id or "").strip()
    if not pid:
        raise ValueError("missing property id")
    items = load_focus()
    for it in items:
        if it["id"] == pid:
            if code and not it.get("code"):
                it["code"] = str(code).strip().upper()
                save_focus(items)
            return it
    item = {
        "id": pid,
        "code": str(code or "").strip().upper(),
        "pinned_at": _now(),
    }
    items.append(item)
    save_focus(items)
    return item


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


def toggle_focus(property_id: str, code: str = "") -> dict:
    """Toggle pin. Returns {focused, item, stats}."""
    pid = (property_id or "").strip()
    if not pid:
        raise ValueError("missing property id")
    if is_focused(pid):
        remove_focus(pid)
        return {"focused": False, "item": None, "stats": focus_stats()}
    item = add_focus(pid, code=code)
    return {"focused": True, "item": item, "stats": focus_stats()}
