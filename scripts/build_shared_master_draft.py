#!/usr/bin/env python3
"""Build shared canonical master draft artifacts — Phase Z3."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.shared_master.area_contract import (  # noqa: E402
    build_owner_review_packet_pattanakarn,
    build_owner_review_packet_rama9,
    build_shared_area_master_draft,
)
from src.hub.shared_master.project_contract import build_cross_product_contract  # noqa: E402
from src.hub.shared_master.readiness import build_field_readiness_matrix, summarize_readiness  # noqa: E402

OUTPUT_DIR = Path("/tmp/pantip-phase-z3-shared-master")
FIXTURE_DIR = ROOT / "data_fixtures" / "shared_master"


def _hash_payload(obj: object) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    area_draft = build_shared_area_master_draft()
    area_hash = _hash_payload(area_draft)
    area_draft["content_hash"] = area_hash
    area_path = FIXTURE_DIR / "shared_area_master_v0.1.json"
    area_path.write_text(json.dumps(area_draft, ensure_ascii=False, indent=2), encoding="utf-8")

    contract = build_cross_product_contract()
    contract_summary = {
        "total": len(contract),
        "exact_id_match": sum(1 for r in contract if r["match_class"] == "EXACT_ID_MATCH"),
        "pantip_only": sum(1 for r in contract if r["match_class"] == "PANTIP_ONLY"),
        "canonical_identity_ready": sum(1 for r in contract if r["canonical_eligibility"] == "CANONICAL_IDENTITY_READY"),
        "rows": contract,
    }
    (OUTPUT_DIR / "project-cross-product-contract.json").write_text(
        json.dumps(contract_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    matrix = build_field_readiness_matrix()
    summary = summarize_readiness(matrix)
    readiness_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "projects": [r.to_dict() for r in matrix],
    }
    (OUTPUT_DIR / "project-field-readiness.json").write_text(
        json.dumps(readiness_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    (OUTPUT_DIR / "owner-packet-pattanakarn.json").write_text(
        json.dumps(build_owner_review_packet_pattanakarn(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUTPUT_DIR / "owner-packet-rama9.json").write_text(
        json.dumps(build_owner_review_packet_rama9(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manifest = {
        "shared_master_version": "v0.1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": {
            "shared_area_master_v0.1.json": str(area_path),
            "project-cross-product-contract.json": str(OUTPUT_DIR / "project-cross-product-contract.json"),
            "project-field-readiness.json": str(OUTPUT_DIR / "project-field-readiness.json"),
            "owner-packet-pattanakarn.json": str(OUTPUT_DIR / "owner-packet-pattanakarn.json"),
            "owner-packet-rama9.json": str(OUTPUT_DIR / "owner-packet-rama9.json"),
        },
        "content_hashes": {"shared_area_master": area_hash},
    }
    (OUTPUT_DIR / "build-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
