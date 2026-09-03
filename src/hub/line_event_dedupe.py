#!/usr/bin/env python3
"""Durable LINE webhook event deduplication (offline-safe, local JSON store)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORE_PATH = BASE_DIR / "data" / "line_event_dedupe.json"
_LOCK = threading.RLock()

STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_NEEDS_RECONCILE = "needs_reconcile"

DEFAULT_TTL_SEC = 72 * 3600
# Crash before outbound: allow reclaim after this (safe — no send yet).
PROCESSING_STALE_SEC = 15 * 60


def _now() -> float:
    return time.time()


def _load() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return {"events": {}, "updated_at": 0}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"events": {}, "updated_at": 0}
    if not isinstance(data, dict):
        return {"events": {}, "updated_at": 0}
    events = data.get("events")
    if not isinstance(events, dict):
        data["events"] = {}
    return data


def _save(data: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = _now()
    tmp = STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE_PATH)


def event_key_from_line_event(event: dict[str, Any]) -> str | None:
    """Prefer webhookEventId; conservative fallback only when stable ids exist."""
    if not isinstance(event, dict):
        return None
    wid = str(event.get("webhookEventId") or "").strip()
    if wid:
        return f"wev:{wid}"
    # Fallback: message.id is stable for message events; do not use text/user/time alone.
    msg = event.get("message") if isinstance(event.get("message"), dict) else {}
    mid = str(msg.get("id") or "").strip()
    if mid:
        return f"msg:{mid}"
    return None


def cleanup_expired(*, now: float | None = None, ttl_sec: int = DEFAULT_TTL_SEC) -> int:
    now = _now() if now is None else float(now)
    removed = 0
    with _LOCK:
        data = _load()
        events = data.get("events") or {}
        keep: dict[str, Any] = {}
        for key, row in events.items():
            if not isinstance(row, dict):
                removed += 1
                continue
            updated = float(row.get("updated_at") or row.get("created_at") or 0)
            st = str(row.get("status") or "")
            # Always retain non-terminal processing briefly; expire terminal by TTL.
            if st in {STATUS_COMPLETED, STATUS_NEEDS_RECONCILE} and updated and (now - updated) > ttl_sec:
                removed += 1
                continue
            keep[key] = row
        data["events"] = keep
        _save(data)
    return removed


def claim_event(
    event_key: str,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Atomic claim. Returns {ok, status, action} where action is claimed|duplicate|ambiguous."""
    key = (event_key or "").strip()
    if not key:
        return {"ok": False, "action": "no_key", "status": ""}
    now = _now() if now is None else float(now)
    with _LOCK:
        data = _load()
        events = data.setdefault("events", {})
        row = events.get(key)
        if isinstance(row, dict):
            st = str(row.get("status") or "")
            if st == STATUS_COMPLETED:
                return {"ok": False, "action": "duplicate_completed", "status": st, "record": dict(row)}
            if st == STATUS_NEEDS_RECONCILE:
                return {"ok": False, "action": "ambiguous", "status": st, "record": dict(row)}
            if st == STATUS_PROCESSING:
                # If outbound may have started → ambiguous; else treat as in-flight duplicate
                # unless processing is stale (crash before send) → safe reclaim.
                if row.get("outbound_started_at"):
                    return {"ok": False, "action": "ambiguous", "status": st, "record": dict(row)}
                created = float(row.get("created_at") or row.get("updated_at") or 0)
                if created and (now - created) > PROCESSING_STALE_SEC:
                    # Safe reclaim — outbound never marked started.
                    pass
                else:
                    return {"ok": False, "action": "duplicate_processing", "status": st, "record": dict(row)}
        events[key] = {
            "key": key,
            "status": STATUS_PROCESSING,
            "created_at": now,
            "updated_at": now,
            "outbound_started_at": None,
            "completed_at": None,
        }
        _save(data)
        return {"ok": True, "action": "claimed", "status": STATUS_PROCESSING, "record": dict(events[key])}


def mark_outbound_started(event_key: str, *, now: float | None = None) -> dict[str, Any]:
    key = (event_key or "").strip()
    now = _now() if now is None else float(now)
    with _LOCK:
        data = _load()
        row = (data.get("events") or {}).get(key)
        if not isinstance(row, dict):
            return {"ok": False, "error": "not_found"}
        if not row.get("outbound_started_at"):
            row["outbound_started_at"] = now
        row["updated_at"] = now
        data["events"][key] = row
        _save(data)
        return {"ok": True, "record": dict(row)}


def mark_completed(event_key: str, *, now: float | None = None) -> dict[str, Any]:
    key = (event_key or "").strip()
    now = _now() if now is None else float(now)
    with _LOCK:
        data = _load()
        row = (data.get("events") or {}).get(key)
        if not isinstance(row, dict):
            return {"ok": False, "error": "not_found"}
        row["status"] = STATUS_COMPLETED
        row["completed_at"] = now
        row["updated_at"] = now
        data["events"][key] = row
        _save(data)
        return {"ok": True, "record": dict(row)}


def mark_needs_reconcile(event_key: str, *, reason: str = "", now: float | None = None) -> dict[str, Any]:
    key = (event_key or "").strip()
    now = _now() if now is None else float(now)
    with _LOCK:
        data = _load()
        row = (data.get("events") or {}).get(key)
        if not isinstance(row, dict):
            return {"ok": False, "error": "not_found"}
        row["status"] = STATUS_NEEDS_RECONCILE
        row["reason"] = (reason or "")[:300]
        row["updated_at"] = now
        data["events"][key] = row
        _save(data)
        return {"ok": True, "record": dict(row)}


def get_event(event_key: str) -> dict[str, Any] | None:
    key = (event_key or "").strip()
    with _LOCK:
        row = (_load().get("events") or {}).get(key)
        return dict(row) if isinstance(row, dict) else None


class LineReconcileError(Exception):
    def __init__(self, message: str, *, code: str = "invalid", http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


LINE_ACTION_MARK_COMPLETED = "mark_completed"
LINE_ACTION_ALLOW_REPROCESS = "allow_reprocess"
LINE_ACTION_SUPPRESS = "suppress"
LINE_ACTION_KEEP = "keep_unresolved"

LINE_RECONCILE_ACTIONS = {
    LINE_ACTION_MARK_COMPLETED,
    LINE_ACTION_ALLOW_REPROCESS,
    LINE_ACTION_SUPPRESS,
    LINE_ACTION_KEEP,
}


def list_needs_reconcile_events(*, limit: int = 100) -> list[dict[str, Any]]:
    """Ambiguous LINE events needing operator attention. No message text/PII."""
    cleanup_expired()
    with _LOCK:
        events = (_load().get("events") or {})
    out: list[dict[str, Any]] = []
    for key, row in events.items():
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") != STATUS_NEEDS_RECONCILE:
            continue
        out.append(
            {
                "key": key,
                "status": row.get("status"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
                "outbound_started_at": row.get("outbound_started_at"),
                "reason": str(row.get("reason") or "")[:200],
                "reconciled_at": row.get("reconciled_at"),
                "reconciliation_action": row.get("reconciliation_action"),
            }
        )
        if len(out) >= max(1, min(int(limit or 100), 500)):
            break
    out.sort(key=lambda r: float(r.get("updated_at") or 0), reverse=True)
    return out


def reconcile_line_event(
    event_key: str,
    *,
    action: str,
    operator: str = "",
    now: float | None = None,
) -> dict[str, Any]:
    """Operator reconciliation. Never sends a LINE message."""
    key = (event_key or "").strip()
    act = (action or "").strip().lower()
    now = _now() if now is None else float(now)
    if not key:
        raise LineReconcileError("event_key is required", code="missing_key", http_status=400)
    if act not in LINE_RECONCILE_ACTIONS:
        raise LineReconcileError("invalid action", code="invalid_action", http_status=400)

    with _LOCK:
        data = _load()
        events = data.setdefault("events", {})
        row = events.get(key)
        if not isinstance(row, dict):
            raise LineReconcileError("event not found", code="not_found", http_status=404)
        st = str(row.get("status") or "")
        if act == LINE_ACTION_KEEP:
            if st != STATUS_NEEDS_RECONCILE:
                raise LineReconcileError("event is not awaiting reconciliation", code="invalid_state", http_status=409)
            return dict(row)
        if st == STATUS_COMPLETED and act == LINE_ACTION_MARK_COMPLETED:
            return dict(row)  # duplicate confirm harmless
        if st != STATUS_NEEDS_RECONCILE:
            raise LineReconcileError("event is not awaiting reconciliation", code="invalid_state", http_status=409)

        # Preserve identity + outbound evidence; never store tokens.
        row["reconciled_at"] = now
        row["reconciliation_action"] = act
        row["reconciled_by"] = (operator or "")[:80]
        row["updated_at"] = now

        if act == LINE_ACTION_MARK_COMPLETED:
            row["status"] = STATUS_COMPLETED
            row["completed_at"] = now
        elif act == LINE_ACTION_ALLOW_REPROCESS:
            # Explicit only: clear to allow a future claim. Does not send.
            events.pop(key, None)
            data["events"] = events
            _save(data)
            return {
                "ok": True,
                "key": key,
                "status": "cleared_for_reprocess",
                "reconciliation_action": act,
                "reconciled_at": now,
                "reconciled_by": (operator or "")[:80],
            }
        elif act == LINE_ACTION_SUPPRESS:
            row["status"] = STATUS_COMPLETED
            row["completed_at"] = now
            row["suppressed"] = True

        events[key] = row
        data["events"] = events
        _save(data)
        return dict(row)