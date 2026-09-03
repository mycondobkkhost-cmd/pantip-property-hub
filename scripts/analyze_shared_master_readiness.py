#!/usr/bin/env python3
"""Analyze shared master readiness and inventories — Phase Z3."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.shared_master.project_contract import canonical_project_id_policy  # noqa: E402
from src.hub.shared_master.readiness import build_field_readiness_matrix, summarize_readiness  # noqa: E402

OUTPUT_DIR = Path("/tmp/pantip-phase-z3-shared-master")
RX_TRUSTED = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-trusted-master.sqlite"
)
RX_CATALOG = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-catalog.sqlite"
)


def _table_count(db: Path, table: str) -> int:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.Error:
        return -1
    finally:
        conn.close()


def build_realxtate_inventory() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "assets": [
            {
                "name": "project_master_v01",
                "path": str(RX_TRUSTED),
                "table": "project_master_v01",
                "record_count": _table_count(RX_TRUSTED, "project_master_v01"),
                "primary_id": "project_id",
                "authority": "CANONICAL_IDENTITY_V01",
                "shareable": True,
            },
            {
                "name": "market_area_seed_8z2b",
                "path": str(RX_TRUSTED),
                "table": "market_area_seed_8z2b",
                "record_count": _table_count(RX_TRUSTED, "market_area_seed_8z2b"),
                "primary_id": "area_id",
                "authority": "AREA_MASTER_V01_SEED",
                "shareable": True,
            },
            {
                "name": "marketplace_area_assignment_8z3",
                "path": str(RX_TRUSTED),
                "table": "marketplace_area_assignment_8z3",
                "record_count": _table_count(RX_TRUSTED, "marketplace_area_assignment_8z3"),
                "primary_id": "(project_id, area_id, role)",
                "authority": "REFERENCE_ASSIGNMENT",
                "shareable": True,
            },
            {
                "name": "transit_stations",
                "path": str(RX_TRUSTED),
                "table": "transit_stations",
                "record_count": _table_count(RX_TRUSTED, "transit_stations"),
                "primary_id": "station_id",
                "authority": "CANONICAL_TRANSIT",
                "shareable": True,
            },
            {
                "name": "property_projects",
                "path": str(RX_CATALOG),
                "table": "property_projects",
                "record_count": _table_count(RX_CATALOG, "property_projects"),
                "primary_id": "id",
                "authority": "SOURCE_CATALOG",
                "shareable": True,
            },
            {
                "name": "marketplace_groups",
                "path": "web/services/marketplace-group-config.ts",
                "record_count": 7,
                "primary_id": "group slug",
                "authority": "PRODUCT_TAXONOMY",
                "shareable": False,
            },
        ],
    }


def build_pantip_inventory() -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": [
            {
                "name": "phase_w_crosswalk",
                "path": str(Path.home() / "Backups/pantip-property-automation/phase-w-crosswalk-20260904T035800Z/live-project-crosswalk.json"),
                "record_count": 2175,
                "primary_id": "pantip_project_id",
                "classification": "CANONICAL_CANDIDATE",
            },
            {
                "name": "area_spatial_seed",
                "path": str(ROOT / "data_fixtures/area_engine/market_area_spatial_seed_v0.2.json"),
                "record_count": 43,
                "classification": "CANONICAL_CANDIDATE",
            },
            {
                "name": "zone_master",
                "path": str(ROOT / "data/zone_master.json"),
                "classification": "CANONICAL_CANDIDATE",
            },
            {
                "name": "transit_master",
                "path": str(ROOT / "data/transit_master.json"),
                "classification": "CANONICAL_CANDIDATE",
            },
            {
                "name": "properties_listings",
                "path": str(ROOT / "data/properties.json"),
                "classification": "PRODUCT_SPECIFIC",
            },
        ],
        "z3_modules": [
            "src/hub/shared_master/schema.py",
            "src/hub/shared_master/project_contract.py",
            "src/hub/shared_master/area_contract.py",
            "src/hub/shared_master/source_authority.py",
            "src/hub/shared_master/readiness.py",
        ],
    }


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rx = build_realxtate_inventory()
    pantip = build_pantip_inventory()
    policy = canonical_project_id_policy()
    matrix = build_field_readiness_matrix()
    summary = summarize_readiness(matrix)

    (OUTPUT_DIR / "realxtate-master-inventory.json").write_text(
        json.dumps(rx, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "pantip-master-inventory.json").write_text(
        json.dumps(pantip, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "canonical-id-policy.json").write_text(
        json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUTPUT_DIR / "readiness-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps({"policy": policy, "readiness_summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
