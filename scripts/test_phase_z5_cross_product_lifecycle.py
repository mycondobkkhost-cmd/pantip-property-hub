#!/usr/bin/env python3
"""Phase Z5 cross-product lifecycle + lease opportunity foundation tests."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.cross_product_sync import (  # noqa: E402
    build_cross_product_capability_diff,
    build_realxtate_current_state,
    discover_realxtate_capabilities,
    write_sync_artifacts,
)
from src.hub.lease_opportunity import (  # noqa: E402
    LOCAL_DIR,
    audit_rental_data_coverage,
    classify_lease_evidence,
    list_contact_events,
    list_opportunities,
    record_contact_event,
    seed_test_fixtures,
    upsert_opportunity,
    vacancy_safety_status,
)
from src.hub.shared_master.area_contract import SEMANTIC_REVIEWS  # noqa: E402
from src.hub.notification_center import (  # noqa: E402
    OTP_IS_NOT_NOTIFICATION,
    create_notification_event,
    list_notification_events,
    mark_dismissed,
    mark_read,
    sync_notifications_from_opportunities,
)
from src.hub.operational_contracts import (  # noqa: E402
    LISTING_CYCLE_CONTRACT,
    LISTING_FRESHNESS_CONTRACT,
    LISTING_IDENTITY_CONTRACT,
    PROPERTY_IDENTITY_CONTRACT,
    SHARED_MASTER_EXCLUDES_OPERATIONAL,
    SOURCE_PROVENANCE_CONTRACT,
)
from src.hub.shared_master.lifecycle_contract import CANONICAL_PROJECT_EXCLUDED_OPERATIONAL  # noqa: E402

PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
PHASE_W_HASH = "9c7eba7f1d44354867efc2fa4c01e3524549c442efa244b07c653398b4dc3602"
REALXTATE = Path("/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP")
PROJECTS = ROOT / "data" / "projects.json"
PROPERTIES = ROOT / "data" / "properties.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhaseZ5CrossProductTests(unittest.TestCase):
    def setUp(self) -> None:
        if LOCAL_DIR.exists():
            shutil.rmtree(LOCAL_DIR)

    @classmethod
    def setUpClass(cls) -> None:
        cls._projects_hash = _sha(PROJECTS)
        cls._properties_hash = _sha(PROPERTIES)
        cls._rx_head_before = subprocess.check_output(
            ["git", "-C", str(REALXTATE), "rev-parse", "HEAD"], text=True
        ).strip()
        cls._rx_status_before = subprocess.check_output(
            ["git", "-C", str(REALXTATE), "status", "--short"], text=True
        )

    def test_01_realxtate_inventory_deterministic(self):
        a = build_realxtate_current_state()
        b = build_realxtate_current_state()
        self.assertEqual(a["head_sha"], b["head_sha"])
        self.assertEqual(a["capabilities"], b["capabilities"])

    def test_02_realxtate_read_only(self):
        head_after = subprocess.check_output(
            ["git", "-C", str(REALXTATE), "rev-parse", "HEAD"], text=True
        ).strip()
        self.assertEqual(head_after, self._rx_head_before)

    def test_03_cross_product_diff_deterministic(self):
        a = build_cross_product_capability_diff()
        b = build_cross_product_capability_diff()
        self.assertEqual(a["rows"], b["rows"])

    def test_04_shared_master_excludes_operational(self):
        for f in ("lease_start", "lease_end", "notification_history", "customer_profile"):
            self.assertIn(f, CANONICAL_PROJECT_EXCLUDED_OPERATIONAL)
        self.assertIn("listing_freshness", SHARED_MASTER_EXCLUDES_OPERATIONAL)

    def test_05_source_record_not_property(self):
        self.assertIn("canonical_property_id", SOURCE_PROVENANCE_CONTRACT["fields"])
        self.assertIn("source_record != canonical property", SOURCE_PROVENANCE_CONTRACT["rule"])

    def test_06_provenance_unlinked(self):
        self.assertIn("UNLINKED", SOURCE_PROVENANCE_CONTRACT["mapping_statuses"])

    def test_07_provenance_rejected(self):
        self.assertIn("REJECTED", SOURCE_PROVENANCE_CONTRACT["mapping_statuses"])

    def test_08_source_idempotency(self):
        self.assertEqual(SOURCE_PROVENANCE_CONTRACT["idempotency_key"], "(source_system, source_listing_id)")

    def test_09_property_id_not_listing_id(self):
        self.assertNotEqual(
            PROPERTY_IDENTITY_CONTRACT["mutation_identity"],
            LISTING_IDENTITY_CONTRACT["mutation_identity"],
        )

    def test_10_property_id_not_listing_cycle(self):
        self.assertIn("listing_cycle_id", LISTING_CYCLE_CONTRACT["fields"])
        self.assertEqual(PROPERTY_IDENTITY_CONTRACT["mutation_identity"], "property_id")

    def test_11_listing_belongs_to_cycle(self):
        self.assertIn("listing_id != property_id", LISTING_IDENTITY_CONTRACT["rule"])

    def test_12_multiple_listing_cycles(self):
        self.assertIn("many listing cycles", LISTING_CYCLE_CONTRACT["rule"])

    def test_13_opportunity_requires_property_id(self):
        with self.assertRaises(ValueError):
            upsert_opportunity(listing_cycle_id="c1")

    def test_14_property_code_not_mutation_identity(self):
        self.assertIn("property_code", PROPERTY_IDENTITY_CONTRACT["excluded_from_mutation"])

    def test_15_explicit_lease_end_strong(self):
        c = classify_lease_evidence(contract_end="2026-12-31")
        self.assertEqual(c["evidence_class"], "CONFIRMED_LEASE_END")
        self.assertTrue(c["strong"])

    def test_16_start_term_derivation_strong(self):
        c = classify_lease_evidence(contract_start="2025-01-01", term_months=12)
        self.assertEqual(c["evidence_class"], "DERIVED_FROM_EXPLICIT_TERM")
        self.assertTrue(c["strong"])

    def test_17_start_only_no_invented_term(self):
        c = classify_lease_evidence(contract_start="2025-01-01")
        self.assertEqual(c["evidence_class"], "INSUFFICIENT_EVIDENCE")

    def test_18_deal_date_not_confirmed_end(self):
        c = classify_lease_evidence(deal_date="2025-06-01")
        self.assertIn(c["evidence_class"], {"ESTIMATED_12M_CANDIDATE", "DEAL_DATE_ONLY_CANDIDATE"})
        self.assertFalse(c.get("strong"))

    def test_19_estimated_12m_remains_estimated(self):
        c = classify_lease_evidence(deal_date="2024-01-01")
        self.assertEqual(c["evidence_class"], "ESTIMATED_12M_CANDIDATE")
        self.assertIn("disclaimer_th", c)

    def test_20_elapsed_time_never_available(self):
        self.assertNotEqual(vacancy_safety_status(evidence_class="CONFIRMED_LEASE_END"), "AVAILABLE")

    def test_21_owner_confirmation_only_confirmed_vacancy(self):
        self.assertEqual(
            vacancy_safety_status(evidence_class="CONFIRMED_LEASE_END", owner_confirmed=True),
            "OWNER_CONFIRMED_VACANT_SOON",
        )

    def test_22_follow_up_windows_configurable(self):
        from src.hub.lease_opportunity import load_config, save_config

        save_config(follow_up_windows_days=[90, 60, 30])
        self.assertEqual(load_config()["follow_up_windows_days"], [90, 60, 30])

    def test_23_opportunity_dedupe(self):
        a = upsert_opportunity(property_id="dedupe_prop", listing_cycle_id="cyc1", property_code_display="D1")
        b = upsert_opportunity(property_id="dedupe_prop", listing_cycle_id="cyc1", opportunity_status="FOLLOW_UP_DUE")
        self.assertEqual(a["opportunity_id"], b["opportunity_id"])

    def test_24_append_only_contact_history(self):
        opp = upsert_opportunity(property_id="hist_prop", listing_cycle_id="h1")
        record_contact_event(opportunity_id=opp["opportunity_id"], actor="test", result="WAITING_FOR_OWNER")
        record_contact_event(opportunity_id=opp["opportunity_id"], actor="test", result="CONTACT_FAILED")
        self.assertEqual(len(list_contact_events(opp["opportunity_id"])), 2)

    def test_25_notification_dedupe(self):
        e1 = create_notification_event(
            event_type="FOLLOW_UP_DUE_TODAY",
            recipient_user_id="u1",
            related_entity_type="lease_opportunity",
            related_entity_id="x1",
            dedupe_key="dup::x1",
        )
        e2 = create_notification_event(
            event_type="FOLLOW_UP_DUE_TODAY",
            recipient_user_id="u1",
            related_entity_type="lease_opportunity",
            related_entity_id="x1",
            dedupe_key="dup::x1",
        )
        self.assertIsNotNone(e1)
        self.assertIsNone(e2)

    def test_26_notification_read_dismiss_independent(self):
        evt = create_notification_event(
            event_type="LEASE_END_WITHIN_30_DAYS",
            recipient_user_id="u2",
            related_entity_type="lease_opportunity",
            related_entity_id="x2",
            dedupe_key="read::x2",
        )
        assert evt
        read = mark_read(evt["notification_event_id"])
        dismissed = mark_dismissed(evt["notification_event_id"])
        self.assertTrue(read.get("read_at"))
        self.assertTrue(dismissed.get("dismissed_at"))

    def test_27_web_channel_separate_from_event(self):
        evt = create_notification_event(
            event_type="FOLLOW_UP_OVERDUE",
            recipient_user_id="u3",
            related_entity_type="lease_opportunity",
            related_entity_id="x3",
            dedupe_key="ch::x3-unique",
            delivery_channel="HUB_NOTIFICATION",
        )
        self.assertIsNotNone(evt)
        self.assertEqual(evt["delivery_channel"], "HUB_NOTIFICATION")

    def test_28_otp_not_notification(self):
        self.assertTrue(OTP_IS_NOT_NOTIFICATION)

    def test_29_customer_profile_excluded_shared_master(self):
        self.assertIn("customer_profile", SHARED_MASTER_EXCLUDES_OPERATIONAL)

    def test_30_viewing_excluded_shared_master(self):
        self.assertIn("viewing", SHARED_MASTER_EXCLUDES_OPERATIONAL)

    def test_31_freshness_separate_from_bump(self):
        self.assertIn("LISTING_BUMPED", LISTING_FRESHNESS_CONTRACT["events"])
        self.assertTrue(LISTING_FRESHNESS_CONTRACT["bump_separate"])

    def test_32_pattanakarn_unchanged(self):
        r = SEMANTIC_REVIEWS["phatthanakan"]
        self.assertFalse(r.get("owner_decision_recorded"))
        self.assertIn(r.get("review_status"), {"READY_FOR_OWNER_REVIEW", "REVIEW_REQUIRED"})

    def test_33_rama9_unchanged(self):
        r = SEMANTIC_REVIEWS["rama9"]
        self.assertFalse(r.get("owner_decision_recorded"))

    def test_34_suan_luang_deferred(self):
        self.assertEqual(SEMANTIC_REVIEWS["suan_luang"]["review_status"], "INSUFFICIENT_EVIDENCE")

    def test_35_no_owner_decision_during_qa(self):
        for key in ("phatthanakan", "rama9"):
            self.assertFalse(SEMANTIC_REVIEWS[key].get("owner_decision_recorded"))

    def test_36_no_production_lease_writes(self):
        self.assertTrue(str(LOCAL_DIR).endswith("lease_opportunity_phase_z5"))

    def test_37_no_production_notification_writes(self):
        from src.hub.notification_center import EVENTS_PATH

        self.assertTrue(str(EVENTS_PATH).startswith(str(LOCAL_DIR)))

    def test_38_projects_json_unchanged(self):
        self.assertEqual(_sha(PROJECTS), self._projects_hash)

    def test_39_properties_json_unchanged(self):
        self.assertEqual(_sha(PROPERTIES), self._properties_hash)

    def test_40_phase_w_unchanged(self):
        self.assertTrue(PHASE_W.is_file())
        self.assertEqual(_sha(PHASE_W), PHASE_W_HASH)

    def test_41_realxtate_unchanged_post_tests(self):
        head = subprocess.check_output(["git", "-C", str(REALXTATE), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(head, self._rx_head_before)

    def test_42_livingbkk_not_accessed(self):
        z5_sources = [
            ROOT / "src/hub/cross_product_sync.py",
            ROOT / "src/hub/lease_opportunity.py",
            ROOT / "src/hub/notification_center.py",
        ]
        for p in z5_sources:
            self.assertNotIn("LivingBKK_App", p.read_text())

    def test_43_no_deploy_marker(self):
        self.assertFalse((ROOT / ".deployed").exists())

    def test_artifacts_written(self):
        paths = write_sync_artifacts()
        self.assertTrue(Path(paths["state_path"]).is_file())
        self.assertTrue(Path(paths["diff_path"]).is_file())

    def test_data_coverage_audit(self):
        cov = audit_rental_data_coverage()
        self.assertIn("RENTAL_PROPERTIES_TOTAL", cov)
        self.assertGreater(cov["RENTAL_PROPERTIES_TOTAL"], 0)

    def test_fixtures_seed(self):
        items = seed_test_fixtures()
        self.assertGreaterEqual(len(items), 6)
        created = sync_notifications_from_opportunities(recipient_user_id="qa_user")
        self.assertIsInstance(created, list)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
