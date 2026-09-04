"""Pantip listing freshness foundation — Phase Z6 (aligned to RealXtate verification model)."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_DIR = BASE_DIR / ".local" / "listing_freshness_phase_z6"
FRESHNESS_PATH = LOCAL_DIR / "listing_freshness.json"

# RealXtate marketplace_availability + Pantip conceptual overlay
REALXTATE_AVAILABILITY = frozenset(
    {"available", "unavailable", "pending_verification", "expired", "unknown"}
)

PANTIP_FRESHNESS_STATES = frozenset(
    {
        "VERIFIED_AVAILABLE",
        "VERIFICATION_DUE",
        "VERIFICATION_OVERDUE",
        "STALE_UNCONFIRMED",
        "OWNER_REPORTED_UNAVAILABLE",
        "RENTED",
        "SOLD",
        "PAUSED",
    }
)

FRESHNESS_EVENTS = frozenset(
    {
        "LISTING_VERIFICATION_DUE",
        "LISTING_VERIFIED_AVAILABLE",
        "LISTING_VERIFICATION_OVERDUE",
        "LISTING_BECAME_STALE",
        "LISTING_MARKED_UNAVAILABLE",
        "LISTING_BUMP_REQUESTED",
    }
)

# RealXtate TTL: rent 7 days, sale 30 days
DEFAULT_TTL_DAYS = {"rent": 7, "sale": 30}

REALXTATE_TO_PANTIP_MAP = {
    "available": "VERIFIED_AVAILABLE",
    "pending_verification": "VERIFICATION_DUE",
    "expired": "STALE_UNCONFIRMED",
    "unknown": "STALE_UNCONFIRMED",
    "unavailable": "OWNER_REPORTED_UNAVAILABLE",
}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _parse_day(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _load_items() -> list[dict[str, Any]]:
    if not FRESHNESS_PATH.exists():
        return []
    try:
        data = json.loads(FRESHNESS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(data.get("items") or [])


def _save_items(items: list[dict[str, Any]]) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    FRESHNESS_PATH.write_text(
        json.dumps({"items": items, "updated_at": _now(), "test_only": True}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    item = dict(item)
    item.setdefault("listing_id", "")
    item.setdefault("property_id", "")
    item.setdefault("availability_state", "STALE_UNCONFIRMED")
    item.setdefault("last_verified_at", "")
    item.setdefault("verification_due_at", "")
    item.setdefault("stale_at", "")
    item.setdefault("verification_source", "")
    item.setdefault("verified_by", "")
    item.setdefault("realxtate_public_availability", "unknown")
    item.setdefault("test_only", True)
    return item


def compute_verification_due(*, last_verified_at: str, transaction: str = "rent") -> str:
    lv = _parse_day(last_verified_at)
    if not lv:
        return ""
    ttl = DEFAULT_TTL_DAYS.get(transaction, 7)
    return (lv + timedelta(days=ttl)).isoformat()


def derive_freshness_state(item: dict[str, Any], *, today: date | None = None) -> str:
    today = today or date.today()
    base = item.get("availability_state") or "STALE_UNCONFIRMED"
    if base in {"OWNER_REPORTED_UNAVAILABLE", "RENTED", "SOLD", "PAUSED"}:
        return base
    due = _parse_day(item.get("verification_due_at"))
    verified = _parse_day(item.get("last_verified_at"))
    if verified and (today - verified).days <= 1:
        return "VERIFIED_AVAILABLE"
    if due:
        if today > due:
            overdue_days = (today - due).days
            if overdue_days > 7:
                return "STALE_UNCONFIRMED"
            return "VERIFICATION_OVERDUE"
        if (due - today).days <= 2:
            return "VERIFICATION_DUE"
    return base if base != "VERIFIED_AVAILABLE" else "STALE_UNCONFIRMED"


def upsert_freshness(**fields: Any) -> dict[str, Any]:
    listing_id = str(fields.get("listing_id") or fields.get("property_id") or "")
    if not listing_id:
        raise ValueError("listing_id or property_id required")
    items = _load_items()
    now = _now()
    for i, it in enumerate(items):
        if it.get("listing_id") == listing_id or it.get("property_id") == listing_id:
            merged = _normalize({**it, **fields, "updated_at": now})
            if fields.get("last_verified_at") and not merged.get("verification_due_at"):
                merged["verification_due_at"] = compute_verification_due(
                    last_verified_at=merged["last_verified_at"],
                    transaction=fields.get("transaction", "rent"),
                )
            merged["availability_state"] = derive_freshness_state(merged)
            items[i] = merged
            _save_items(items)
            return merged
    rec = _normalize({**fields, "listing_id": listing_id, "created_at": now, "updated_at": now})
    if rec.get("last_verified_at"):
        rec["verification_due_at"] = compute_verification_due(
            last_verified_at=rec["last_verified_at"],
            transaction=fields.get("transaction", "rent"),
        )
    rec["availability_state"] = derive_freshness_state(rec)
    items.append(rec)
    _save_items(items)
    return rec


def mark_verified_available(
    listing_id: str,
    *,
    verified_by: str = "operator",
    verification_source: str = "hub_pilot",
    transaction: str = "rent",
) -> dict[str, Any]:
    today = date.today().isoformat()
    return upsert_freshness(
        listing_id=listing_id,
        availability_state="VERIFIED_AVAILABLE",
        last_verified_at=today,
        verification_due_at=compute_verification_due(last_verified_at=today, transaction=transaction),
        verified_by=verified_by,
        verification_source=verification_source,
        realxtate_public_availability="available",
    )


def seed_test_fixtures() -> list[dict[str, Any]]:
    today = date.today()
    fixtures = [
        ("test_listing_verified_today", today.isoformat(), "rent"),
        ("test_listing_due_soon", (today - timedelta(days=6)).isoformat(), "rent"),
        ("test_listing_overdue", (today - timedelta(days=10)).isoformat(), "rent"),
        ("test_listing_stale", (today - timedelta(days=20)).isoformat(), "rent"),
        ("test_listing_unavailable", "", "rent"),
        ("test_listing_rented", "", "rent"),
    ]
    out = []
    for lid, verified, txn in fixtures:
        if lid == "test_listing_unavailable":
            out.append(
                upsert_freshness(
                    listing_id=lid,
                    availability_state="OWNER_REPORTED_UNAVAILABLE",
                    realxtate_public_availability="unavailable",
                )
            )
        elif lid == "test_listing_rented":
            out.append(upsert_freshness(listing_id=lid, availability_state="RENTED"))
        else:
            out.append(
                upsert_freshness(
                    listing_id=lid,
                    last_verified_at=verified,
                    transaction=txn,
                    verification_source="test_fixture",
                )
            )
    return out


def freshness_summary() -> dict[str, int]:
    items = [_normalize(x) for x in _load_items()]
    counts: dict[str, int] = {s: 0 for s in PANTIP_FRESHNESS_STATES}
    for it in items:
        st = derive_freshness_state(it)
        counts[st] = counts.get(st, 0) + 1
    return counts


def build_api_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "test_only": True,
        "realxtate_alignment": {
            "ttl_days_rent": DEFAULT_TTL_DAYS["rent"],
            "ttl_days_sale": DEFAULT_TTL_DAYS["sale"],
            "public_availability_map": REALXTATE_TO_PANTIP_MAP,
            "verification_separate_from_bump": True,
            "freshness_separate_from_lease": True,
        },
        "states": sorted(PANTIP_FRESHNESS_STATES),
        "events": sorted(FRESHNESS_EVENTS),
        "summary": freshness_summary(),
        "items": [_normalize(x) for x in _load_items()],
        "display_labels_th": {
            "VERIFIED_AVAILABLE": "ยืนยันแล้วว่ายังว่างวันนี้",
            "VERIFICATION_DUE": "กำลังรอการยืนยันสถานะ",
            "VERIFICATION_OVERDUE": "เกินกำหนดยืนยัน",
            "STALE_UNCONFIRMED": "ยังไม่ยืนยันล่าสุด — ไม่แสดงว่าว่างแน่นอน",
        },
    }
