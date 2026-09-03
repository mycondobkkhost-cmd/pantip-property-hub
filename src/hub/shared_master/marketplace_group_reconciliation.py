"""RealXtate marketplace group reconciliation — Phase Z4."""

from __future__ import annotations

from typing import Any

# All 7 groups from RealXtate marketplace-group-config.ts (read-only reference).
REALXTATE_MARKETPLACE_GROUPS: list[dict[str, Any]] = [
    {
        "group_id": "group_central_sukhumvit",
        "slug": "central-sukhumvit",
        "canonical_name_th": "สุขุมวิทตอนกลาง",
        "canonical_name_en": "Central Sukhumvit",
        "members": ["phrom_phong", "thonglor", "ekkamai"],
        "semantic_purpose": "Core cross-shopping corridor; pilot UX group",
        "status": "READY",
        "shared_classification": "SHARED_CANONICAL_CANDIDATE",
        "z3_draft_included": True,
        "exclusion_reason": None,
    },
    {
        "group_id": "group_inner_sukhumvit",
        "slug": "inner-sukhumvit",
        "canonical_name_th": "สุขุมวิทตอนใน",
        "canonical_name_en": "Inner Sukhumvit",
        "members": ["nana", "ploenchit", "siam"],
        "semantic_purpose": "CBD/shopping core",
        "status": "READY",
        "shared_classification": "SHARED_CANONICAL_CANDIDATE",
        "z3_draft_included": True,
        "exclusion_reason": None,
    },
    {
        "group_id": "group_outer_sukhumvit",
        "slug": "outer-sukhumvit",
        "canonical_name_th": "สุขุมวิทตอนนอก",
        "canonical_name_en": "Outer Sukhumvit",
        "members": ["ekkamai", "phra_khanong", "onnut", "udom_suk", "bearing"],
        "semantic_purpose": "East BTS Sukhumvit belt",
        "status": "READY",
        "shared_classification": "SHARED_CANONICAL_CANDIDATE",
        "z3_draft_included": True,
        "exclusion_reason": None,
    },
    {
        "group_id": "group_asoke_rama9",
        "slug": "asoke-rama9",
        "canonical_name_th": "อโศก–พระราม 9",
        "canonical_name_en": "Asoke – Rama 9",
        "members": ["asoke", "phetchaburi", "rama_9", "khlong_toei"],
        "semantic_purpose": "CBD / new-CBD corridor; relevant to Rama 9 owner review",
        "status": "READY",
        "shared_classification": "SHARED_CANONICAL_CANDIDATE",
        "z3_draft_included": True,
        "exclusion_reason": None,
    },
    {
        "group_id": "group_ratchada",
        "slug": "ratchada-huai-khwang",
        "canonical_name_th": "รัชดา–ห้วยขวาง",
        "canonical_name_en": "Ratchada – Huai Khwang",
        "members": ["ratchada", "huai_khwang"],
        "semantic_purpose": "MRT Blue cultural belt; Rama 9 removed in 8Z.5A",
        "status": "READY",
        "shared_classification": "SHARED_CANONICAL_CANDIDATE",
        "z3_draft_included": True,
        "exclusion_reason": None,
    },
    {
        "group_id": "group_north_phaholyothin",
        "slug": "phaholyothin-north",
        "canonical_name_th": "พหลโยธินตอนบน",
        "canonical_name_en": "Upper Phaholyothin",
        "members": ["ari", "saphan_kwai", "chatuchak", "lat_phrao"],
        "semantic_purpose": "BTS north corridor",
        "status": "READY",
        "shared_classification": "SHARED_CANONICAL_CANDIDATE",
        "z3_draft_included": False,
        "exclusion_reason": "Z3 draft omission (implementation oversight); included in Z4",
    },
    {
        "group_id": "group_sathon_silom",
        "slug": "sathon-silom",
        "canonical_name_th": "สาทร–สีลม",
        "canonical_name_en": "Sathorn – Silom",
        "members": ["sathon", "silom", "charoen_nakhon"],
        "semantic_purpose": "CBD / riverside office-renter cluster",
        "status": "READY",
        "shared_classification": "SHARED_CANONICAL_CANDIDATE",
        "z3_draft_included": False,
        "exclusion_reason": "Z3 draft omission (implementation oversight); included in Z4",
    },
]


def build_group_reconciliation() -> dict[str, Any]:
    included_z3 = [g for g in REALXTATE_MARKETPLACE_GROUPS if g["z3_draft_included"]]
    omitted_z3 = [g for g in REALXTATE_MARKETPLACE_GROUPS if not g["z3_draft_included"]]
    return {
        "realxtate_total": len(REALXTATE_MARKETPLACE_GROUPS),
        "z3_draft_count": len(included_z3),
        "z4_draft_count": len(REALXTATE_MARKETPLACE_GROUPS),
        "z3_omission_explanation": (
            "Z3 shared area master draft included only 5 of 7 RealXtate groups. "
            "Omitted: group_north_phaholyothin, group_sathon_silom. "
            "Cause: incomplete manual transcription in area_contract.py, not intentional exclusion. "
            "All 7 are SHARED_CANONICAL_CANDIDATE with PRODUCT_TAXONOMY provenance from RealXtate."
        ),
        "omitted_in_z3": [{"group_id": g["group_id"], "reason": g["exclusion_reason"]} for g in omitted_z3],
        "groups": REALXTATE_MARKETPLACE_GROUPS,
        "standalone_ready_areas": [
            {"identity_key": "bang_na", "reason": "No multi-area group adds browsing value yet"},
            {"identity_key": "ramkhamhaeng", "reason": "Inland east; thin overlap with Outer Sukhumvit"},
        ],
    }


def marketplace_groups_for_shared_draft() -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for g in REALXTATE_MARKETPLACE_GROUPS:
        groups.append(
            {
                "entity_id": g["group_id"],
                "identity_key": g["group_id"],
                "canonical_name_th": g["canonical_name_th"],
                "canonical_name_en": g["canonical_name_en"],
                "semantic_kind": "MARKETPLACE_GROUP",
                "review_status": "OWNER_APPROVED_FOR_STAGED_ENABLEMENT",
                "provenance": ["realxtate:marketplace-group-config.ts"],
                "shared_classification": g["shared_classification"],
                "member_relations": [
                    {"area_id": m, "relation": "MEMBER", "confidence": "HIGH"} for m in g["members"]
                ],
                "status": g["status"],
            }
        )
    return groups
