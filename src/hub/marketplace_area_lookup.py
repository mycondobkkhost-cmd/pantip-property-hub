"""Deterministic marketplace area name lookup for owner review display.

READ-ONLY presentation enrichment. Does not mutate Phase W crosswalk or production data.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOOKUP_PATH = BASE_DIR / "data_fixtures" / "master_review" / "marketplace_area_names.json"

UNNAMED_AREA_LABEL_TH = "ทำเลที่ยังไม่มีชื่อแสดงผล"
APPROVE_BLOCKED_REASON_TH = "ยังไม่ควรอนุมัติ — ข้อมูลชื่อทำเลไม่ครบ"

AREA_ROLE_LABELS_TH: dict[str, str] = {
    "PRIMARY": "ทำเลหลัก",
    "SECONDARY": "ทำเลรองที่เกี่ยวข้อง",
    "EDGE": "ทำเลบริเวณรอยต่อ",
}

AREA_ROLE_TOOLTIPS_TH: dict[str, str] = {
    "PRIMARY": "ทำเลที่โครงการสัมพันธ์มากที่สุด",
    "SECONDARY": "ทำเลใกล้เคียงที่ยังเกี่ยวข้องกับการค้นหา",
    "EDGE": "โครงการอยู่ใกล้ขอบระหว่างทำเล",
}

CONFIDENCE_LABELS_TH: dict[str, str] = {
    "HIGH": "ความมั่นใจสูง",
    "MEDIUM": "ความมั่นใจปานกลาง",
    "LOW": "ความมั่นใจต่ำ",
}


def lookup_path() -> Path:
    raw = (os.environ.get("MASTER_REVIEW_AREA_LOOKUP_PATH") or "").strip()
    return Path(raw) if raw else DEFAULT_LOOKUP_PATH


@lru_cache(maxsize=1)
def load_area_lookup() -> dict[str, dict[str, str]]:
    path = lookup_path()
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    areas = payload.get("areas") or {}
    if not isinstance(areas, dict):
        return {}
    return areas


def clear_lookup_cache() -> None:
    load_area_lookup.cache_clear()


def role_label_th(role: str | None) -> str:
    return AREA_ROLE_LABELS_TH.get(str(role or "").upper(), str(role or ""))


def role_tooltip_th(role: str | None) -> str:
    return AREA_ROLE_TOOLTIPS_TH.get(str(role or "").upper(), "")


def confidence_label_th(confidence: str | None) -> str:
    return CONFIDENCE_LABELS_TH.get(str(confidence or "").upper(), str(confidence or ""))


def has_trusted_name(relation: dict[str, Any]) -> bool:
    if relation.get("has_trusted_name") is True:
        return True
    th = str(relation.get("area_name_th") or relation.get("area_name") or "").strip()
    return bool(th and th != UNNAMED_AREA_LABEL_TH)


def display_name_th(relation: dict[str, Any]) -> str:
    if has_trusted_name(relation):
        return str(relation.get("area_name_th") or relation.get("area_name") or "").strip()
    return UNNAMED_AREA_LABEL_TH


def enrich_area_relation(relation: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with presentation metadata; preserve canonical area_id/role."""
    out = dict(relation)
    area_id = str(out.get("area_id") or "").strip()
    role = str(out.get("role") or "PRIMARY").upper()
    confidence = str(out.get("confidence") or "LOW").upper()

    entry = load_area_lookup().get(area_id) or {}
    name_th = str(entry.get("area_name_th") or out.get("area_name_th") or out.get("area_name") or "").strip()
    name_en = str(entry.get("area_name_en") or out.get("area_name_en") or "").strip()

    trusted = bool(name_th)
    out["area_id"] = area_id or out.get("area_id")
    out["role"] = role
    out["confidence"] = confidence
    out["area_name_th"] = name_th if trusted else ""
    out["area_name_en"] = name_en if trusted else ""
    out["area_name"] = name_th if trusted else ""
    out["has_trusted_name"] = trusted
    out["display_name_th"] = display_name_th(out)
    out["role_label_th"] = role_label_th(role)
    out["role_tooltip_th"] = role_tooltip_th(role)
    out["confidence_label_th"] = confidence_label_th(confidence)
    if entry.get("identity_key"):
        out["identity_key"] = entry["identity_key"]
    if entry.get("source"):
        out["name_source"] = entry["source"]
    return out


def enrich_area_relations(relations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [enrich_area_relation(rel) for rel in relations or []]


def all_decision_areas_named(relations: list[dict[str, Any]] | None) -> bool:
    rels = relations or []
    if not rels:
        return False
    return all(has_trusted_name(rel) for rel in rels)


def build_approval_gate(item: dict[str, Any]) -> dict[str, Any]:
    review_type = item.get("review_type") or ""
    proposed = item.get("proposed_value") or {}
    relations = proposed.get("marketplace_area_relations") or []

    if review_type == "PANTIP_ONLY_REVIEW":
        return {
            "can_approve": False,
            "blocked_reason_th": "โครงการ Pantip-only — ยังไม่มีข้อเสนอจาก Master อ้างอิง",
            "unnamed_area_count": 0,
        }

    if review_type != "AREA_REVIEW":
        return {"can_approve": True, "blocked_reason_th": "", "unnamed_area_count": 0}

    unnamed = [rel for rel in relations if not has_trusted_name(rel)]
    if unnamed:
        return {
            "can_approve": False,
            "blocked_reason_th": APPROVE_BLOCKED_REASON_TH,
            "unnamed_area_count": len(unnamed),
        }

    semantic = str(proposed.get("semantic_kind") or "")
    if semantic not in {"MARKETPLACE_AREA"}:
        return {
            "can_approve": False,
            "blocked_reason_th": "ยังไม่ควรอนุมัติ — ประเภทข้อเสนอไม่ชัดเจน",
            "unnamed_area_count": 0,
        }

    return {"can_approve": True, "blocked_reason_th": "", "unnamed_area_count": 0}
