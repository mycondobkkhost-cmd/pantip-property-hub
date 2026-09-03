"""Shared area taxonomy contract — Phase Z3."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.hub.area_candidate_evidence import build_all_candidate_packets, discover_other_candidates

AREA_SEMANTIC_KINDS = frozenset(
    {
        "MARKETPLACE_GROUP",
        "MARKETPLACE_AREA",
        "CORRIDOR",
        "TRANSIT_HUB",
        "ADMIN_AREA",
    }
)

SPATIAL_SEED = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "data_fixtures"
    / "area_engine"
    / "market_area_spatial_seed_v0.2.json"
)
RX_GROUP_CONFIG = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/services/marketplace-group-config.ts"
)

# Semantic review recommendations (evidence-based, not owner-approved)
SEMANTIC_REVIEWS = {
    "rama9": {
        "z2_classification": "UMBRELLA_GROUP",
        "recommended_model": "MARKETPLACE_GROUP with child areas",
        "candidate_children": [
            {"identity_key": "rama9", "semantic_kind": "MARKETPLACE_AREA", "note": "MRT Rama 9 station belt"},
            {"identity_key": "huai_khwang", "semantic_kind": "MARKETPLACE_AREA", "note": "adjacent market area"},
            {"identity_key": "ratchada", "semantic_kind": "MARKETPLACE_AREA", "note": "Ratchadaphisek corridor"},
            {"identity_key": "phetchaburi", "semantic_kind": "MARKETPLACE_AREA", "note": "Phetchaburi interchange belt"},
            {"identity_key": "makkasan", "semantic_kind": "MARKETPLACE_AREA", "note": "ARL Makkasan"},
            {"identity_key": "ratchada_rama9_corridor", "semantic_kind": "CORRIDOR", "note": "road/corridor linkage"},
        ],
        "realxtate_evidence": "group_asoke_rama9 in marketplace-group-config.ts; Rama 9 removed from Ratchada group in 8Z.5A",
        "review_status": "CANDIDATE_OWNER_REVIEW",
        "owner_decision_recorded": False,
    },
    "phatthanakan": {
        "z2_classification": "CORRIDOR",
        "canonical_name_th": "พัฒนาการ",
        "canonical_name_en": "Phatthanakan",
        "aliases": ["Pattanakarn", "Phatthanakan", "พัฒนาการ"],
        "recommended_model": "CORRIDOR with optional MARKETPLACE_AREA search relation",
        "options": [
            "A: CORRIDOR only",
            "B: MARKETPLACE_AREA only",
            "C: CORRIDOR + marketplace/search relation",
        ],
        "review_status": "READY_FOR_OWNER_REVIEW",
        "owner_decision_recorded": False,
    },
    "suan_luang": {
        "z2_classification": "INSUFFICIENT_EVIDENCE",
        "distinct_entities_needed": [
            {"identity_key": "admin_suan_luang", "semantic_kind": "ADMIN_AREA", "name_th": "เขตสวนหลวง"},
            {"identity_key": "suan_luang", "semantic_kind": "MARKETPLACE_AREA", "name_th": "สวนหลวง", "status": "CANDIDATE"},
            {"identity_key": "yl_suan_luang_rama_9", "semantic_kind": "TRANSIT_HUB", "name_th": "MRT สวนหลวง ร.9"},
        ],
        "review_status": "INSUFFICIENT_EVIDENCE",
        "owner_decision_recorded": False,
    },
    "sukhumvit": {
        "legacy_token_count_note": "1152 legacy tokens in Z2",
        "recommended_model": "hierarchy: CORRIDOR (sukhumvit) + MARKETPLACE_GROUPs (central/inner/outer) + MARKETPLACE_AREAs",
        "do_not_treat_as_single_area": True,
        "realxtate_evidence": "group_central_sukhumvit, group_inner_sukhumvit, group_outer_sukhumvit in marketplace-group-config.ts",
        "candidate_hierarchy": [
            {"identity_key": "sukhumvit", "semantic_kind": "CORRIDOR"},
            {"identity_key": "sukhumvit_inner", "semantic_kind": "MARKETPLACE_AREA"},
            {"identity_key": "sukhumvit_middle", "semantic_kind": "MARKETPLACE_AREA"},
            {"identity_key": "sukhumvit_outer", "semantic_kind": "MARKETPLACE_AREA"},
            {"identity_key": "group_central_sukhumvit", "semantic_kind": "MARKETPLACE_GROUP"},
            {"identity_key": "group_inner_sukhumvit", "semantic_kind": "MARKETPLACE_GROUP"},
            {"identity_key": "group_outer_sukhumvit", "semantic_kind": "MARKETPLACE_GROUP"},
        ],
        "review_status": "PARTIAL_EVIDENCE",
    },
}


def _load_seed_areas() -> list[dict[str, Any]]:
    if not SPATIAL_SEED.is_file():
        return []
    return json.loads(SPATIAL_SEED.read_text(encoding="utf-8")).get("areas", [])


def _entity_from_seed(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": seed.get("area_id"),
        "identity_key": seed.get("identity_key"),
        "canonical_name_th": seed.get("canonical_name_th"),
        "canonical_name_en": seed.get("canonical_name_en"),
        "semantic_kind": seed.get("semantic_kind", "MARKETPLACE_AREA"),
        "aliases": seed.get("aliases") or [],
        "parent_group_relations": [],
        "member_relations": [],
        "adjacency": seed.get("adjacent_identity_keys") or [],
        "anchor_evidence": seed.get("anchors") or [],
        "confidence": seed.get("confidence", "MEDIUM"),
        "review_status": seed.get("review_status", "APPROVED"),
        "provenance": seed.get("source_records") or ["market_area_spatial_seed_v0.2"],
        "status": seed.get("status", "EXISTING_APPROVED"),
    }


def build_shared_area_master_draft() -> dict[str, Any]:
    """Build sanitized shared area master draft v0.1."""
    seeds = _load_seed_areas()
    entities = [_entity_from_seed(s) for s in seeds]

    # Add candidate semantic review entities not fully in seed
    for key, review in SEMANTIC_REVIEWS.items():
        if key in {e["identity_key"] for e in entities}:
            for e in entities:
                if e["identity_key"] == key:
                    e["semantic_review"] = review
            continue
        pkt = build_all_candidate_packets().get(key)
        if pkt:
            entities.append(
                {
                    "entity_id": f"candidate_{key}_v01",
                    "identity_key": key,
                    "canonical_name_th": pkt.get("canonical_name_th"),
                    "canonical_name_en": pkt.get("canonical_name_en"),
                    "semantic_kind": pkt.get("semantic_kind", "MARKETPLACE_AREA"),
                    "aliases": [],
                    "parent_group_relations": [],
                    "member_relations": [],
                    "adjacency": pkt.get("adjacent_areas") or [],
                    "anchor_evidence": pkt.get("transit_anchors") or [],
                    "confidence": pkt.get("confidence", "LOW"),
                    "review_status": pkt.get("review_status", "REVIEW_REQUIRED"),
                    "provenance": pkt.get("evidence_sources") or [],
                    "status": "CANDIDATE",
                    "semantic_review": review,
                }
            )

    # Marketplace groups from RealXtate config (read-only reference)
    groups = [
        {
            "entity_id": "group_central_sukhumvit",
            "identity_key": "group_central_sukhumvit",
            "canonical_name_th": "สุขุมวิทกลาง",
            "canonical_name_en": "Central Sukhumvit",
            "semantic_kind": "MARKETPLACE_GROUP",
            "review_status": "OWNER_APPROVED_FOR_STAGED_ENABLEMENT",
            "provenance": ["realxtate:marketplace-group-config.ts"],
        },
        {
            "entity_id": "group_inner_sukhumvit",
            "identity_key": "group_inner_sukhumvit",
            "canonical_name_th": "สุขุมวิทใน",
            "canonical_name_en": "Inner Sukhumvit",
            "semantic_kind": "MARKETPLACE_GROUP",
            "review_status": "OWNER_APPROVED_FOR_STAGED_ENABLEMENT",
            "provenance": ["realxtate:marketplace-group-config.ts"],
        },
        {
            "entity_id": "group_outer_sukhumvit",
            "identity_key": "group_outer_sukhumvit",
            "canonical_name_th": "สุขุมวิทนอก",
            "canonical_name_en": "Outer Sukhumvit",
            "semantic_kind": "MARKETPLACE_GROUP",
            "review_status": "OWNER_APPROVED_FOR_STAGED_ENABLEMENT",
            "provenance": ["realxtate:marketplace-group-config.ts"],
        },
        {
            "entity_id": "group_asoke_rama9",
            "identity_key": "group_asoke_rama9",
            "canonical_name_th": "อโศก – พระราม 9",
            "canonical_name_en": "Asoke – Rama 9",
            "semantic_kind": "MARKETPLACE_GROUP",
            "review_status": "OWNER_APPROVED_FOR_STAGED_ENABLEMENT",
            "provenance": ["realxtate:marketplace-group-config.ts"],
            "member_relations": [
                {"area_id": "asoke", "relation": "MEMBER", "confidence": "HIGH"},
                {"area_id": "rama9", "relation": "MEMBER", "confidence": "HIGH"},
                {"area_id": "phrom_phong", "relation": "MEMBER", "confidence": "MEDIUM"},
            ],
        },
        {
            "entity_id": "group_ratchada",
            "identity_key": "group_ratchada",
            "canonical_name_th": "รัชดา",
            "canonical_name_en": "Ratchada",
            "semantic_kind": "MARKETPLACE_GROUP",
            "review_status": "OWNER_APPROVED_FOR_STAGED_ENABLEMENT",
            "provenance": ["realxtate:marketplace-group-config.ts"],
        },
    ]

    return {
        "shared_master_version": "v0.1",
        "schema_version": "shared-area-master-0.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "semantic_kinds": sorted(AREA_SEMANTIC_KINDS),
        "semantic_reviews": SEMANTIC_REVIEWS,
        "group_subarea_contract": {
            "group_fields": ["group_id", "group_name_th", "group_name_en", "member_relations"],
            "member_relation_fields": ["area_id", "relation", "confidence", "evidence"],
            "note": "PRIMARY/SECONDARY/EDGE are project↔area roles, NOT group membership roles",
        },
        "entities": entities,
        "marketplace_groups": groups,
        "discovered_candidates": discover_other_candidates(10),
    }


def build_owner_review_packet_pattanakarn() -> dict[str, Any]:
    pkt = build_all_candidate_packets().get("phatthanakan", {})
    return {
        "packet_id": "owner_master_pattanakarn_v01",
        "language": "th",
        "title": "พัฒนาการคืออะไรในระบบ?",
        "question": "พัฒนาการควรถูกนิยามอย่างไรใน Shared Master?",
        "options": [
            {
                "id": "A",
                "label_th": "ทางลอด/ถนนสาย (Corridor เท่านั้น)",
                "search_effect": "ค้นหา 'พัฒนาการ' จะจับโครงการตามแกนถนน ไม่ใช่พื้นที่ตลาดแบบวงกลม",
            },
            {
                "id": "B",
                "label_th": "พื้นที่ตลาด (Marketplace Area)",
                "search_effect": "ค้นหา 'พัฒนาการ' เป็น neighborhood แบบ Phrom Phong / Thonglor",
            },
            {
                "id": "C",
                "label_th": "Corridor + ความสัมพันธ์ค้นหา/ตลาด",
                "search_effect": "เก็บ Corridor เป็นความหมายหลัก แต่ยังเชื่อมกับ filter ตลาดได้",
            },
        ],
        "canonical_spellings": {
            "th": "พัฒนาการ",
            "en_primary": "Phatthanakan",
            "en_aliases": ["Pattanakarn"],
        },
        "representative_projects": pkt.get("token_frequency"),
        "evidence_summary": pkt,
        "owner_decision_recorded": False,
    }


def build_owner_review_packet_rama9() -> dict[str, Any]:
    pkt = build_all_candidate_packets().get("rama9", {})
    review = SEMANTIC_REVIEWS["rama9"]
    return {
        "packet_id": "owner_master_rama9_v01",
        "language": "th",
        "title": "พระราม 9 ควรเป็นกลุ่มพื้นที่ใหญ่หรือพื้นที่เดียว?",
        "explanation_th": (
            "พระราม 9 อาจเป็นพื้นที่ตลาดขนาดใหญ่ที่ครอบคลุมหลายพื้นที่ย่อย "
            "เช่น ห้วยขวาง รัชดา เพชรบุรี มักกะสัน — ไม่ควรบังคับเป็นจุดเดียว"
        ),
        "candidate_children": review["candidate_children"],
        "supporting_evidence": pkt,
        "ambiguous_edges": [
            "Life Asoke Rama 9 อยู่ทั้งอโศกและพระราม 9",
            "Ratchada group เคยมี Rama 9 แต่ถูกแยกใน 8Z.5A",
        ],
        "search_filter_effect": "Group browsing vs single-area radius จะเปลี่ยนผลลัพธ์โครงการที่ขอบเขต",
        "owner_decision_recorded": False,
    }
