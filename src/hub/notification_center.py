"""Notification center foundation — Phase Z5 (local TEST_ONLY storage)."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.hub.lease_opportunity import list_opportunities, load_config, opportunity_summary
from src.hub.operational_contracts import NOTIFICATION_EVENT_CONTRACT

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_DIR = BASE_DIR / ".local" / "lease_opportunity_phase_z5"
EVENTS_PATH = LOCAL_DIR / "notification_events.json"

PANTIP_MVP_EVENT_TYPES = frozenset(
    {
        "FOLLOW_UP_OVERDUE",
        "FOLLOW_UP_DUE_TODAY",
        "LEASE_END_WITHIN_14_DAYS",
        "LEASE_END_WITHIN_30_DAYS",
        "LEASE_END_WITHIN_60_DAYS",
        "OWNER_CONFIRMED_VACANT_SOON",
    }
)

DELIVERY_CHANNELS = frozenset({"WEB_NOTIFICATION", "HUB_NOTIFICATION"})
OTP_IS_NOT_NOTIFICATION = True


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> date:
    return date.today()


def _load_events_raw() -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    try:
        data = json.loads(EVENTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(data.get("items") or [])


def _save_events(items: list[dict[str, Any]]) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_PATH.write_text(
        json.dumps({"items": items, "updated_at": _now(), "test_only": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_day(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _normalize_event(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item)
    item.setdefault("notification_event_id", "")
    item.setdefault("event_type", "")
    item.setdefault("recipient_user_id", "")
    item.setdefault("related_entity_type", "lease_opportunity")
    item.setdefault("related_entity_id", "")
    item.setdefault("created_at", "")
    item.setdefault("read_at", "")
    item.setdefault("dismissed_at", "")
    item.setdefault("dedupe_key", "")
    item.setdefault("priority", "normal")
    item.setdefault("delivery_channel", "HUB_NOTIFICATION")
    item.setdefault("test_only", True)
    return item


def list_notification_events(*, recipient_user_id: str = "", include_dismissed: bool = False) -> list[dict[str, Any]]:
    items = [_normalize_event(x) for x in _load_events_raw()]
    uid = (recipient_user_id or "").strip()
    if uid:
        items = [x for x in items if x.get("recipient_user_id") == uid]
    if not include_dismissed:
        items = [x for x in items if not x.get("dismissed_at")]
    return sorted(items, key=lambda x: (x.get("read_at") != "", x.get("created_at") or ""), reverse=True)


def unread_count(recipient_user_id: str = "") -> int:
    return sum(1 for e in list_notification_events(recipient_user_id=recipient_user_id) if not e.get("read_at"))


def create_notification_event(
    *,
    event_type: str,
    recipient_user_id: str,
    related_entity_type: str,
    related_entity_id: str,
    dedupe_key: str,
    priority: str = "normal",
    delivery_channel: str = "HUB_NOTIFICATION",
) -> dict[str, Any] | None:
    if event_type not in PANTIP_MVP_EVENT_TYPES:
        raise ValueError(f"unsupported event_type: {event_type}")
    if delivery_channel not in DELIVERY_CHANNELS:
        raise ValueError(f"unsupported delivery_channel: {delivery_channel}")

    items = _load_events_raw()
    today = _today().isoformat()
    full_dedupe = f"{dedupe_key}::{today}"
    for it in items:
        if it.get("dedupe_key") == full_dedupe and not it.get("dismissed_at"):
            return None  # no duplicate daily alerts

    evt = _normalize_event(
        {
            "notification_event_id": f"ne_{uuid.uuid4().hex[:12]}",
            "event_type": event_type,
            "recipient_user_id": recipient_user_id,
            "related_entity_type": related_entity_type,
            "related_entity_id": related_entity_id,
            "created_at": _now(),
            "dedupe_key": full_dedupe,
            "priority": priority,
            "delivery_channel": delivery_channel,
            "test_only": True,
        }
    )
    items.append(evt)
    _save_events(items)
    return evt


def mark_read(notification_event_id: str) -> dict[str, Any]:
    items = _load_events_raw()
    nid = (notification_event_id or "").strip()
    for i, it in enumerate(items):
        if it.get("notification_event_id") == nid:
            it = dict(it)
            it["read_at"] = _now()
            items[i] = it
            _save_events(items)
            return _normalize_event(it)
    raise ValueError("notification not found")


def mark_dismissed(notification_event_id: str) -> dict[str, Any]:
    items = _load_events_raw()
    nid = (notification_event_id or "").strip()
    for i, it in enumerate(items):
        if it.get("notification_event_id") == nid:
            it = dict(it)
            it["dismissed_at"] = _now()
            items[i] = it
            _save_events(items)
            return _normalize_event(it)
    raise ValueError("notification not found")


def sync_notifications_from_opportunities(*, recipient_user_id: str) -> list[dict[str, Any]]:
    """Generate notification events from current opportunities (TEST_ONLY)."""
    created: list[dict[str, Any]] = []
    today = _today()
    windows = load_config().get("follow_up_windows_days") or [60, 45, 30, 14]

    for opp in list_opportunities():
        oid = opp.get("opportunity_id") or ""
        end = _parse_day(opp.get("expected_lease_end_date"))
        nxt = _parse_day(opp.get("next_followup_at"))

        if opp.get("opportunity_status") == "OWNER_CONFIRMED_VACANT_SOON":
            evt = create_notification_event(
                event_type="OWNER_CONFIRMED_VACANT_SOON",
                recipient_user_id=recipient_user_id,
                related_entity_type="lease_opportunity",
                related_entity_id=oid,
                dedupe_key=f"owner_confirmed::{oid}",
                priority="high",
            )
            if evt:
                created.append(evt)
            continue

        if nxt and nxt < today:
            evt = create_notification_event(
                event_type="FOLLOW_UP_OVERDUE",
                recipient_user_id=recipient_user_id,
                related_entity_type="lease_opportunity",
                related_entity_id=oid,
                dedupe_key=f"follow_up_overdue::{oid}",
                priority="high",
            )
            if evt:
                created.append(evt)
        elif nxt and nxt == today:
            evt = create_notification_event(
                event_type="FOLLOW_UP_DUE_TODAY",
                recipient_user_id=recipient_user_id,
                related_entity_type="lease_opportunity",
                related_entity_id=oid,
                dedupe_key=f"follow_up_due::{oid}",
            )
            if evt:
                created.append(evt)

        if end:
            days = (end - today).days
            if days <= 14:
                t = "LEASE_END_WITHIN_14_DAYS"
            elif days <= 30:
                t = "LEASE_END_WITHIN_30_DAYS"
            elif days <= 60:
                t = "LEASE_END_WITHIN_60_DAYS"
            else:
                t = None
            if t:
                evt = create_notification_event(
                    event_type=t,
                    recipient_user_id=recipient_user_id,
                    related_entity_type="lease_opportunity",
                    related_entity_id=oid,
                    dedupe_key=f"{t.lower()}::{oid}",
                )
                if evt:
                    created.append(evt)

    return created


def build_api_payload(*, recipient_user_id: str = "") -> dict[str, Any]:
    return {
        "ok": True,
        "test_only": True,
        "contract_version": NOTIFICATION_EVENT_CONTRACT["version"],
        "otp_is_notification_channel": False,
        "delivery_channels": sorted(DELIVERY_CHANNELS),
        "event_types": sorted(PANTIP_MVP_EVENT_TYPES),
        "unread_count": unread_count(recipient_user_id),
        "summary": opportunity_summary(),
        "events": list_notification_events(recipient_user_id=recipient_user_id),
    }
