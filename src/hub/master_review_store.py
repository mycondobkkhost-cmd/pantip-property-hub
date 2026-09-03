#!/usr/bin/env python3
"""Owner canonical master review — decision recording only (Phase X).

REVIEW != APPLY. This module never mutates projects.json or properties.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_REVIEW_DATA_DIR = BASE_DIR / ".local" / "master_review"
FIXTURE_CROSSWALK = BASE_DIR / "data_fixtures" / "master_review" / "sample_crosswalk.json"

REVIEW_VERSION = "0.1"
CROSSWALK_VERSION = "phase-w-20260904T035800Z"

STATUSES = frozenset({"PENDING", "APPROVED", "REJECTED", "DEFERRED"})
FORBIDDEN_STATUSES = frozenset({"APPLIED"})

APPROVE_REASONS = frozenset(
    {
        "REFERENCE_EVIDENCE_ACCEPTED",
        "OWNER_KNOWLEDGE",
        "MULTIPLE_SOURCES_AGREE",
        "MARKETPLACE_CLASSIFICATION_ACCEPTED",
    }
)
REJECT_REASONS = frozenset(
    {
        "REFERENCE_INCORRECT",
        "PROJECT_DIFFERENT",
        "SEMANTIC_MISMATCH",
        "OWNER_KNOWLEDGE",
        "INSUFFICIENT_EVIDENCE",
    }
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"APPROVED", "REJECTED", "DEFERRED"}),
    "DEFERRED": frozenset({"APPROVED", "REJECTED", "PENDING"}),
    "APPROVED": frozenset({"DEFERRED", "REJECTED"}),
    "REJECTED": frozenset({"DEFERRED", "APPROVED"}),
}

PRIORITY_THAI = {
    "P0": "ควรตรวจสอบก่อน",
    "P1": "สำคัญ",
    "P2": "ตรวจสอบตามลำดับ",
    "P3": "ต้องใช้ข้อมูลเพิ่ม",
}

CONFIDENCE_THAI = {
    "HIGH": "สูง",
    "MEDIUM": "กลาง",
    "LOW": "ต่ำ",
    "REALXTATE_HIGH": "สูง",
    "REALXTATE_MEDIUM": "กลาง",
    "REALXTATE_LOW": "ต่ำ",
}


class MasterReviewError(Exception):
    def __init__(self, message: str, *, code: str = "review_error", http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


def review_data_dir() -> Path:
    raw = (os.environ.get("MASTER_REVIEW_DATA_DIR") or "").strip()
    return Path(raw) if raw else DEFAULT_REVIEW_DATA_DIR


def source_crosswalk_path() -> Path:
    raw = (os.environ.get("MASTER_REVIEW_SOURCE_PATH") or "").strip()
    if raw:
        return Path(raw)
    backup = (
        Path.home()
        / "Backups"
        / "pantip-property-automation"
        / "phase-w-crosswalk-20260904T035800Z"
        / "live-project-crosswalk.json"
    )
    if backup.is_file():
        return backup
    return FIXTURE_CROSSWALK


def decisions_log_path() -> Path:
    return review_data_dir() / "master_review_decisions.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_fingerprint(row: dict[str, Any]) -> str:
    payload = {
        "project_id": row.get("pantip_project_id"),
        "bucket_key": row.get("pantip_bucket_key"),
        "canonical_name": row.get("pantip_canonical_name"),
        "zone_verified": row.get("pantip_zone_verified") or [],
        "transit_verified": row.get("pantip_transit_verified") or [],
        "listing_count": row.get("live_listing_count"),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _priority_score(row: dict[str, Any]) -> int:
    score = 0
    if row.get("zone_agreement_class") == "DIRECT_CONFLICT":
        score += 100
    conf = row.get("realxtate_area_confidence", "")
    if conf == "REALXTATE_HIGH":
        score += 50
    elif conf == "REALXTATE_MEDIUM":
        score += 30
    score += min(int(row.get("live_listing_count") or 0), 50)
    if row.get("legacy_promotion_suspected"):
        score += 20
    if row.get("match_class") == "CONFLICT":
        score += 40
    return score


def _priority_band(score: int) -> str:
    if score >= 120:
        return "P0"
    if score >= 80:
        return "P1"
    if score >= 50:
        return "P2"
    return "P3"


def _format_rx_areas(areas: list[dict[str, Any]]) -> str:
    if not areas:
        return "—"
    parts = []
    for area in areas[:3]:
        aid = str(area.get("area_id") or "")
        short = re.sub(r"^rxa_", "", aid)[:12] or aid
        role = area.get("role") or ""
        conf = area.get("confidence") or ""
        parts.append(f"{short} ({role}/{conf})")
    return ", ".join(parts)


def _confidence_tier(row: dict[str, Any]) -> str:
    conf = row.get("realxtate_area_confidence") or ""
    if conf == "REALXTATE_HIGH":
        return "HIGH"
    if conf == "REALXTATE_MEDIUM":
        return "MEDIUM"
    if conf == "REALXTATE_LOW":
        return "LOW"
    return "LOW"


def _legacy_state_thai(row: dict[str, Any]) -> str:
    if row.get("legacy_promotion_suspected"):
        return "ข้อมูลเดิมมาจากชีตและยังไม่มีหลักฐานยืนยันอิสระ"
    return "มีการแยกข้อมูล verified/unverified แล้ว"


def _semantic_note(row: dict[str, Any]) -> str:
    zc = row.get("zone_agreement_class") or ""
    if zc == "SEMANTICALLY_DIFFERENT_BUT_NOT_CONFLICT":
        return "ข้อมูลคนละประเภท แต่สามารถอยู่ร่วมกันได้ (เช่น เขตปกครอง vs ทำเลตลาด)"
    if zc == "DIRECT_CONFLICT":
        return "ข้อมูลประเภทเดียวกันแต่ขัดแย้งกัน — ควรตรวจสอบ"
    if zc == "PARTIAL_AGREE":
        return "ข้อมูลบางส่วนตรงกัน แต่ยังไม่ครบ"
    return ""


def _build_evidence(row: dict[str, Any], review_type: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    if row.get("match_class") == "EXACT_ID_MATCH":
        evidence.append(
            {
                "evidence_id": "stable_project_id",
                "evidence_type": "identity",
                "source": "crosswalk",
                "value": row.get("pantip_project_id"),
                "confidence": "HIGH",
                "explanation": "โครงการตรงกันด้วย Project ID",
            }
        )
    if review_type == "AREA_REVIEW":
        for area in row.get("realxtate_marketplace_areas") or []:
            evidence.append(
                {
                    "evidence_id": str(area.get("area_id") or uuid.uuid4()),
                    "evidence_type": "marketplace_area",
                    "source": "realxtate_reference",
                    "value": area,
                    "confidence": area.get("confidence") or "LOW",
                    "explanation": "RealXtate จัดทำเล Marketplace จากหลักฐานอิสระ",
                }
            )
    if row.get("legacy_promotion_suspected"):
        evidence.append(
            {
                "evidence_id": "legacy_promotion",
                "evidence_type": "quality_flag",
                "source": "phase_w_audit",
                "value": "verified_equals_unverified",
                "confidence": "MEDIUM",
                "explanation": "ข้อมูล Pantip ปัจจุบันน่าจะคัดลอกจากชีตพนักงาน",
            }
        )
    return evidence


def build_review_item(row: dict[str, Any], *, source_hash: str, review_type: str) -> dict[str, Any]:
    project_id = row.get("pantip_project_id") or ""
    score = _priority_score(row)
    priority = _priority_band(score)
    zones = row.get("pantip_zone_verified") or []
    current_value = {
        "semantic_kind": "MARKETPLACE_AREA" if review_type == "AREA_REVIEW" else "PROJECT_IDENTITY",
        "value": "; ".join(zones[:5]) if review_type == "AREA_REVIEW" else row.get("pantip_canonical_name"),
        "source": "pantip_live_snapshot",
        "verification_state": "LEGACY_PROMOTION_SUSPECTED" if row.get("legacy_promotion_suspected") else "VERIFIED_SPLIT",
    }
    proposed_value = {
        "semantic_kind": "MARKETPLACE_AREA",
        "value": _format_rx_areas(row.get("realxtate_marketplace_areas") or []),
        "source": "realxtate_reference",
        "confidence": _confidence_tier(row),
    }
    if review_type == "PANTIP_ONLY_REVIEW":
        current_value = {
            "semantic_kind": "PROJECT_IDENTITY",
            "value": row.get("pantip_canonical_name"),
            "source": "pantip_live_snapshot",
            "verification_state": "PANTIP_ONLY",
        }
        proposed_value = {
            "semantic_kind": "UNKNOWN",
            "value": "ยังไม่มีใน Master อ้างอิง",
            "source": "none",
            "confidence": "LOW",
        }

    item_id = f"{review_type.lower()}:{project_id}"
    return {
        "review_item_id": item_id,
        "review_version": REVIEW_VERSION,
        "review_type": review_type,
        "project_id": project_id,
        "canonical_project_id": project_id,
        "project_name": row.get("pantip_canonical_name") or "",
        "live_snapshot_listing_count": int(row.get("live_listing_count") or 0),
        "current_value": current_value,
        "proposed_value": proposed_value,
        "evidence": _build_evidence(row, review_type),
        "disagreement_class": row.get("zone_agreement_class") or row.get("match_class") or "",
        "legacy_promotion_suspected": bool(row.get("legacy_promotion_suspected")),
        "priority": priority,
        "priority_score": score,
        "priority_label_th": PRIORITY_THAI.get(priority, priority),
        "semantic_note_th": _semantic_note(row),
        "legacy_state_th": _legacy_state_thai(row),
        "source_snapshot": {
            "generated_at": CROSSWALK_VERSION,
            "crosswalk_version": CROSSWALK_VERSION,
            "source_hash": source_hash,
        },
        "source_project_fingerprint": project_fingerprint(row),
        "decision": {
            "status": "PENDING",
            "decided_by": None,
            "decided_at": None,
            "reason": None,
            "note": None,
        },
    }


def load_crosswalk_rows(path: Path | None = None) -> tuple[list[dict[str, Any]], str]:
    src = path or source_crosswalk_path()
    if not src.is_file():
        raise MasterReviewError(f"Review source not found: {src}", code="source_missing", http_status=404)
    rows = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise MasterReviewError("Crosswalk source must be a JSON array", code="invalid_source")
    return rows, file_sha256(src)


def build_review_queue(
    rows: list[dict[str, Any]] | None = None,
    *,
    source_hash: str | None = None,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    if rows is None:
        rows, source_hash = load_crosswalk_rows(path)
    source_hash = source_hash or ""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    area_rows = [
        r
        for r in rows
        if r.get("zone_agreement_class") == "DIRECT_CONFLICT"
        and r.get("realxtate_area_confidence") in ("REALXTATE_HIGH", "REALXTATE_MEDIUM")
        and r.get("correction_class") == "REVIEW_RECOMMENDED"
    ]
    area_rows.sort(key=_priority_score, reverse=True)
    for row in area_rows:
        item = build_review_item(row, source_hash=source_hash, review_type="AREA_REVIEW")
        if item["review_item_id"] in seen:
            raise MasterReviewError("Duplicate review_item_id", code="duplicate_item")
        seen.add(item["review_item_id"])
        items.append(item)

    pantip_only = [r for r in rows if r.get("match_class") == "PANTIP_ONLY"]
    pantip_only.sort(key=lambda r: -(int(r.get("live_listing_count") or 0)))
    for row in pantip_only:
        item = build_review_item(row, source_hash=source_hash, review_type="PANTIP_ONLY_REVIEW")
        if item["review_item_id"] in seen:
            raise MasterReviewError("Duplicate review_item_id", code="duplicate_item")
        seen.add(item["review_item_id"])
        items.append(item)

    return items


def load_decision_events() -> list[dict[str, Any]]:
    path = decisions_log_path()
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def current_decision_map() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for event in load_decision_events():
        rid = str(event.get("review_item_id") or "")
        if rid:
            out[rid] = event
    return out


def apply_decisions_to_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest = current_decision_map()
    enriched: list[dict[str, Any]] = []
    for item in items:
        copy = json.loads(json.dumps(item, ensure_ascii=False))
        event = latest.get(copy["review_item_id"])
        if event:
            copy["decision"] = {
                "status": event.get("new_status"),
                "decided_by": event.get("actor"),
                "decided_at": event.get("timestamp"),
                "reason": event.get("reason"),
                "note": event.get("note"),
            }
        enriched.append(copy)
    return enriched


def validate_transition(previous: str | None, new_status: str) -> None:
    if new_status in FORBIDDEN_STATUSES:
        raise MasterReviewError("APPLIED status is not allowed in Phase X", code="forbidden_status")
    if new_status not in STATUSES:
        raise MasterReviewError(f"Invalid status: {new_status}", code="invalid_status")
    prev = previous or "PENDING"
    if new_status == prev:
        raise MasterReviewError("Status unchanged", code="unchanged_status")
    allowed = ALLOWED_TRANSITIONS.get(prev, frozenset())
    if new_status not in allowed:
        raise MasterReviewError(
            f"Transition {prev} → {new_status} not allowed",
            code="invalid_transition",
        )


def record_decision(
    *,
    review_item_id: str,
    project_id: str,
    new_status: str,
    actor: str,
    expected_source_snapshot_hash: str,
    reason: str | None = None,
    note: str | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if new_status == "APPROVED" and not reason:
        raise MasterReviewError("APPROVED requires reason code", code="reason_required")
    if new_status == "REJECTED" and not reason:
        raise MasterReviewError("REJECTED requires reason code", code="reason_required")
    if new_status == "APPROVED" and reason not in APPROVE_REASONS:
        raise MasterReviewError(f"Invalid approve reason: {reason}", code="invalid_reason")
    if new_status == "REJECTED" and reason not in REJECT_REASONS:
        raise MasterReviewError(f"Invalid reject reason: {reason}", code="invalid_reason")

    if items is None:
        items = build_review_queue()
    item = next((i for i in items if i["review_item_id"] == review_item_id), None)
    if not item:
        raise MasterReviewError("Unknown review item", code="unknown_item", http_status=404)
    if item.get("project_id") != project_id:
        raise MasterReviewError("project_id mismatch", code="project_mismatch", http_status=400)
    if item.get("source_snapshot", {}).get("source_hash") != expected_source_snapshot_hash:
        raise MasterReviewError(
            "Stale source snapshot hash — review source changed",
            code="stale_snapshot",
            http_status=409,
        )

    latest = current_decision_map().get(review_item_id)
    previous = (latest or {}).get("new_status") or "PENDING"
    validate_transition(previous, new_status)

    event = {
        "decision_event_id": str(uuid.uuid4()),
        "review_item_id": review_item_id,
        "project_id": project_id,
        "previous_status": previous,
        "new_status": new_status,
        "actor": actor,
        "timestamp": _now_iso(),
        "reason": reason,
        "note": note,
        "source_snapshot_hash": expected_source_snapshot_hash,
        "source_project_fingerprint": item.get("source_project_fingerprint"),
    }
    path = decisions_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def filter_items(
    items: list[dict[str, Any]],
    *,
    status: str | None = None,
    priority: str | None = None,
    confidence: str | None = None,
    review_type: str | None = None,
    issue_type: str | None = None,
    search: str | None = None,
    top50_only: bool = False,
) -> list[dict[str, Any]]:
    area_items = [i for i in items if i.get("review_type") == "AREA_REVIEW"]
    if top50_only:
        area_items = sorted(area_items, key=lambda i: i.get("priority_score", 0), reverse=True)[:50]
        allowed_ids = {i["review_item_id"] for i in area_items}
        items = [i for i in items if i["review_item_id"] in allowed_ids or i.get("review_type") == "PANTIP_ONLY_REVIEW"]
    out = items
    if review_type:
        out = [i for i in out if i.get("review_type") == review_type]
    if status:
        out = [i for i in out if (i.get("decision") or {}).get("status") == status]
    if priority:
        out = [i for i in out if i.get("priority") == priority]
    if confidence:
        out = [i for i in out if (i.get("proposed_value") or {}).get("confidence") == confidence]
    if issue_type == "area_conflict":
        out = [i for i in out if i.get("disagreement_class") == "DIRECT_CONFLICT"]
    elif issue_type == "legacy_suspect":
        out = [i for i in out if i.get("legacy_promotion_suspected")]
    elif issue_type == "pantip_only":
        out = [i for i in out if i.get("review_type") == "PANTIP_ONLY_REVIEW"]
    if search:
        q = search.lower().strip()
        out = [
            i
            for i in out
            if q in (i.get("project_name") or "").lower() or q in (i.get("project_id") or "").lower()
        ]
    return out


def summary_counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: dict[str, int] = {"PENDING": 0, "APPROVED": 0, "REJECTED": 0, "DEFERRED": 0}
    listings_by_status: dict[str, int] = {k: 0 for k in by_status}
    for item in items:
        st = (item.get("decision") or {}).get("status") or "PENDING"
        by_status[st] = by_status.get(st, 0) + 1
        listings_by_status[st] = listings_by_status.get(st, 0) + int(item.get("live_snapshot_listing_count") or 0)
    return {
        "total_items": len(items),
        "area_review_count": sum(1 for i in items if i.get("review_type") == "AREA_REVIEW"),
        "pantip_only_count": sum(1 for i in items if i.get("review_type") == "PANTIP_ONLY_REVIEW"),
        "by_status": by_status,
        "listings_by_status": listings_by_status,
        "message_th": "ยังไม่มีการแก้ข้อมูล Production",
    }


def export_promotion_candidate(items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if items is None:
        items = apply_decisions_to_items(build_review_queue())
    approved = [i for i in items if (i.get("decision") or {}).get("status") == "APPROVED"]
    decisions = []
    for item in approved:
        dec = item.get("decision") or {}
        decisions.append(
            {
                "review_item_id": item.get("review_item_id"),
                "project_id": item.get("project_id"),
                "review_type": item.get("review_type"),
                "approved_value": item.get("proposed_value"),
                "semantic_kind": (item.get("proposed_value") or {}).get("semantic_kind"),
                "evidence": item.get("evidence"),
                "approved_by": dec.get("decided_by"),
                "approved_at": dec.get("decided_at"),
                "source_project_fingerprint": item.get("source_project_fingerprint"),
                "source_snapshot_hash": (item.get("source_snapshot") or {}).get("source_hash"),
            }
        )
    source_hash = ""
    if items:
        source_hash = (items[0].get("source_snapshot") or {}).get("source_hash") or ""
    return {
        "promotion_version": "0.1",
        "artifact_type": "canonical-promotion-candidate",
        "generated_at": _now_iso(),
        "source_crosswalk_version": CROSSWALK_VERSION,
        "source_snapshot_hash": source_hash,
        "decision_count": len(decisions),
        "decisions": decisions,
        "notice_th": "ไฟล์นี้เป็นข้อเสนอสำหรับขั้นตอนแก้ไขในอนาคต — ยังไม่ใช่คำสั่งแก้ Production",
    }


def batch_record_decision(
    *,
    review_item_ids: list[str],
    new_status: str,
    actor: str,
    expected_source_snapshot_hash: str,
    reason: str | None = None,
    note: str | None = None,
) -> list[dict[str, Any]]:
    if new_status == "APPROVED":
        raise MasterReviewError(
            "BATCH_APPROVE disabled in Phase X v0.1",
            code="batch_approve_disabled",
        )
    items = apply_decisions_to_items(build_review_queue())
    selected = [i for i in items if i["review_item_id"] in review_item_ids]
    if len(selected) != len(set(review_item_ids)):
        raise MasterReviewError("Unknown review item in batch", code="unknown_item")
    if len({i.get("review_type") for i in selected}) > 1:
        raise MasterReviewError("Batch items must share review_type", code="batch_incompatible")
    if len({(i.get("proposed_value") or {}).get("confidence") for i in selected}) > 1:
        raise MasterReviewError("Batch items must share confidence tier", code="batch_incompatible")
    if any(i.get("review_type") == "PANTIP_ONLY_REVIEW" for i in selected):
        raise MasterReviewError("Cannot batch Pantip-only identity reviews", code="batch_forbidden")
    events = []
    for item in selected:
        events.append(
            record_decision(
                review_item_id=item["review_item_id"],
                project_id=item["project_id"],
                new_status=new_status,
                actor=actor,
                expected_source_snapshot_hash=expected_source_snapshot_hash,
                reason=reason,
                note=note,
                items=items,
            )
        )
    return events
