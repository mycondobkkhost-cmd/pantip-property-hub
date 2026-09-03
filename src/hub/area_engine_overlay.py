"""Area Engine analysis overlay for Owner Review — Phase Z1.

READ-ONLY reference overlay. Does not mutate production or record owner decisions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.hub.admin_geography import resolve_admin_geography
from src.hub.area_assignment_engine import (
    CLASS_AUTO_SAFE,
    CLASS_REJECT_QUARANTINE,
    CLASS_REVIEW,
    OUTCOME_AUTO_QUARANTINED,
    OUTCOME_AUTO_SAFE,
    OUTCOME_NOT_EVALUABLE,
    OUTCOME_OWNER_REVIEW_REQUIRED,
    SUPPORT_IMPLAUSIBLE,
    evaluate_project,
    load_area_seeds,
    load_project_contexts,
    load_stations,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
DEFAULT_TRUSTED = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-trusted-master.sqlite"
)
DEFAULT_CATALOG = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-catalog.sqlite"
)

OUTCOME_LABEL_TH = {
    OUTCOME_AUTO_SAFE: "ระบบพบหลักฐานทางภูมิศาสตร์ชัดเจน — แนะนำ AUTO_SAFE",
    OUTCOME_OWNER_REVIEW_REQUIRED: "ควรให้เจ้าของตรวจสอบเพิ่มเติม",
    OUTCOME_AUTO_QUARANTINED: "พบความขัดแย้งชัดเจน — ตัดออกจากข้อเสนอในอนาคตได้โดยไม่ต้องตรวจซ้ำ",
    OUTCOME_NOT_EVALUABLE: "ยังประเมินไม่ได้ — ไม่มีพิกัดที่ใช้งานได้",
}

CLASSIFICATION_LABEL_TH = {
    CLASS_AUTO_SAFE: "หลักฐานภูมิศาสตร์ชัดเจน",
    CLASS_REVIEW: "ควรตรวจสอบเพิ่มเติม",
    CLASS_REJECT_QUARANTINE: "ไม่น่าเชื่อถือ / อยู่ไกลเกินไป",
}


def _outcome_from_classification(classification: str, project_outcome: str) -> str:
    return project_outcome or {
        CLASS_AUTO_SAFE: OUTCOME_AUTO_SAFE,
        CLASS_REVIEW: OUTCOME_OWNER_REVIEW_REQUIRED,
        CLASS_REJECT_QUARANTINE: OUTCOME_AUTO_QUARANTINED,
    }.get(classification, OUTCOME_OWNER_REVIEW_REQUIRED)


def _format_area_line(area: dict[str, Any]) -> dict[str, Any]:
    name = area.get("name_th") or area.get("identity_key") or "—"
    cls = area.get("classification") or ""
    meters = area.get("straight_line_meters")
    lines: list[str] = []
    if cls == CLASS_AUTO_SAFE:
        lines.append("ระบบพบหลักฐานทางภูมิศาสตร์ชัดเจน")
        lines.append(f"แนะนำ: {OUTCOME_LABEL_TH[OUTCOME_AUTO_SAFE]}")
    elif cls == CLASS_REJECT_QUARANTINE:
        if meters is not None:
            lines.append(f"อยู่ห่างประมาณ {int(meters / 1000)} กม.")
        if area.get("contradictions"):
            if any("legacy" in c or "lineage" in c for c in area["contradictions"]):
                lines.append("พบเฉพาะข้อมูลเก่าที่มาจากแหล่งเดียวกัน")
        lines.append("แนะนำ: ตัดออกจากข้อเสนอในอนาคต")
    elif cls == CLASS_REVIEW:
        if meters is not None:
            lines.append(f"ระยะทางเส้นตรงประมาณ {int(meters)} เมตร — อยู่ในช่วงต้องพิจารณา")
        lines.append("แนะนำ: ให้เจ้าของตรวจสอบ")
    else:
        lines.append(CLASSIFICATION_LABEL_TH.get(cls, cls))
    for ex in area.get("explanation_th") or []:
        if ex not in lines:
            lines.append(ex)
    return {
        "area_id": area.get("area_id"),
        "name_th": name,
        "classification": cls,
        "classification_label_th": CLASSIFICATION_LABEL_TH.get(cls, cls),
        "straight_line_meters": meters,
        "explanation_th": lines,
        "evidence": area.get("evidence") or [],
        "contradictions": area.get("contradictions") or [],
    }


def build_area_engine_overlay(
    project_id: str,
    *,
    crosswalk_path: Path | None = None,
    trusted_db: Path | None = None,
    catalog_db: Path | None = None,
) -> dict[str, Any]:
    """Build read-only Area Engine overlay for one project."""
    crosswalk_path = crosswalk_path or DEFAULT_PHASE_W
    trusted_db = trusted_db or DEFAULT_TRUSTED
    catalog_db = catalog_db or DEFAULT_CATALOG

    if not crosswalk_path.is_file() or not trusted_db.is_file():
        return {
            "ok": False,
            "project_id": project_id,
            "error": "ข้อมูลอ้างอิงไม่พร้อม (Phase W หรือ RealXtate trusted DB)",
            "overlay_kind": "AREA_ENGINE_ANALYSIS",
            "not_production_truth": True,
            "disclaimer_th": "ผลวิเคราะห์นี้ยังไม่ได้แก้ข้อมูลจริง",
        }

    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    seeds = load_area_seeds(trusted_db)
    stations = load_stations(trusted_db)
    contexts = load_project_contexts(trusted_db, catalog_db, crosswalk)
    ctx = contexts.get(project_id)
    if not ctx:
        return {
            "ok": False,
            "project_id": project_id,
            "error": "ไม่พบโครงการในข้อมูลอ้างอิง",
            "overlay_kind": "AREA_ENGINE_ANALYSIS",
            "not_production_truth": True,
            "disclaimer_th": "ผลวิเคราะห์นี้ยังไม่ได้แก้ข้อมูลจริง",
            "has_apply_path": False,
        }

    result = evaluate_project(ctx, seeds, stations)
    admin = resolve_admin_geography(ctx.latitude or 0.0, ctx.longitude or 0.0) if ctx.latitude else None

    existing_lines = []
    for audit in result.get("existing_assignment_audit") or []:
        line = _format_area_line(audit)
        if audit.get("audit") == SUPPORT_IMPLAUSIBLE:
            line["explanation_th"].insert(0, "การกำหนดทำเลเดิมไม่สอดคล้องกับพิกัด")
        existing_lines.append(line)

    candidate_lines = [
        _format_area_line(c)
        for c in (result.get("candidate_evaluations") or [])[:8]
        if c.get("classification") in {CLASS_AUTO_SAFE, CLASS_REVIEW, CLASS_REJECT_QUARANTINE}
    ]

    project_outcome = result.get("project_outcome") or _outcome_from_classification(
        result.get("classification", ""), ""
    )

    coord_provenance_th: list[str] = []
    prov = getattr(ctx, "acquired_provenance", None)
    if ctx.latitude is not None and ctx.longitude is not None:
        coord_provenance_th.append(f"พิกัดโครงการ: {ctx.latitude:.6f}, {ctx.longitude:.6f}")
        tier = result.get("coordinate_tier") or ctx.coordinate_tier
        tier_labels = {
            "T1_COORD": "T1 — ยืนยันโดยเจ้าของ",
            "T2_COORD": "T2 — แหล่งอ้างอิงที่ระบบเชื่อถือ",
            "T3_COORD": "T3 — พบตรงกันจาก 2 แหล่งอิสระ",
            "T4_COORD": "T4 — พบจาก 1 แหล่ง (ยังไม่ใช้แก้ข้อมูลอัตโนมัติ)",
        }
        coord_provenance_th.append(f"ระดับหลักฐาน: {tier_labels.get(tier, tier)}")
    if prov and prov.get("candidates"):
        lineages = {c.get("evidence_lineage_id") for c in prov["candidates"]}
        if len(prov["candidates"]) >= 2 and len(lineages) == 1:
            coord_provenance_th.append(
                "พบข้อมูลหลายจุด แต่สืบย้อนกลับไปยังแหล่งเดิมเดียวกัน — จึงนับเป็นหลักฐาน 1 แหล่ง"
            )
        elif prov.get("outcome") == "RECOVERED_CORROBORATED":
            coord_provenance_th.append("พบพิกัดตรงกันจาก 2 แหล่งอิสระ")
        elif prov.get("outcome") == "CANDIDATE_SINGLE_SOURCE":
            coord_provenance_th.append("พบพิกัดจาก 1 แหล่ง — ยังไม่ใช้แก้ข้อมูลอัตโนมัติ")
        for c in prov["candidates"][:2]:
            if c.get("provider"):
                coord_provenance_th.append(f"แหล่งข้อมูล: {c['provider']}")

    return {
        "ok": True,
        "project_id": project_id,
        "project_name": result.get("project_name"),
        "overlay_kind": "AREA_ENGINE_ANALYSIS",
        "not_production_truth": True,
        "disclaimer_th": "ผลวิเคราะห์นี้ยังไม่ได้แก้ข้อมูลจริง — ไม่ใช่ข้อมูล Pantip หรือ RealXtate ที่ใช้งานจริง",
        "section_title_th": "ผลตรวจสอบจาก Area Engine",
        "project_outcome": project_outcome,
        "project_outcome_label_th": OUTCOME_LABEL_TH.get(project_outcome, project_outcome),
        "coordinate_tier": result.get("coordinate_tier"),
        "coordinate_usable": result.get("coordinate_usable"),
        "coordinate_provenance_th": coord_provenance_th,
        "picked_areas": [_format_area_line(a) for a in result.get("picked_areas") or []],
        "existing_assignment_analysis": existing_lines,
        "top_candidates": candidate_lines,
        "admin_geography": admin.to_dict() if admin else None,
        "has_apply_path": False,
    }
