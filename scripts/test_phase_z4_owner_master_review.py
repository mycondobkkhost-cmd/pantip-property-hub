#!/usr/bin/env python3
"""Phase Z4 owner master definition review + lifecycle roadmap tests."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.master_definition_review import build_all_packets_v2  # noqa: E402
from src.hub.shared_master.area_contract import SEMANTIC_REVIEWS  # noqa: E402
from src.hub.shared_master.identity_accounting import (  # noqa: E402
    IDENTITY_BUCKETS,
    build_identity_accounting,
)
from src.hub.shared_master.lifecycle_contract import (  # noqa: E402
    CANONICAL_PROJECT_EXCLUDED_OPERATIONAL,
    IMPLEMENTATION_SEQUENCE,
    LISTING_FRESHNESS_STATES,
    NOTIFICATION_EVENT_TYPES,
    VACANCY_STATES,
    VIEWING_RESPONSES,
)
from src.hub.shared_master.marketplace_group_reconciliation import (  # noqa: E402
    REALXTATE_MARKETPLACE_GROUPS,
    build_group_reconciliation,
    marketplace_groups_for_shared_draft,
)
from src.hub.shared_master.project_contract import CANONICAL_EXCLUDED_FIELDS  # noqa: E402
from src.hub.shared_master.readiness import build_field_readiness_matrix, summarize_readiness  # noqa: E402

PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
PHASE_W_HASH = "9c7eba7f1d44354867efc2fa4c01e3524549c442efa244b07c653398b4dc3602"
LIVINGBKK = Path("/Users/angkarn1996/Desktop/LivingBKK_App")


class PhaseZ4TrackATests(unittest.TestCase):
    def test_identity_accounting_reconciles_2175(self):
        acct = build_identity_accounting()
        self.assertEqual(acct["total_live"], 2175)
        self.assertTrue(acct["equation_balanced"])
        self.assertEqual(sum(acct["buckets"].values()), 2175)

    def test_canonical_shared_identity_ready_unambiguous(self):
        acct = build_identity_accounting()
        self.assertEqual(acct["SHARED_CANONICAL_IDENTITY_READY"], 2128)

    def test_product_only_counted_separately(self):
        acct = build_identity_accounting()
        self.assertEqual(acct["PRODUCT_ONLY_IDENTITY_READY"], 3)

    def test_identity_categories_no_overlap(self):
        acct = build_identity_accounting()
        buckets = {p["identity_bucket"] for p in acct["projects"]}
        self.assertTrue(buckets.issubset(IDENTITY_BUCKETS))
        self.assertEqual(len(acct["projects"]), 2175)

    def test_all_7_realxtate_groups_accounted(self):
        recon = build_group_reconciliation()
        self.assertEqual(recon["realxtate_total"], 7)
        self.assertEqual(len(REALXTATE_MARKETPLACE_GROUPS), 7)

    def test_no_group_silently_omitted(self):
        recon = build_group_reconciliation()
        ids = {g["group_id"] for g in recon["groups"]}
        expected = {
            "group_central_sukhumvit",
            "group_inner_sukhumvit",
            "group_outer_sukhumvit",
            "group_asoke_rama9",
            "group_ratchada",
            "group_north_phaholyothin",
            "group_sathon_silom",
        }
        self.assertEqual(ids, expected)

    def test_shared_draft_has_7_groups(self):
        groups = marketplace_groups_for_shared_draft()
        self.assertEqual(len(groups), 7)

    def test_pattanakarn_unapproved(self):
        pkt = build_all_packets_v2()["phatthanakan"]
        self.assertEqual(pkt["status"], "REVIEW_REQUIRED")
        self.assertFalse(pkt["owner_decision_recorded"])

    def test_rama9_unapproved(self):
        pkt = build_all_packets_v2()["rama9"]
        self.assertEqual(pkt["status"], "REVIEW_REQUIRED")
        self.assertFalse(pkt["owner_decision_recorded"])

    def test_suan_luang_insufficient(self):
        self.assertEqual(SEMANTIC_REVIEWS["suan_luang"]["review_status"], "INSUFFICIENT_EVIDENCE")

    def test_corridor_not_marketplace_area(self):
        pkt = build_all_packets_v2()["rama9"]
        kinds = {c["semantic_kind"] for c in pkt["verified_children"]}
        self.assertIn("CORRIDOR", kinds)
        self.assertIn("MARKETPLACE_AREA", kinds)

    def test_readiness_identity_fixed(self):
        matrix = build_field_readiness_matrix()
        summary = summarize_readiness(matrix)
        ready = summary["fields"]["identity_status"]["counts"].get("READY", 0)
        self.assertEqual(ready, 2128)


class PhaseZ4TrackBTests(unittest.TestCase):
    def test_operational_excluded_from_canonical(self):
        for f in ("listing_verification_status", "last_owner_verified_at", "lease_end"):
            self.assertIn(f, CANONICAL_PROJECT_EXCLUDED_OPERATIONAL)

    def test_customer_profile_excluded(self):
        self.assertIn("customer_profile", CANONICAL_PROJECT_EXCLUDED_OPERATIONAL)

    def test_lease_dates_excluded(self):
        self.assertIn("lease_start", CANONICAL_PROJECT_EXCLUDED_OPERATIONAL)

    def test_listing_freshness_excluded(self):
        self.assertIn("listing_freshness_state", CANONICAL_PROJECT_EXCLUDED_OPERATIONAL)

    def test_viewing_excluded(self):
        self.assertIn("viewing_request_id", CANONICAL_PROJECT_EXCLUDED_OPERATIONAL)

    def test_property_not_canonical_project(self):
        self.assertNotIn("property_id", CANONICAL_EXCLUDED_FIELDS)
        self.assertIn("property_code", CANONICAL_EXCLUDED_FIELDS)

    def test_notification_events_operational(self):
        self.assertIn("VIEWING_REQUEST_CREATED", NOTIFICATION_EVENT_TYPES)

    def test_vacancy_not_from_time_alone(self):
        self.assertIn("POSSIBLE_UPCOMING_VACANCY", VACANCY_STATES)
        self.assertIn("UPCOMING_VACANCY_CONFIRMED", VACANCY_STATES)

    def test_freshness_states_defined(self):
        self.assertIn("VERIFIED_AVAILABLE", LISTING_FRESHNESS_STATES)
        self.assertIn("STALE_UNCONFIRMED", LISTING_FRESHNESS_STATES)

    def test_viewing_responses_defined(self):
        self.assertIn("PROPOSE_ALTERNATIVE_TIME", VIEWING_RESPONSES)

    def test_implementation_sequence(self):
        self.assertGreaterEqual(len(IMPLEMENTATION_SEQUENCE), 5)

    def test_lifecycle_docs_exist(self):
        docs = [
            "SHARED-PROPERTY-LIFECYCLE-ROADMAP-v0.1.md",
            "LISTING-FRESHNESS-AND-RENEWAL-CONTRACT-v0.1.md",
            "VIEWING-REQUEST-CONTRACT-v0.1.md",
            "LEASE-OPPORTUNITY-CONTRACT-v0.1.md",
            "NOTIFICATION-EVENT-CONTRACT-v0.1.md",
        ]
        for d in docs:
            self.assertTrue((ROOT / "docs" / d).is_file(), d)

    def test_phase_w_unchanged(self):
        self.assertEqual(hashlib.sha256(PHASE_W.read_bytes()).hexdigest(), PHASE_W_HASH)

    def test_livingbkk_not_accessed(self):
        for py in (ROOT / "src/hub").rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            self.assertNotIn("LivingBKK_App", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
