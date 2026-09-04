"""Owner-readable policy packet data — Phase Z8 (REVIEW ONLY, no production config)."""

from __future__ import annotations

from typing import Any

from src.hub.legacy_entry_date import audit_age_distribution
from src.hub.live_freshness_dry_run import (
    build_live_freshness_dry_run,
    compare_stale_public_policies,
    recommend_stale_public_policy,
)
from src.hub.recheck_capacity import (
    audit_backlog_by_listing_type,
    capacity_scenarios,
    contact_workload_scenarios,
    load_capacity_config,
    recommend_first_batch_strategy,
)


def build_owner_policy_packet(*, include_live_freshness: bool = False) -> dict[str, Any]:
    audit = audit_age_distribution()
    listing_audit = audit_backlog_by_listing_type()
    cfg = load_capacity_config()
    workloads = audit["recheck_workload_by_threshold"]
    fresh = None
    if include_live_freshness:
        try:
            fresh = build_live_freshness_dry_run()
        except Exception as exc:  # noqa: BLE001
            fresh = {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "review_only": True,
        "title_th": "นโยบายการติดตามทรัพย์และความสดประกาศ — ร่างทบทวน",
        "sections_th": [
            {
                "id": "old_properties",
                "title": "ทรัพย์เก่าในฐานข้อมูล",
                "body": f"มีทรัพย์ที่มีวันลงข้อมูลถูกต้อง {audit['valid_entry_date_count']} รายการ จากทั้งหมด {audit['total_properties']}",
            },
            {
                "id": "threshold_workload",
                "title": "ภาระงานตามเกณฑ์อายุ",
                "body": f">90 วัน: {workloads[90]} | >180 วัน: {workloads[180]} | >270 วัน: {workloads[270]} | >365 วัน: {workloads[365]}",
            },
            {
                "id": "backlog_vs_queue",
                "title": "Backlog vs คิวงานจริง",
                "body": "หลายพันรายการอาจเข้าเกณฑ์ แต่จะดึงเข้าคิว operator เฉพาะตามความจุรายวัน (เช่น 10/25/50/100 รายการ/วัน)",
            },
            {
                "id": "batch_sizes",
                "title": "ขนาดชุดงานที่แนะนำทดลอง",
                "body": "เริ่ม 25 รายการ/วัน/operator — ปรับได้หลังทบทวน",
            },
            {
                "id": "rent_sale",
                "title": "เช่า vs ขาย",
                "body": f"ประชากร: เช่า {listing_audit['population'].get('rent',0)} | ขาย {listing_audit['population'].get('sale',0)} | ทั้งคู่ {listing_audit['population'].get('both',0)}",
            },
            {
                "id": "freshness_ttl",
                "title": "ความสดประกาศ (RealXtate)",
                "body": "เช่า 7 วัน | ขาย 30 วัน — วันลงข้อมูลเก่าไม่เท่ากับวันยืนยันล่าสุด",
            },
            {
                "id": "bootstrap",
                "title": "Bootstrap ทรัพย์เก่า",
                "body": "แนะนำ HYBRID: สถานะ BOOTSTRAP_VERIFICATION_PENDING + ยืนยันเป็นชุด ไม่ซ่อนทั้ง catalog วันแรก",
            },
            {
                "id": "stale_public",
                "title": "นโยบาย stale ต่อสาธารณะ",
                "body": recommend_stale_public_policy()["rationale_th"],
            },
            {
                "id": "before_activation",
                "title": "ก่อนเปิดใช้งานจริง",
                "body": "ต้องมีการอนุมัติเกณฑ์ recheck, ขนาดชุดงาน, bootstrap freshness, และนโยบาย stale จากเจ้าของ",
            },
        ],
        "policy_choices": {
            "recheck_rent_days": [90, 180, 270, 365, "custom"],
            "recheck_sale_days": [90, 180, 270, 365, "custom"],
            "new_recheck_batch_per_day": [10, 25, 50, 100, "custom"],
            "freshness_bootstrap": ["staged_batch", "grace_period", "new_renewed_only", "hybrid"],
            "stale_public": [p["id"] for p in compare_stale_public_policies()],
        },
        "current_policy_candidates": cfg,
        "capacity_scenarios_summary": capacity_scenarios(),
        "contact_workload_summary": contact_workload_scenarios(),
        "first_batch_recommendation": recommend_first_batch_strategy(),
        "live_freshness": fresh,
        "owner_decisions_persisted": False,
        "test_only": True,
    }
