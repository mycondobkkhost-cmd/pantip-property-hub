#!/usr/bin/env python3
"""Seed / cleanup SAFE Z14.4 synthetic fixtures on staging volume."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BASE = Path("/app/data")
PROPS = BASE / "properties.json"
STATE = BASE / "upcoming_followup_state.json"
PREFIX = "z144-"


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def cleanup() -> None:
    props = [p for p in load_json(PROPS, []) if not str(p.get("id", "")).startswith(PREFIX)]
    PROPS.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
    st = load_json(STATE, {"items": {}})
    items = st.setdefault("items", {})
    for k in list(items.keys()):
        if str(k).startswith(PREFIX):
            del items[k]
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    print("CLEANUP_OK", hashlib.sha256(PROPS.read_bytes()).hexdigest()[:16])


def seed() -> None:
    cleanup()
    props = load_json(PROPS, [])
    fixtures = [
        {
            "id": "z144-annual-up",
            "code": "Z144A",
            "project_name": "Z14.4 Annual Up",
            "rent_price": "15000",
            "sale_price": "",
            "last_posted_at": "2025-09-20",
            "notes": "หมายเหตุ annual upcoming",
            "source_url": "https://example.com/a",
            "post_pages_url": "https://example.com/pa",
            "sample_image_url": "https://picsum.photos/seed/z144a/200/200",
        },
        {
            "id": "z144-annual-ov",
            "code": "Z144B",
            "project_name": "Z14.4 Annual Overdue",
            "rent_price": "16000",
            "last_posted_at": "2025-08-25",
            "notes": "",
            "source_url": "https://example.com/b",
            "post_pages_url": "https://example.com/pb",
        },
        {
            "id": "z144-conf-up",
            "code": "Z144C",
            "project_name": "Z14.4 Confirmed Up",
            "rent_price": "17000",
            "last_posted_at": "2024-01-01",
            "owner_confirmed_available_from": "2026-09-20",
            "notes": "confirmed note",
            "source_url": "https://example.com/c",
            "post_pages_url": "https://example.com/pc",
        },
        {
            "id": "z144-conf-ov",
            "code": "Z144D",
            "project_name": "Z14.4 Confirmed Overdue",
            "rent_price": "18000",
            "owner_confirmed_available_from": "2026-08-28",
            "notes": "",
            "source_url": "https://example.com/d",
            "post_pages_url": "https://example.com/pd",
        },
        {
            "id": "z144-both",
            "code": "Z144E",
            "project_name": "Z14.4 Annual+Confirmed",
            "rent_price": "19000",
            "last_posted_at": "2025-09-20",
            "owner_confirmed_available_from": "2026-09-25",
            "notes": "both reasons",
            "source_url": "https://example.com/e",
            "post_pages_url": "https://example.com/pe",
        },
        {
            "id": "z144-ann-recheck",
            "code": "Z144F",
            "project_name": "Z14.4 Annual+Recheck",
            "rent_price": "20000",
            "last_posted_at": "2025-09-20",
            "notes": "",
            "source_url": "https://example.com/f",
            "post_pages_url": "https://example.com/pf",
        },
        {
            "id": "z144-conf-recheck",
            "code": "Z144G",
            "project_name": "Z14.4 Confirmed+Recheck",
            "rent_price": "21000",
            "owner_confirmed_available_from": "2026-09-20",
            "notes": "vacancy + recheck",
            "source_url": "https://example.com/g",
            "post_pages_url": "https://example.com/pg",
        },
        {
            "id": "z144-sale",
            "code": "Z144H",
            "project_name": "Z14.4 Sale Only",
            "rent_price": "",
            "sale_price": "5500000",
            "last_posted_at": "2025-09-20",
            "notes": "sale only exclude",
            "source_url": "https://example.com/h",
            "post_pages_url": "https://example.com/ph",
        },
        {
            "id": "z144-rent-sale",
            "code": "Z144I",
            "project_name": "Z14.4 Rent+Sale",
            "rent_price": "22000",
            "sale_price": "6000000",
            "last_posted_at": "2025-09-18",
            "notes": "",
            "source_url": "https://example.com/i",
            "post_pages_url": "https://example.com/pi",
        },
        {
            "id": "z144-suppressed",
            "code": "Z144J",
            "project_name": "Z14.4 Suppressed",
            "rent_price": "12000",
            "last_posted_at": "2025-09-20",
            "notes": "should not appear",
            "source_url": "https://example.com/j",
            "post_pages_url": "https://example.com/pj",
        },
    ]
    props.extend(fixtures)
    PROPS.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
    st = load_json(STATE, {"items": {}})
    items = st.setdefault("items", {})
    items["z144-ann-recheck"] = {"suppressed": False, "recheck_after": "2026-09-25"}
    items["z144-conf-recheck"] = {"suppressed": False, "recheck_after": "2026-09-15"}
    items["z144-suppressed"] = {"suppressed": True, "reason": "ทดสอบ", "recheck_after": ""}
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FIXTURES_OK", len(fixtures), hashlib.sha256(PROPS.read_bytes()).hexdigest()[:16])


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "seed").strip()
    if cmd == "cleanup":
        cleanup()
    else:
        seed()
