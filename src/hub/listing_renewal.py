"""Listing renewal vs bump separation — Phase Z7 (TEST_ONLY)."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from src.hub.listing_freshness import compute_verification_due, mark_verified_available, upsert_freshness

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_DIR = BASE_DIR / ".local" / "listing_renewal_phase_z7"
EVENTS_PATH = LOCAL_DIR / "renewal_events.json"


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _load_events() -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    try:
        return list(json.loads(EVENTS_PATH.read_text(encoding="utf-8")).get("items") or [])
    except json.JSONDecodeError:
        return []


def _save_events(items: list[dict[str, Any]]) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_PATH.write_text(
        json.dumps({"items": items, "updated_at": _now(), "test_only": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def renew_listing(
    listing_id: str,
    *,
    verified_by: str = "operator",
    transaction: str = "rent",
    trigger_bump: bool = False,
) -> dict[str, Any]:
    """Owner confirms listing renewal — refreshes freshness TTL; bump is separate."""
    fresh = mark_verified_available(
        listing_id,
        verified_by=verified_by,
        verification_source="listing_renewal",
        transaction=transaction,
    )
    evt = {
        "event_id": f"lre_{uuid.uuid4().hex[:12]}",
        "event_type": "LISTING_RENEWED",
        "listing_id": listing_id,
        "verified_by": verified_by,
        "created_at": _now(),
        "test_only": True,
    }
    items = _load_events()
    items.append(evt)
    if trigger_bump:
        items.append(
            {
                "event_id": f"lbe_{uuid.uuid4().hex[:12]}",
                "event_type": "LISTING_BUMP_REQUESTED",
                "listing_id": listing_id,
                "created_at": _now(),
                "test_only": True,
            }
        )
    _save_events(items)
    return {"renewal_event": evt, "freshness": fresh, "bump_requested": trigger_bump, "test_only": True}


def request_bump_only(listing_id: str) -> dict[str, Any]:
    """Bump without verification refresh."""
    evt = {
        "event_id": f"lbe_{uuid.uuid4().hex[:12]}",
        "event_type": "LISTING_BUMP_REQUESTED",
        "listing_id": listing_id,
        "created_at": _now(),
        "test_only": True,
    }
    items = _load_events()
    items.append(evt)
    _save_events(items)
    return {"bump_event": evt, "verification_refreshed": False, "test_only": True}


def list_renewal_events(*, listing_id: str = "") -> list[dict[str, Any]]:
    items = _load_events()
    if listing_id:
        items = [x for x in items if x.get("listing_id") == listing_id]
    return items
