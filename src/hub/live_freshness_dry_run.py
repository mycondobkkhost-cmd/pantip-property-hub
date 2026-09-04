"""LIVE production freshness dry-run — Phase Z8 (READ ONLY)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from src.hub.legacy_entry_date import parse_legacy_record_entered_at, record_age_days
from src.hub.listing_freshness import DEFAULT_TTL_DAYS, derive_freshness_state

ARTIFACT_DIR = Path("/tmp/pantip-phase-z8-live")
LIVE_CACHE = ARTIFACT_DIR / "properties.json"
FRESHNESS_ARTIFACT = ARTIFACT_DIR / "live-freshness-dry-run.json"

FLY_APP = "property-hub"
FLY_MACHINE = "28623d2ae33748"
FLY_VOLUME = "vol_vz8qondpo5pkpmxv"
REMOTE_PATH = "/app/data/properties.json"

BOOTSTRAP_STRATEGIES = (
    "UNKNOWN_PENDING_BOOTSTRAP",
    "STAGED_VERIFICATION_BATCH",
    "GRACE_PERIOD",
    "NEW_RENEWED_ONLY",
    "HYBRID",
)

BOOTSTRAP_STATE = "BOOTSTRAP_VERIFICATION_PENDING"


def _listing_kind(prop: dict[str, Any]) -> str:
    rent = bool((prop.get("rent_price") or "").strip())
    sale = bool((prop.get("sale_price") or "").strip())
    if rent and sale:
        return "both"
    if rent:
        return "rent"
    if sale:
        return "sale"
    return "unknown"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acquire_live_properties_read_only(*, force_refresh: bool = False) -> dict[str, Any]:
    """Read-only acquisition from Fly /app/data via sftp get."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    meta_path = ARTIFACT_DIR / "acquisition-meta.json"
    if LIVE_CACHE.is_file() and not force_refresh:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        count = len(json.loads(LIVE_CACHE.read_text(encoding="utf-8")))
        meta["property_count"] = count
        meta["sha256"] = _sha256(LIVE_CACHE)
        return {"ok": True, "path": str(LIVE_CACHE), "method": meta.get("method", "cache"), **meta}

    try:
        subprocess.run(
            [
                "fly",
                "ssh",
                "sftp",
                "get",
                REMOTE_PATH,
                str(LIVE_CACHE),
                "-a",
                FLY_APP,
                "--machine",
                FLY_MACHINE,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        method = "fly_ssh_sftp_get"
    except Exception as exc:  # noqa: BLE001
        # Fallback: local git properties.json with explicit label (not live)
        local = Path(__file__).resolve().parent.parent.parent / "data" / "properties.json"
        if local.is_file():
            LIVE_CACHE.write_bytes(local.read_bytes())
            method = "local_fallback_not_live"
        else:
            return {"ok": False, "error": str(exc), "method": "failed"}

    count = len(json.loads(LIVE_CACHE.read_text(encoding="utf-8")))
    meta = {
        "ok": True,
        "path": str(LIVE_CACHE),
        "method": method,
        "property_count": count,
        "sha256": _sha256(LIVE_CACHE),
        "remote_path": REMOTE_PATH,
        "machine_id": FLY_MACHINE,
        "volume_id": FLY_VOLUME,
        "production_write": False,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _verification_evidence_class(prop: dict[str, Any], *, today: date) -> str:
    """Do NOT treat last_listed_at as last_verified_at."""
    if prop.get("last_verified_at") or prop.get("verification_due_at"):
        return "HAS_REAL_VERIFICATION_EVIDENCE"
    entered = parse_legacy_record_entered_at(prop.get("last_listed_at"))
    if entered:
        return "LEGACY_RECORD_ONLY"
    return "NO_VERIFICATION_HISTORY"


def build_live_freshness_dry_run(*, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    acq = acquire_live_properties_read_only()
    if not acq.get("ok"):
        return {"ok": False, "error": acq.get("error"), "test_only": True}

    props = json.loads(LIVE_CACHE.read_text(encoding="utf-8"))
    evidence_counts: Counter[str] = Counter()
    bootstrap_counts: Counter[str] = Counter()
    ttl_would_expire = 0
    falsely_stale_from_acquisition = 0
    rent_ttl = DEFAULT_TTL_DAYS["rent"]
    sale_ttl = DEFAULT_TTL_DAYS["sale"]

    for p in props:
        ev = _verification_evidence_class(p, today=today)
        evidence_counts[ev] += 1
        kind = _listing_kind(p)
        ttl = rent_ttl if kind in {"rent", "both", "unknown"} else sale_ttl

        if ev == "HAS_REAL_VERIFICATION_EVIDENCE":
            item = {
                "last_verified_at": p.get("last_verified_at", ""),
                "verification_due_at": p.get("verification_due_at", ""),
                "availability_state": p.get("availability_state", "VERIFIED_AVAILABLE"),
            }
            st = derive_freshness_state(item, today=today)
            bootstrap_counts[st] += 1
        elif ev == "LEGACY_RECORD_ONLY":
            # Bootstrap: do NOT auto-mark STALE from acquisition date
            bootstrap_counts[BOOTSTRAP_STATE] += 1
            entered = parse_legacy_record_entered_at(p.get("last_listed_at"))
            age = record_age_days(entered, today=today) or 0
            if age > ttl:
                falsely_stale_from_acquisition += 1
        else:
            bootstrap_counts["NO_VERIFICATION_HISTORY"] += 1

    strategies = {
        "UNKNOWN_PENDING_BOOTSTRAP": {
            "description_th": "ทรัพย์เก่าทั้งหมดอยู่สถานะรอ bootstrap จนกว่าจะยืนยัน",
            "initial_state": BOOTSTRAP_STATE,
            "legacy_auto_stale": False,
        },
        "STAGED_VERIFICATION_BATCH": {
            "description_th": "ยืนยันเป็นชุดๆ ตามความจุ operator",
            "initial_state": BOOTSTRAP_STATE,
            "legacy_auto_stale": False,
        },
        "GRACE_PERIOD": {
            "description_th": "ให้ grace 30–60 วันก่อนเริ่มบังคับ verification",
            "initial_state": BOOTSTRAP_STATE,
            "legacy_auto_stale": False,
        },
        "NEW_RENEWED_ONLY": {
            "description_th": "เฉพาะประกาศใหม่/ต่ออายุเข้าระบบ freshness",
            "initial_state": "NEW_LISTINGS_ONLY",
            "legacy_auto_stale": False,
        },
        "HYBRID": {
            "description_th": "legacy = BOOTSTRAP_VERIFICATION_PENDING + ชุดแรก staged batch",
            "initial_state": BOOTSTRAP_STATE,
            "legacy_auto_stale": False,
            "recommended": True,
        },
    }

    payload = {
        "ok": True,
        "test_only": True,
        "acquisition": acq,
        "live_population": len(props),
        "ttl_days": DEFAULT_TTL_DAYS,
        "evidence_classes": dict(evidence_counts),
        "has_real_verification_count": evidence_counts["HAS_REAL_VERIFICATION_EVIDENCE"],
        "legacy_record_only_count": evidence_counts["LEGACY_RECORD_ONLY"],
        "no_verification_history_count": evidence_counts["NO_VERIFICATION_HISTORY"],
        "would_falsely_stale_if_acquisition_used_as_verified": falsely_stale_from_acquisition,
        "bootstrap_state_counts": dict(bootstrap_counts),
        "bootstrap_strategies": strategies,
        "recommended_bootstrap": "HYBRID",
        "recommended_bootstrap_state": BOOTSTRAP_STATE,
        "new_state_needed": True,
        "new_state_rationale": "ต้องแยก LEGACY_RECORD_ONLY จาก STALE_UNCONFIRMED เพื่อไม่ซ่อนทั้ง catalog วันแรก",
        "public_ux_semantics_th": {
            "verified_recently": "เจ้าของยืนยันล่าสุดวันนี้",
            "verified_ago": "ยืนยันสถานะล่าสุด X วันที่แล้ว",
            "verification_due": "กำลังรอยืนยันสถานะล่าสุด",
            "legacy_unverified": "ข้อมูลเก่ายังไม่ได้ยืนยันสถานะใหม่ — ไม่แสดงว่ายังว่าง",
            "stale_unconfirmed": "ยังไม่ยืนยันล่าสุด — ไม่แสดงว่าว่างแน่นอน",
        },
        "stale_policy_options": compare_stale_public_policies(),
        "production_write": False,
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    FRESHNESS_ARTIFACT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["artifact_path"] = str(FRESHNESS_ARTIFACT)
    return payload


def compare_stale_public_policies() -> list[dict[str, Any]]:
    return [
        {
            "id": "visible_no_availability_claim",
            "label_th": "แสดงแต่ไม่ claim ว่าว่าง",
            "inventory_impact": "low",
            "trust": "high",
            "owner_friction": "medium",
            "operator_workload": "medium",
        },
        {
            "id": "lower_ranking",
            "label_th": "ลดอันดับในผลค้นหา",
            "inventory_impact": "low",
            "trust": "high",
            "owner_friction": "low",
            "operator_workload": "medium",
        },
        {
            "id": "hidden_default_search",
            "label_th": "ซ่อนจากผลค้นหาหลัก",
            "inventory_impact": "high",
            "trust": "medium",
            "owner_friction": "high",
            "operator_workload": "low",
        },
        {
            "id": "archived_until_reconfirmed",
            "label_th": "เก็บเข้าคลังจนกว่าจะยืนยันใหม่",
            "inventory_impact": "very_high",
            "trust": "medium",
            "owner_friction": "very_high",
            "operator_workload": "low",
        },
    ]


def recommend_stale_public_policy() -> dict[str, Any]:
    return {
        "recommended": "visible_no_availability_claim",
        "rationale_th": "รักษา inventory และความน่าเชื่อถือ — ไม่ claim ว่าว่างจากอายุข้อมูลเก่า",
        "implementation": "NOT_IN_Z8",
        "test_only": True,
    }


def get_production_state_read_only() -> dict[str, Any]:
    try:
        status = subprocess.run(
            ["fly", "status", "-a", FLY_APP, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        machines = subprocess.run(
            ["fly", "machines", "list", "-a", FLY_APP, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        machine_list = json.loads(machines.stdout) if machines.returncode == 0 else []
        return {
            "app": FLY_APP,
            "machine_count": len(machine_list),
            "machines": [{"id": m.get("id"), "state": m.get("state")} for m in machine_list],
            "volume_id": FLY_VOLUME,
            "health": "ok" if len(machine_list) == 1 else "unexpected_machine_count",
            "production_write": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {"app": FLY_APP, "error": str(exc), "production_write": False}
