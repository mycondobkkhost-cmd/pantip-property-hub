#!/usr/bin/env python3
"""Generate synthetic data_seed/ for local bootstrap — no PII, no real credentials."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "data_seed"

PROJECTS = [
    {
        "id": "seed-proj-001",
        "bucket_key": "sample_tower_a",
        "canonical_name": "Sample Tower A",
        "aliases": ["Sample A", "Tower A Condo"],
        "transit_verified": ["BTS อโศก"],
        "transit_unverified": [],
        "zone_verified": ["อโศก", "สุขุมวิท"],
        "zone_unverified": [],
        "location_status": "verified",
        "is_thru_thonglor": False,
        "listing_count": 0,
    },
    {
        "id": "seed-proj-002",
        "bucket_key": "sample_tower_b",
        "canonical_name": "Sample Tower B",
        "aliases": ["Sample B"],
        "transit_verified": ["MRT สามย่าน"],
        "transit_unverified": [],
        "zone_verified": ["สามย่าน"],
        "zone_unverified": [],
        "location_status": "verified",
        "is_thru_thonglor": False,
        "listing_count": 0,
    },
    {
        "id": "seed-proj-003",
        "bucket_key": "sample_dup_block",
        "canonical_name": "Duplicate Code Block (synthetic)",
        "aliases": ["Dup Block"],
        "transit_verified": ["BTS พระโขนง"],
        "transit_unverified": [],
        "zone_verified": ["พระโขนง"],
        "zone_unverified": [],
        "location_status": "verified",
        "is_thru_thonglor": False,
        "listing_count": 0,
    },
    {
        "id": "seed-proj-004",
        "bucket_key": "co_agent_demo",
        "canonical_name": "Co-Agent Demo Condo",
        "aliases": ["COA Demo"],
        "transit_verified": ["BTS ทองหล่อ"],
        "transit_unverified": [],
        "zone_verified": ["ทองหล่อ"],
        "zone_unverified": [],
        "location_status": "verified",
        "is_thru_thonglor": False,
        "listing_count": 0,
    },
    {
        "id": "seed-proj-005",
        "bucket_key": "studio_hub",
        "canonical_name": "Studio Hub Place",
        "aliases": [],
        "transit_verified": ["ARL มักกะสัน"],
        "transit_unverified": [],
        "zone_verified": ["มักกะสัน"],
        "zone_unverified": [],
        "location_status": "pending_verification",
        "is_thru_thonglor": False,
        "listing_count": 0,
    },
    {
        "id": "seed-proj-006",
        "bucket_key": "riverside_sample",
        "canonical_name": "Riverside Sample",
        "aliases": ["River Sample"],
        "transit_verified": ["BTS สะพานตากสิน"],
        "transit_unverified": [],
        "zone_verified": ["ธนบุรี"],
        "zone_unverified": [],
        "location_status": "verified",
        "is_thru_thonglor": False,
        "listing_count": 0,
    },
    {
        "id": "seed-proj-007",
        "bucket_key": "budget_block",
        "canonical_name": "Budget Block Condo",
        "aliases": [],
        "transit_verified": ["MRT ห้วยขวาง"],
        "transit_unverified": [],
        "zone_verified": ["ห้วยขวาง"],
        "zone_unverified": [],
        "location_status": "verified",
        "is_thru_thonglor": False,
        "listing_count": 0,
    },
    {
        "id": "seed-proj-008",
        "bucket_key": "penthouse_demo",
        "canonical_name": "Penthouse Demo Residences",
        "aliases": ["PH Demo"],
        "transit_verified": ["BTS ช่องนนทรี"],
        "transit_unverified": [],
        "zone_verified": ["ช่องนนทรี"],
        "zone_unverified": [],
        "location_status": "verified",
        "is_thru_thonglor": False,
        "listing_count": 0,
    },
]

PROJ_NAME = {p["id"]: p["canonical_name"] for p in PROJECTS}


def _base_prop(
    pid: str,
    code: str,
    *,
    prefix: str = "RXT",
    project_id: str,
    rent: str = "15000",
    sale: str = "",
    post_url: str = "",
    post_pages_url: str = "",
    kind: str = "direct",
) -> dict:
    proj = next(p for p in PROJECTS if p["id"] == project_id)
    zones = list(proj.get("zone_verified") or [])
    transit = list(proj.get("transit_verified") or [])
    return {
        "id": pid,
        "code": code,
        "code_prefix": prefix,
        "data_source": "hub",
        "listing_kind": kind,
        "project_id": project_id,
        "project_name": PROJ_NAME[project_id],
        "last_listed_at": "01/09/2026",
        "property_type": "Condo",
        "bedrooms": "1 Bed 1 Bath",
        "size_sqm": "32",
        "floor": "12",
        "rent_price": rent,
        "sale_price": sale,
        "source_url": "",
        "post_url": post_url,
        "post_pages_url": post_pages_url,
        "owner_facebook": [],
        "owner_phones": [],
        "owner_lines": [],
        "notes": "",
        "page_post_text": "",
        "text_th": "",
        "text_en": "",
        "import_status": "active",
        "media_status": "pending",
        "sheet_row": "",
        "transit_from_sheet": transit,
        "location_ref": ", ".join(zones[:3]),
        "duplicate_flags": [],
    }


def build_properties() -> list[dict]:
    props: list[dict] = []

    props.append(
        _base_prop(
            "seed-prop-rxt-001",
            "RXT0001",
            project_id="seed-proj-001",
            rent="18000",
            post_url="https://example.com/fb/post/rxt0001",
        )
    )
    props.append(
        _base_prop(
            "seed-prop-coa-001",
            "COA0001",
            prefix="COA",
            project_id="seed-proj-004",
            kind="co_agent",
            rent="22000",
            post_pages_url="https://example.com/fb/page/coa0001",
        )
    )

    dup_projects = ("seed-proj-003", "seed-proj-006", "seed-proj-007")
    for i, proj_id in enumerate(dup_projects, start=1):
        props.append(
            _base_prop(
                f"seed-prop-dup-{i}",
                "PTP4734",
                prefix="PTP",
                project_id=proj_id,
                rent=str(14000 + i * 500),
                post_url=f"https://example.com/fb/post/ptp4734-{i}",
            )
        )

    co_rows = [
        ("seed-prop-coa-002", "COA0002", "seed-proj-004", "https://example.com/fb/post/coa0002"),
        ("seed-prop-coa-003", "COA0003", "seed-proj-004", "https://example.com/fb/page/coa0003"),
        ("seed-prop-coa-004", "COA0004", "seed-proj-005", "https://example.com/fb/post/coa0004"),
        ("seed-prop-coa-005", "COA0005", "seed-proj-006", "https://example.com/fb/post/coa0005"),
    ]
    for pid, code, proj_id, url in co_rows:
        props.append(
            _base_prop(
                pid,
                code,
                prefix="COA",
                project_id=proj_id,
                kind="co_agent",
                rent="20000",
                post_url=url if "/post/" in url else "",
                post_pages_url=url if "/page/" in url else "",
            )
        )

    extras = [
        ("seed-prop-rxt-002", "RXT0002", "seed-proj-002", "12000"),
        ("seed-prop-rxt-003", "RXT0003", "seed-proj-005", "13500"),
        ("seed-prop-rxt-004", "RXT0004", "seed-proj-006", "25000", "3500000"),
        ("seed-prop-rxt-005", "RXT0005", "seed-proj-007", "11000"),
        ("seed-prop-rxt-006", "RXT0006", "seed-proj-008", "45000", "8900000"),
        ("seed-prop-rxt-007", "RXT0007", "seed-proj-001", "16500"),
        ("seed-prop-rxt-008", "RXT0008", "seed-proj-002", "17500"),
        ("seed-prop-rxt-009", "RXT0009", "seed-proj-007", "9900"),
        ("seed-prop-rxt-010", "RXT0010", "seed-proj-008", "52000"),
    ]
    for row in extras:
        pid, code, proj_id = row[0], row[1], row[2]
        rent = row[3]
        sale = row[4] if len(row) > 4 else ""
        props.append(
            _base_prop(
                pid,
                code,
                project_id=proj_id,
                rent=rent,
                sale=sale,
                post_url=f"https://example.com/fb/post/{code.lower()}",
            )
        )

    counts: dict[str, int] = {}
    for p in props:
        counts[p["project_id"]] = counts.get(p["project_id"], 0) + 1
    for proj in PROJECTS:
        proj["listing_count"] = counts.get(proj["id"], 0)

    return props


def main() -> int:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    properties = build_properties()
    (SEED_DIR / "projects.json").write_text(
        json.dumps(PROJECTS, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (SEED_DIR / "properties.json").write_text(
        json.dumps(properties, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "projects": len(PROJECTS),
                "properties": len(properties),
                "duplicate_code_ptp4734": sum(1 for p in properties if p["code"] == "PTP4734"),
                "seed_dir": str(SEED_DIR),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
