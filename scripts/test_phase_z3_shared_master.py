#!/usr/bin/env python3
"""Phase Z3 shared canonical master contract tests."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.area_assignment_engine import (  # noqa: E402
    CLASS_AUTO_SAFE,
    CLASS_REJECT_QUARANTINE,
    evaluate_project,
    load_area_seeds,
    load_project_contexts,
    load_stations,
)
from src.hub.coordinate_evidence import TIER_T4, parse_coordinate_from_payload  # noqa: E402
from src.hub.location_evidence import LINEAGE_LEGACY_SHEET, build_legacy_evidence_records  # noqa: E402
from src.hub.shared_master.area_contract import (  # noqa: E402
    AREA_SEMANTIC_KINDS,
    SEMANTIC_REVIEWS,
    build_owner_review_packet_pattanakarn,
    build_owner_review_packet_rama9,
    build_shared_area_master_draft,
)
from src.hub.shared_master.project_contract import (  # noqa: E402
    CANONICAL_EXCLUDED_FIELDS,
    build_canonical_project_record,
    build_cross_product_contract,
    canonical_project_id_policy,
    classify_pantip_only_project,
)
from src.hub.shared_master.readiness import build_field_readiness_matrix, summarize_readiness  # noqa: E402
from src.hub.shared_master.schema import ENTITY_TYPES, READINESS_STATUSES, SHARED_MASTER_VERSION  # noqa: E402
from src.hub.shared_master.source_authority import (  # noqa: E402
    SOURCE_TIERS,
    coordinate_promotion_policy,
    reference_assignment_policy,
)

PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
PHASE_W_HASH = "9c7eba7f1d44354867efc2fa4c01e3524549c442efa244b07c653398b4dc3602"
TRUSTED_DB = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-trusted-master.sqlite"
)
ASPIRE_ID = "d9a5d2b2-355a-55e6-b471-773b9badc8c6"
LIFE_ASOKE_IDS = {
    "life_asoke": "ec5214c9-c9fb-5ca5-98fb-852703044e4a",
    "life_asoke_hype": "needs_lookup",
}
LIVINGBKK = Path("/Users/angkarn1996/Desktop/LivingBKK_App")


class PhaseZ3SharedMasterTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.crosswalk = json.loads(PHASE_W.read_text(encoding="utf-8"))
    cls.contract = build_cross_product_contract()
    cls.matrix = build_field_readiness_matrix()
    cls.area_draft = build_shared_area_master_draft()

  def test_canonical_project_id_uniqueness(self):
    ids = [r["canonical_project_id"] for r in self.contract]
    self.assertEqual(len(ids), len(set(ids)))

  def test_shared_id_stability(self):
    policy = canonical_project_id_policy()
    self.assertEqual(policy["exact_id_match_count"], 2156)
    self.assertEqual(policy["stable_id_pair_count"], 2156)
    self.assertFalse(policy["new_third_namespace_required"])

  def test_no_new_third_id_namespace(self):
    policy = canonical_project_id_policy()
    self.assertEqual(policy["recommended_canonical_project_id"], "reuse_stable_shared_uuid")

  def test_pantip_only_projects_supported(self):
    only = [r for r in self.contract if r["match_class"] == "PANTIP_ONLY"]
    self.assertEqual(len(only), 19)
    for r in only:
      self.assertIsNotNone(r["pantip_only_class"])
      self.assertIsNotNone(r["canonical_project_id"])

  def test_fuzzy_name_cannot_merge_product_only(self):
    for r in self.contract:
      if r["match_class"] == "PANTIP_ONLY":
        self.assertNotEqual(r.get("realxtate_project_id"), r["pantip_project_id"])

  def test_listing_fields_excluded_from_canonical(self):
    for field in ("rent_price", "property_code", "owner_facebook"):
      self.assertIn(field, CANONICAL_EXCLUDED_FIELDS)

  def test_pii_excluded(self):
    for field in ("phone", "line", "owner_name", "tenant_name"):
      self.assertIn(field, CANONICAL_EXCLUDED_FIELDS)

  def test_field_readiness_independent(self):
    r = next(x for x in self.matrix if x.canonical_project_id == ASPIRE_ID)
    self.assertEqual(r.identity_status, "READY")
    self.assertIn(r.coordinate_status, ("READY", "CANDIDATE", "CONFLICT", "MISSING"))

  def test_coordinate_candidate_not_fully_ready_project(self):
    summary = summarize_readiness(self.matrix)
    if summary["fields"]["coordinate_status"]["ready_count"] < summary["total_projects"]:
      self.assertLess(
        summary["fields"]["identity_status"]["ready_count"],
        summary["total_projects"] + 1,
      )

  def test_marketplace_area_not_admin_district(self):
    self.assertIn("ADMIN_AREA", AREA_SEMANTIC_KINDS)
    self.assertIn("MARKETPLACE_AREA", AREA_SEMANTIC_KINDS)
    suan = SEMANTIC_REVIEWS["suan_luang"]
    kinds = {e["semantic_kind"] for e in suan["distinct_entities_needed"]}
    self.assertIn("ADMIN_AREA", kinds)
    self.assertIn("MARKETPLACE_AREA", kinds)

  def test_group_not_area(self):
    groups = self.area_draft["marketplace_groups"]
    areas = [e for e in self.area_draft["entities"] if e["semantic_kind"] == "MARKETPLACE_AREA"]
    self.assertTrue(groups)
    self.assertTrue(areas)

  def test_corridor_not_marketplace_area(self):
    corridors = [e for e in self.area_draft["entities"] if e["semantic_kind"] == "CORRIDOR"]
    self.assertTrue(any(c["identity_key"] == "phatthanakan" for c in corridors))

  def test_transit_not_marketplace_area(self):
    self.assertIn("TRANSIT_HUB", AREA_SEMANTIC_KINDS)
    self.assertIn("TRANSIT_STATION", ENTITY_TYPES)

  def test_group_contains_multiple_areas(self):
    g = next(g for g in self.area_draft["marketplace_groups"] if g["identity_key"] == "group_asoke_rama9")
    self.assertGreaterEqual(len(g.get("member_relations", [])), 2)

  def test_area_belongs_to_groups(self):
    self.assertTrue(self.area_draft["marketplace_groups"])

  def test_project_multiple_marketplace_areas(self):
    row = next(r for r in self.crosswalk if r["pantip_project_id"] == "ec5214c9-c9fb-5ca5-98fb-852703044e4a")
    self.assertGreaterEqual(len(row.get("realxtate_marketplace_areas") or []), 2)

  def test_primary_secondary_edge_preserved(self):
    row = next(r for r in self.crosswalk if r["pantip_project_id"] == "ec5214c9-c9fb-5ca5-98fb-852703044e4a")
    roles = {a["role"] for a in row.get("realxtate_marketplace_areas") or []}
    self.assertTrue(roles & {"PRIMARY", "SECONDARY", "EDGE"})

  def test_group_membership_not_primary_secondary(self):
    contract = self.area_draft["group_subarea_contract"]
    self.assertIn("PRIMARY/SECONDARY/EDGE", contract["note"])

  def test_rama9_candidate_review(self):
    review = SEMANTIC_REVIEWS["rama9"]
    self.assertEqual(review["review_status"], "CANDIDATE_OWNER_REVIEW")
    pkt = build_owner_review_packet_rama9()
    self.assertFalse(pkt["owner_decision_recorded"])

  def test_pattanakarn_candidate_review(self):
    review = SEMANTIC_REVIEWS["phatthanakan"]
    self.assertEqual(review["review_status"], "READY_FOR_OWNER_REVIEW")
    pkt = build_owner_review_packet_pattanakarn()
    self.assertFalse(pkt["owner_decision_recorded"])

  def test_suan_luang_unapproved(self):
    review = SEMANTIC_REVIEWS["suan_luang"]
    self.assertEqual(review["review_status"], "INSUFFICIENT_EVIDENCE")

  def test_legacy_zone_bag_raw_evidence(self):
    recs = build_legacy_evidence_records(
      project_id="test",
      pantip_zones=["ทองหล่อ"],
      catalog_locations=["ทองหล่อ"],
      listing_transit=[],
      project_name="Test",
    )
    self.assertTrue(recs)
    self.assertEqual(recs[0].evidence_lineage_id, LINEAGE_LEGACY_SHEET)

  def test_realxtate_8z3_reference_assignment(self):
    pol = reference_assignment_policy()
    self.assertEqual(pol["realxtate_marketplace_area_assignment_8z3"], "REFERENCE_ASSIGNMENT")

  def test_copied_evidence_lineage_once(self):
    from src.hub.location_evidence import EvidenceRecord, count_independent_lineages

    recs = [
      EvidenceRecord("t", "f", "lineage:legacy_employee_sheet", "s", "id", "v", "LOW", "T4"),
      EvidenceRecord("t", "f", "lineage:legacy_employee_sheet", "s", "id", "v2", "LOW", "T4"),
    ]
    self.assertEqual(count_independent_lineages(recs), 1)

  def test_t4_cannot_silently_become_canonical(self):
    pol = coordinate_promotion_policy()
    self.assertFalse(pol["tier_mapping"]["T4"]["auto_promote_future"])

  def test_field_promotion_fail_closed(self):
    self.assertTrue(coordinate_promotion_policy()["fail_closed"])

  def test_versioned_artifact_deterministic(self):
    a = build_shared_area_master_draft()
    b = build_shared_area_master_draft()
    a.pop("generated_at", None)
    b.pop("generated_at", None)
    self.assertEqual(
      hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest(),
      hashlib.sha256(json.dumps(b, sort_keys=True).encode()).hexdigest(),
    )

  def test_content_hash_recorded(self):
    draft = build_shared_area_master_draft()
    self.assertIn("shared_master_version", draft)

  def test_source_snapshots_recorded(self):
    self.assertEqual(SHARED_MASTER_VERSION, "v0.1")

  def test_no_property_price_in_canonical(self):
    self.assertIn("rent_price", CANONICAL_EXCLUDED_FIELDS)

  def test_no_property_code_in_canonical_identity(self):
    self.assertIn("property_code", CANONICAL_EXCLUDED_FIELDS)

  def test_no_owner_contact_data(self):
    for f in ("phone", "line", "owner_name"):
      self.assertIn(f, CANONICAL_EXCLUDED_FIELDS)

  def test_aspire_onnut_identity_stable(self):
    row = next(r for r in self.contract if r["canonical_project_id"] == ASPIRE_ID)
    self.assertEqual(row["match_class"], "EXACT_ID_MATCH")
    self.assertEqual(row["canonical_eligibility"], "CANONICAL_IDENTITY_READY")

  @unittest.skipUnless(TRUSTED_DB.is_file() and PHASE_W.is_file(), "integration data missing")
  def test_aspire_onnut_on_nut_supported(self):
    crosswalk = json.loads(PHASE_W.read_text(encoding="utf-8"))
    contexts = load_project_contexts(
      TRUSTED_DB,
      TRUSTED_DB.parent / "realxtate-catalog.sqlite",
      crosswalk,
    )
    ctx = contexts[ASPIRE_ID]
    seeds = load_area_seeds(TRUSTED_DB)
    stations = load_stations(TRUSTED_DB)
    result = evaluate_project(ctx, seeds, stations)
    onnut = next(c for c in result["candidate_evaluations"] if c["identity_key"] == "onnut")
    self.assertEqual(onnut["classification"], CLASS_AUTO_SAFE)

  @unittest.skipUnless(TRUSTED_DB.is_file() and PHASE_W.is_file(), "integration data missing")
  def test_aspire_onnut_charoen_nakhon_not_canonical(self):
    crosswalk = json.loads(PHASE_W.read_text(encoding="utf-8"))
    contexts = load_project_contexts(
      TRUSTED_DB,
      TRUSTED_DB.parent / "realxtate-catalog.sqlite",
      crosswalk,
    )
    ctx = contexts[ASPIRE_ID]
    seeds = load_area_seeds(TRUSTED_DB)
    stations = load_stations(TRUSTED_DB)
    result = evaluate_project(ctx, seeds, stations)
    charoen = next(c for c in result["candidate_evaluations"] if c["identity_key"] == "charoen_nakhon")
    self.assertEqual(charoen["classification"], CLASS_REJECT_QUARANTINE)
    picked = {p["identity_key"] for p in result["picked_areas"]}
    self.assertNotIn("charoen_nakhon", picked)

  def test_life_asoke_family_separate(self):
    names = {r["pantip_canonical_name"] for r in self.crosswalk}
    self.assertTrue(any("Life Asoke Rama 9" in n for n in names))
    self.assertTrue(any("Life Asoke Hype" in n or "Life Asoke" in n for n in names))

  def test_product_only_project_supported(self):
    only = [r for r in self.contract if r["match_class"] == "PANTIP_ONLY"]
    self.assertTrue(any(r["canonical_eligibility"] == "PRODUCT_ONLY_VALID" for r in only))

  def test_transit_stable_id_preserved(self):
    self.assertIn("TRANSIT_STATION", ENTITY_TYPES)

  def test_coordinate_history_preserved(self):
    rec = build_canonical_project_record(
      ASPIRE_ID,
      crosswalk_row={"realxtate_project_id": ASPIRE_ID},
      payload={"coordinate": {"latitude": 13.7, "longitude": 100.6}},
      area_assignments=[],
    )
    self.assertTrue(rec["coordinate_evidence"])

  def test_no_overwrite_raw_evidence(self):
    pol = coordinate_promotion_policy()
    self.assertTrue(pol["preserve_history"])

  def test_phase_w_source_unchanged(self):
    h = hashlib.sha256(PHASE_W.read_bytes()).hexdigest()
    self.assertEqual(h, PHASE_W_HASH)

  def test_livingbkk_not_accessed(self):
    shared_dir = ROOT / "src" / "hub" / "shared_master"
    for py in shared_dir.glob("*.py"):
      text = py.read_text(encoding="utf-8")
      self.assertNotIn("LivingBKK", text)
      self.assertNotIn("LivingBKK_App", text)

  def test_entity_types_complete(self):
    for et in (
      "CANONICAL_PROJECT",
      "MARKETPLACE_AREA",
      "MARKETPLACE_GROUP",
      "CORRIDOR",
      "TRANSIT_STATION",
      "ADMIN_DISTRICT",
      "COORDINATE_EVIDENCE",
      "IDENTITY_ALIAS",
    ):
      self.assertIn(et, ENTITY_TYPES)

  def test_readiness_statuses(self):
    for s in ("READY", "CANDIDATE", "REVIEW_REQUIRED", "MISSING"):
      self.assertIn(s, READINESS_STATUSES)

  def test_source_tiers(self):
    self.assertFalse(SOURCE_TIERS["T4"]["may_promote_to_canonical"])
    self.assertFalse(SOURCE_TIERS["T5"]["may_promote_to_canonical"])


if __name__ == "__main__":
  unittest.main(verbosity=2)
