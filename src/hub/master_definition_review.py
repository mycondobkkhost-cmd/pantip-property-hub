"""Owner master definition review packets — Phase Z4."""

from __future__ import annotations

from typing import Any

from src.hub.area_candidate_evidence import build_all_candidate_packets
from src.hub.shared_master.area_contract import SEMANTIC_REVIEWS, build_owner_review_packet_pattanakarn, build_owner_review_packet_rama9


def build_review_index() -> dict[str, Any]:
    return {
        "review_version": "z4-v2",
        "scope": "MASTER_DEFINITION_ONLY",
        "decision_count": 2,
        "topics": [
            {"id": "phatthanakan", "title_th": "พัฒนาการ", "status": "REVIEW_REQUIRED"},
            {"id": "rama9", "title_th": "พระราม 9", "status": "REVIEW_REQUIRED"},
        ],
        "deferred": [{"id": "suan_luang", "reason": "INSUFFICIENT_EVIDENCE"}],
        "production_warning_th": "การเลือกในหน้านี้ยังไม่แก้ข้อมูล Production",
        "what_will_not_change": [
            "พิกัดโครงการ",
            "รายการประกาศ (listings)",
            "การมอบหมายพื้นที่อัตโนมัติ",
            "ข้อมูล Production บน Fly",
        ],
    }


def build_pattanakarn_packet_v2() -> dict[str, Any]:
    base = build_owner_review_packet_pattanakarn()
    pkt = build_all_candidate_packets().get("phatthanakan", {})
    base["packet_version"] = "v2"
    base["status"] = "REVIEW_REQUIRED"
    base["owner_decision_recorded"] = False
    base["current_definition"] = {
        "semantic_kind": "CORRIDOR",
        "canonical_name_th": "พัฒนาการ",
        "canonical_name_en": "Phatthanakan",
        "review_status": "READY_FOR_OWNER_REVIEW",
    }
    base["options"] = [
        {
            "id": "A",
            "label_th": "ทางลอด/ถนนสาย (Corridor เท่านั้น)",
            "meaning_th": "พัฒนาการหมายถึงแกนถนนพัฒนาการ — โครงการจะถูกจับตามแนวถนน ไม่ใช่วงกลมแบบทองหล่อ",
            "search_behavior_th": "ค้นหา 'พัฒนาการ' จะแสดงโครงการที่อยู่ตามแกนถนน",
            "advantages_th": ["ตรงกับความหมายทางภูมิศาสตร์", "ลดการจับผิดเป็นย่านวงกลม"],
            "risks_th": ["อาจไม่ตรงกับภาษาตลาดที่เรียก 'ย่านพัฒนาการ'"],
            "realxtate_effect": "Filter ตาม corridor anchor ไม่ใช่ radius แบบ neighborhood",
            "pantip_effect": "Area engine ใช้ corridor distance แทน marketplace radius",
        },
        {
            "id": "B",
            "label_th": "พื้นที่ตลาด (Marketplace Area)",
            "meaning_th": "พัฒนาการเป็นย่านตลาดแบบ Thonglor / On Nut",
            "search_behavior_th": "ค้นหา 'พัฒนาการ' เป็น neighborhood เดียว",
            "advantages_th": ["ตรงกับภาษาตลาดทั่วไป"],
            "risks_th": ["อาจจับโครงการนอกแกนถนนเข้ามา", "ขอบเขตไม่ชัด"],
            "realxtate_effect": "Browse/filter แบบ area เดียว",
            "pantip_effect": "PRIMARY area assignment แบบ radius",
        },
        {
            "id": "C",
            "label_th": "Corridor + ความสัมพันธ์ค้นหา/ตลาด",
            "meaning_th": "เก็บ Corridor เป็นความหมายหลัก แต่เชื่อมกับ filter ตลาดได้",
            "search_behavior_th": "ค้นหาอาจแสดงทั้งแกนถนนและความสัมพันธ์ตลาด",
            "advantages_th": ["ยืดหยุ่นสำหรับ search UX"],
            "risks_th": ["ซับซ้อนกว่า", "ต้องกำหนดกฎชัดเจน"],
            "realxtate_effect": "Corridor primary + optional marketplace relation",
            "pantip_effect": "Corridor + searchable marketplace link",
        },
    ]
    base["representative_projects"] = [
        {"name": "THE PLANT ESTIQUE PATTANAKARN 38", "note": "ชื่อโครงการมีพัฒนาการ"},
        {"name": "Lumpini Onnut-Phattanakarn", "note": "ขอบเขต On Nut + Phatthanakan"},
    ]
    base["nearby_areas"] = ["onnut", "suan_luang", "bang_na", "srinagarindra"]
    base["evidence_summary"] = pkt
    return base


def build_rama9_packet_v2() -> dict[str, Any]:
    base = build_owner_review_packet_rama9()
    pkt = build_all_candidate_packets().get("rama9", {})
    base["packet_version"] = "v2"
    base["status"] = "REVIEW_REQUIRED"
    base["owner_decision_recorded"] = False
    base["owner_question_th"] = "ถ้าผู้ใช้เลือก พระราม 9 ใน RealXtate เขาควรเห็นอะไร?"
    base["current_definition"] = {
        "recommendation": "MARKETPLACE_GROUP candidate (not approved)",
        "note": "Z3 recommendation only — owner has not decided",
    }
    # Verified children from RealXtate seed + group config
    base["verified_children"] = [
        {"identity_key": "rama_9", "semantic_kind": "MARKETPLACE_AREA", "name_th": "พระราม 9", "evidence": "market_area_seed_8z2b + group_asoke_rama9 member"},
        {"identity_key": "huai_khwang", "semantic_kind": "MARKETPLACE_AREA", "name_th": "ห้วยขวาง", "evidence": "group_ratchada member"},
        {"identity_key": "ratchada", "semantic_kind": "MARKETPLACE_AREA", "name_th": "รัชดา", "evidence": "group_ratchada member"},
        {"identity_key": "phetchaburi", "semantic_kind": "MARKETPLACE_AREA", "name_th": "เพชรบุรี", "evidence": "group_asoke_rama9 member"},
        {"identity_key": "asoke", "semantic_kind": "MARKETPLACE_AREA", "name_th": "อโศก", "evidence": "group_asoke_rama9 member"},
        {"identity_key": "ratchada_rama9_corridor", "semantic_kind": "CORRIDOR", "name_th": "แกนรัชดา–พระราม 9", "evidence": "area_spatial_seed CORRIDOR"},
    ]
    base["group_context"] = {
        "existing_realxtate_group": "group_asoke_rama9",
        "members": ["asoke", "phetchaburi", "rama_9", "khlong_toei"],
        "note": "RealXtate already has Asoke–Rama 9 group; owner decides if Rama 9 standalone search matches this",
    }
    base["representative_projects"] = [
        {"name": "Life Asoke Rama 9", "note": "อยู่ทั้งอโศกและพระราม 9"},
        {"name": "COBE Ratchada - Rama9", "note": "Pantip-only; ชื่อมี Rama 9"},
    ]
    base["what_user_sees_options"] = [
        "โครงการในพื้นที่ย่อยที่เกี่ยวข้อง (rama_9, asoke, phetchaburi, ...)",
        "ไม่ใช่จุดเดียวรอบ MRT พระราม 9 เท่านั้น",
        "อาจรวมกลุ่ม Asoke–Rama 9 ตาม RealXtate group config",
    ]
    base["supporting_evidence"] = pkt
    return base


def build_all_packets_v2() -> dict[str, Any]:
    return {
        "index": build_review_index(),
        "phatthanakan": build_pattanakarn_packet_v2(),
        "rama9": build_rama9_packet_v2(),
    }
