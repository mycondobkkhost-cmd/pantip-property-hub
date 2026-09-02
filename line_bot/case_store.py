from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data" / "line_cases.json"

_lock = Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {"updated_at": _now(), "cases": {}}


def load_cases() -> dict[str, Any]:
    if not CASES_PATH.exists():
        return _empty()
    with _lock:
        raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "cases" not in raw:
        return _empty()
    return raw


def save_cases(data: dict[str, Any]) -> None:
    CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    with _lock:
        CASES_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def upsert_case(case: dict[str, Any]) -> dict[str, Any]:
    data = load_cases()
    key = case["id"]
    prev = data["cases"].get(key, {})
    merged = {**prev, **case}
    if "created_at" not in merged:
        merged["created_at"] = _now()
    merged["updated_at"] = _now()
    data["cases"][key] = merged
    save_cases(data)
    return merged


def get_case(case_id: str) -> dict[str, Any] | None:
    return load_cases()["cases"].get(case_id)


def find_cases(
    *,
    status: str | None = None,
    role: str | None = None,
    query: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    items = list(load_cases()["cases"].values())
    if status:
        items = [c for c in items if c.get("status") == status]
    if role:
        items = [c for c in items if c.get("role") == role]
    if query:
        q = query.lower().strip()
        items = [
            c
            for c in items
            if q in (c.get("display_name") or "").lower()
            or q in (c.get("user_id") or "").lower()
            or q in (c.get("id") or "").lower()
            or q in (c.get("last_text") or "").lower()
        ]
    items.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
    return items[:limit]


def link_user(display_name: str, user_id: str) -> dict[str, Any] | None:
    data = load_cases()
    target = None
    for case in data["cases"].values():
        if (case.get("display_name") or "").strip() == display_name.strip():
            target = case
            break
    if not target:
        # fuzzy contains
        for case in data["cases"].values():
            if display_name.strip().lower() in (case.get("display_name") or "").lower():
                target = case
                break
    if not target:
        return None
    target["user_id"] = user_id
    target["updated_at"] = _now()
    data["cases"][target["id"]] = target
    save_cases(data)
    return target


def touch_live_message(
    *,
    user_id: str,
    role: str,
    text: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Update or create a live case when webhook receives a message."""
    from line_bot.case_classifier import classify_from_last, classify_role

    data = load_cases()
    case = None
    for c in data["cases"].values():
        if c.get("user_id") == user_id:
            case = c
            break

    if case is None:
        case_id = f"live:{user_id}"
        case = {
            "id": case_id,
            "display_name": display_name or user_id[:10],
            "user_id": user_id,
            "role": "unknown",
            "status": "active",
            "source": "live",
            "last_text": "",
            "last_role": None,
            "notes": "",
            "created_at": _now(),
        }

    if role == "customer":
        case["last_customer_text"] = text[:500]
        # refine role from early texts if still unknown/end
        early = []
        if case.get("last_customer_text"):
            early.append(case["last_customer_text"])
        case["role"] = classify_role(case.get("display_name") or "", early)
    else:
        case["last_oa_text"] = text[:500]

    case["last_role"] = role
    case["last_text"] = text[:500]
    case["status"] = classify_from_last(last_role=role, last_text=text)
    case["source"] = case.get("source") or "live"
    case["updated_at"] = _now()
    if display_name:
        case["display_name"] = display_name

    data["cases"][case["id"]] = case
    save_cases(data)
    return case


def new_id(prefix: str = "case") -> str:
    return f"{prefix}:{uuid4().hex[:10]}"
