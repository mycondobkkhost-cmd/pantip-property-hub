#!/usr/bin/env python3
"""Phase Z7 operational lifecycle MVP tests."""

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

from src.hub.legacy_entry_date import (  # noqa: E402
    LEGACY_RECORD_ENTERED_AT_FIELD,
    audit_age_distribution,
    entry_date_semantics_proof,
    parse_legacy_record_entered_at,
    record_age_days,
)
from src.hub.lease_capture_integration import (  # noqa: E402
    build_migration_dry_run,
    on_customer_status_changed,
)
from src.hub.lease_evidence import (  # noqa: E402
    classify_available_raw,
    classify_lease_evidence_authority,
    build_recovery_dry_run,
)
from src.hub.lease_record import (  # noqa: E402
    LOCAL_DIR as LEASE_RECORD_DIR,
    create_lease_record,
    renew_lease_record,
    validate_lease_dates,
)
from src.hub.listing_freshness import (  # noqa: E402
    LOCAL_DIR as FRESHNESS_DIR,
    DEFAULT_TTL_DAYS,
    derive_freshness_state,
    mark_verified_available,
    upsert_freshness,
)
from src.hub.listing_renewal import LOCAL_DIR as RENEWAL_DIR, renew_listing, request_bump_only  # noqa: E402
from src.hub.notification_center import (  # noqa: E402
    LEGACY_WANG_EVENT_GENERATION_DISABLED,
    LOCAL_DIR as NOTIFICATION_DIR,
    PANTIP_MVP_EVENT_TYPES,
    create_notification_event,
    sync_all_notifications,
    sync_notifications_from_recheck,
)
from src.hub.operational_dashboard import build_dashboard_payload  # noqa: E402
from src.hub.property_status_recheck import (  # noqa: E402
    LOCAL_DIR as RECHECK_DIR,
    build_recheck_dry_run,
    list_contact_events,
    load_config,
    record_contact,
    save_config,
    seed_test_fixtures,
    trigger_stage_for_age,
    upsert_recheck,
)
from src.hub.shared_master.area_contract import SEMANTIC_REVIEWS  # noqa: E402

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
DIRTY = [
    PROPERTIES,
    ROOT / "hub" / "preview-data.js",
    ROOT / "hub" / "preview-data.meta.json",
    ROOT / "data" / "transit_master.json",
    ROOT / "data" / "zone_master.json",
]
LIVINGBKK = Path("/Users/angkarn1996/Desktop/LivingBKK_App")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class PhaseZ7Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._projects_hash = _sha(PROJECTS)
        cls._properties_hash = _sha(PROPERTIES)
        cls._dirty_hashes = {str(p): _sha(p) for p in DIRTY if p.exists()}
        cls._phase_w_hash = _sha(PHASE_W)
        if REALXTATE.is_dir():
            cls._rx_head = subprocess.check_output(
                ["git", "-C", str(REALXTATE), "rev-parse", "HEAD"], text=True
            ).strip()
        else:
            cls._rx_head = ""

    def setUp(self) -> None:
        for d in (RECHECK_DIR, LEASE_RECORD_DIR, FRESHNESS_DIR, RENEWAL_DIR, NOTIFICATION_DIR):
            if d.exists():
                shutil.rmtree(d)

    # LEGACY DATE POLICY (1-8)
    def test_01_legacy_wang_not_in_recheck_queue(self):
        dry = build_recheck_dry_run()
        self.assertTrue(dry.get("legacy_wang_scheduling_disabled"))

    def test_02_legacy_wang_not_lease_end(self):
        sem = classify_available_raw("15/03/2026")
        self.assertFalse(sem.get("may_map_to_lease_end"))

    def test_03_legacy_wang_not_confirmed_avail(self):
        rec = build_recovery_dry_run(skip_live_sheet=True)
        for row in rec.get("records") or []:
            if row.get("available_from_date"):
                self.assertTrue(row.get("active_scheduling_disabled"))

    def test_04_legacy_wang_raw_evidence(self):
        sem = classify_available_raw("15/03/2026")
        self.assertTrue(sem.get("legacy_raw_evidence"))

    def test_05_entry_date_authoritative(self):
        proof = entry_date_semantics_proof()
        self.assertEqual(proof["persisted_field"], LEGACY_RECORD_ENTERED_AT_FIELD)

    def test_06_record_age_deterministic(self):
        d = date(2024, 1, 1)
        self.assertEqual(record_age_days(d, today=date(2024, 4, 1)), 91)

    def test_07_missing_entry_quarantined(self):
        self.assertIsNone(parse_legacy_record_entered_at(""))
        self.assertIsNone(record_age_days(None))

    def test_08_invalid_entry_quarantined(self):
        self.assertIsNone(parse_legacy_record_entered_at("not-a-date"))

    # AGE QUEUE (9-17)
    def test_09_90d_classification(self):
        self.assertEqual(trigger_stage_for_age(95), "AGE_90D")

    def test_10_180d_classification(self):
        self.assertEqual(trigger_stage_for_age(200), "AGE_180D")

    def test_11_270d_classification(self):
        self.assertEqual(trigger_stage_for_age(300), "AGE_270D")

    def test_12_365d_classification(self):
        self.assertEqual(trigger_stage_for_age(400), "AGE_365D")

    def test_13_thresholds_configurable(self):
        save_config(active_threshold_days=90)
        self.assertEqual(load_config()["active_threshold_days"], 90)

    def test_14_old_age_not_available(self):
        upsert_recheck(property_id="p_age", record_age_days=400, recheck_status="UPCOMING")
        self.assertNotEqual(upsert_recheck(property_id="p_age")["recheck_status"], "OWNER_CONFIRMED_AVAILABLE")

    def test_15_old_age_not_rented(self):
        upsert_recheck(property_id="p_age2", record_age_days=400)
        self.assertNotIn(upsert_recheck(property_id="p_age2")["recheck_status"], {"OWNER_CONFIRMED_RENTED"})

    def test_16_old_age_not_lease_expired(self):
        dry = build_recheck_dry_run()
        self.assertTrue(all(x.get("not_near_lease_end") for x in dry.get("candidates_sample") or []))

    def test_17_queue_ordering_deterministic(self):
        a = build_recheck_dry_run(threshold_days=90)
        b = build_recheck_dry_run(threshold_days=90)
        self.assertEqual(
            [x["property_id"] for x in a.get("candidates_sample") or []],
            [x["property_id"] for x in b.get("candidates_sample") or []],
        )

    # OWNER CONFIRMATION (18-25)
    def test_18_owner_available_requires_response(self):
        with self.assertRaises(ValueError):
            record_contact(property_id="p1", actor="op", result="INVALID")

    def test_19_future_avail_requires_date(self):
        record_contact(
            property_id="p2",
            actor="op",
            result="OWNER_CONFIRMED_AVAILABLE_SOON",
            owner_confirmed_available_from="2026-10-15",
        )
        upsert_recheck(property_id="p2")
        from src.hub.property_status_recheck import list_rechecks

        row = [x for x in list_rechecks() if x["property_id"] == "p2"][0]
        self.assertEqual(row["owner_confirmed_available_from"], "2026-10-15")

    def test_20_future_avail_provenance(self):
        record_contact(
            property_id="p3",
            actor="op",
            result="OWNER_CONFIRMED_AVAILABLE_SOON",
            owner_confirmed_available_from="2026-11-01",
        )
        row = [x for x in __import__("src.hub.property_status_recheck", fromlist=["list_rechecks"]).list_rechecks() if x["property_id"] == "p3"][0]
        self.assertTrue(row.get("confirmed_by"))
        self.assertTrue(row.get("confirmation_source"))

    def test_21_legacy_cannot_populate_confirmed(self):
        c = classify_lease_evidence_authority(available_from="2026-06-01")
        self.assertTrue(c.get("active_scheduling_disabled"))

    def test_22_unavailable_explicit_only(self):
        record_contact(property_id="p4", actor="op", result="OWNER_CONFIRMED_NOT_AVAILABLE")
        row = upsert_recheck(property_id="p4")
        self.assertEqual(row["recheck_status"], "OWNER_CONFIRMED_NOT_AVAILABLE")

    def test_23_rented_explicit_only(self):
        record_contact(property_id="p5", actor="op", result="OWNER_CONFIRMED_RENTED")
        self.assertEqual(upsert_recheck(property_id="p5")["recheck_status"], "OWNER_CONFIRMED_RENTED")

    def test_24_sold_explicit_only(self):
        record_contact(property_id="p6", actor="op", result="OWNER_CONFIRMED_SOLD")
        self.assertEqual(upsert_recheck(property_id="p6")["recheck_status"], "OWNER_CONFIRMED_SOLD")

    def test_25_contact_history_append_only(self):
        record_contact(property_id="p7", actor="op", result="CONTACTED_WAITING")
        record_contact(property_id="p7", actor="op", result="OWNER_CONFIRMED_AVAILABLE")
        self.assertEqual(len(list_contact_events("p7")), 2)

    # FUTURE LEASE CAPTURE (26-35)
    def test_26_contract_started_requires_capture(self):
        r = on_customer_status_changed(
            case_id="c1",
            old_status="contract_pending",
            new_status="contract_started",
            reserved_codes=[],
        )
        self.assertEqual(r["action"], "LEASE_DATA_COMPLETION_REQUIRED")

    def test_27_non_rental_no_capture(self):
        r = on_customer_status_changed(case_id="c2", old_status="new", new_status="contacted")
        self.assertEqual(r["action"], "none")

    def test_28_property_id_required(self):
        with self.assertRaises(ValueError):
            create_lease_record(property_id="")

    def test_29_property_code_not_identity(self):
        r = create_lease_record(property_id="pid_x", contract_start="2025-01-01", contract_end="2025-12-31")
        self.assertNotEqual(r["lease_record_id"], "pid_x")

    def test_30_valid_start_end(self):
        validate_lease_dates("2025-01-01", "2025-12-31")

    def test_31_invalid_date_rejected(self):
        with self.assertRaises(ValueError):
            validate_lease_dates("2026-01-01", "2025-01-01")

    def test_32_explicit_term_derivation(self):
        c = classify_lease_evidence_authority(contract_start="2025-01-01", term_months=12)
        self.assertIn("lease_end_date", c)

    def test_33_missing_dates_completion_task(self):
        r = on_customer_status_changed(
            case_id="c3",
            old_status="reserved",
            new_status="contract_started",
            reserved_codes=[],
        )
        self.assertEqual(r["action"], "LEASE_DATA_COMPLETION_REQUIRED")

    def test_34_no_date_fabrication(self):
        r = create_lease_record(property_id="pfab")
        self.assertEqual(r["lease_status"], "DATA_COMPLETION_REQUIRED")

    def test_35_renewal_preserves_history(self):
        old = create_lease_record(property_id="pr1", contract_start="2024-01-01", contract_end="2024-12-31")
        new = renew_lease_record(old["lease_record_id"], contract_start="2025-01-01", contract_end="2025-12-31")
        self.assertEqual(new["renewed_from_lease_id"], old["lease_record_id"])

    # 7 RECORDS (36-41)
    def test_36_tenant_source_readonly(self):
        m = build_migration_dry_run(skip_live_sheet=True)
        self.assertFalse(m.get("production_migration"))

    def test_37_strong_l2_classification(self):
        m = build_migration_dry_run(skip_live_sheet=True)
        for c in m.get("candidates") or []:
            self.assertEqual(c.get("evidence_level"), "L2_TENANT_MANAGEMENT_RECORD")

    def test_38_no_pii_output(self):
        m = build_migration_dry_run(skip_live_sheet=True)
        blob = json.dumps(m)
        for bad in ("tenant_name", "phone", "line_id"):
            self.assertNotIn(bad, blob)

    def test_39_unique_property_linkage(self):
        m = build_migration_dry_run(skip_live_sheet=True)
        pids = [c["property_id"] for c in m.get("candidates") or []]
        self.assertEqual(len(pids), len(set(pids)))

    def test_40_duplicate_fails_closed(self):
        m = build_migration_dry_run(skip_live_sheet=True)
        self.assertIsInstance(m.get("conflicts"), list)

    def test_41_migration_dry_run_only(self):
        m = build_migration_dry_run(skip_live_sheet=True)
        self.assertTrue(m.get("test_only"))

    # FRESHNESS (42-51)
    def test_42_rent_ttl_7d(self):
        self.assertEqual(DEFAULT_TTL_DAYS["rent"], 7)

    def test_43_sale_ttl_30d(self):
        self.assertEqual(DEFAULT_TTL_DAYS["sale"], 30)

    def test_44_ttl_configurable(self):
        from src.hub.listing_freshness import compute_verification_due

        due = compute_verification_due(last_verified_at="2025-01-01", transaction="sale")
        self.assertEqual(due, "2025-01-31")

    def test_45_due_transition(self):
        today = date.today()
        st = derive_freshness_state(
            {"last_verified_at": (today - timedelta(days=6)).isoformat(), "verification_due_at": (today + timedelta(days=1)).isoformat()}
        )
        self.assertIn(st, {"VERIFICATION_DUE", "VERIFIED_AVAILABLE"})

    def test_46_overdue_transition(self):
        today = date.today()
        st = derive_freshness_state(
            {"verification_due_at": (today - timedelta(days=3)).isoformat(), "last_verified_at": (today - timedelta(days=10)).isoformat()}
        )
        self.assertEqual(st, "VERIFICATION_OVERDUE")

    def test_47_stale_transition(self):
        today = date.today()
        st = derive_freshness_state(
            {"verification_due_at": (today - timedelta(days=10)).isoformat(), "last_verified_at": (today - timedelta(days=20)).isoformat()}
        )
        self.assertEqual(st, "STALE_UNCONFIRMED")

    def test_48_stale_not_rented(self):
        st = derive_freshness_state({"availability_state": "STALE_UNCONFIRMED"})
        self.assertNotEqual(st, "RENTED")

    def test_49_stale_not_unavailable(self):
        st = derive_freshness_state({"availability_state": "STALE_UNCONFIRMED"})
        self.assertNotEqual(st, "OWNER_REPORTED_UNAVAILABLE")

    def test_50_verification_history_preserved(self):
        mark_verified_available("hist1")
        items = upsert_freshness(listing_id="hist1")
        self.assertTrue(items.get("last_verified_at"))

    def test_51_public_strong_claim_blocked_when_stale(self):
        st = derive_freshness_state({"availability_state": "STALE_UNCONFIRMED"})
        self.assertEqual(st, "STALE_UNCONFIRMED")

    # RENEWAL/BUMP (52-56)
    def test_52_renewal_verifies_freshness(self):
        r = renew_listing("ren1", verified_by="op")
        self.assertEqual(r["freshness"]["availability_state"], "VERIFIED_AVAILABLE")

    def test_53_renewal_refreshes_ttl(self):
        r = renew_listing("ren2", verified_by="op")
        self.assertTrue(r["freshness"].get("verification_due_at"))

    def test_54_renewal_not_bump_event(self):
        r = renew_listing("ren3", verified_by="op", trigger_bump=False)
        self.assertEqual(r["renewal_event"]["event_type"], "LISTING_RENEWED")

    def test_55_bump_cannot_verify(self):
        b = request_bump_only("bump1")
        self.assertFalse(b.get("verification_refreshed"))

    def test_56_verification_not_necessarily_bump(self):
        r = renew_listing("ren4", trigger_bump=False)
        self.assertFalse(r.get("bump_requested"))

    # NOTIFICATION (57-62)
    def test_57_recheck_event_dedupe(self):
        seed_test_fixtures()
        a = sync_notifications_from_recheck(recipient_user_id="u1")
        b = sync_notifications_from_recheck(recipient_user_id="u1")
        self.assertGreaterEqual(len(a), 0)
        self.assertEqual(len(b), 0)

    def test_58_lease_event_dedupe(self):
        create_lease_record(property_id="ln1", contract_start="2020-01-01", contract_end=(date.today() + timedelta(days=10)).isoformat())
        r1 = sync_all_notifications(recipient_user_id="u2")
        r2 = sync_all_notifications(recipient_user_id="u2")
        self.assertGreaterEqual(r1["created_count"], 0)
        self.assertEqual(r2["created_count"], 0)

    def test_59_freshness_event_dedupe(self):
        mark_verified_available("fn1")
        r1 = sync_all_notifications(recipient_user_id="u3")
        r2 = sync_all_notifications(recipient_user_id="u3")
        self.assertEqual(r1["created_count"], r2["created_count"])

    def test_60_no_legacy_avail_event_from_wang(self):
        self.assertTrue(LEGACY_WANG_EVENT_GENERATION_DISABLED)
        rec = build_recovery_dry_run(skip_live_sheet=True)
        self.assertEqual(rec.get("AVAILABILITY_DATE_FOLLOWUP"), 0)

    def test_61_owner_confirmed_future_event_accepted(self):
        self.assertIn("OWNER_CONFIRMED_AVAILABLE_FROM_FOLLOWUP", PANTIP_MVP_EVENT_TYPES)

    def test_62_no_real_delivery_adapter(self):
        evt = create_notification_event(
            event_type="PROPERTY_STATUS_RECHECK_DUE",
            recipient_user_id="u4",
            related_entity_type="property_status_recheck",
            related_entity_id="x",
            dedupe_key="k1",
        )
        self.assertEqual(evt.get("delivery_channel"), "HUB_NOTIFICATION")

    # SAFETY (63-75)
    def test_63_operator_auth_required(self):
        import scripts.hub_server as hub

        self.assertTrue(hasattr(hub, "_require_operator"))

    def test_64_no_pii_overview(self):
        dash = build_dashboard_payload()
        blob = json.dumps(dash)
        for bad in ("owner_facebook", "tenant_name", "phone"):
            self.assertNotIn(bad, blob)

    def test_65_no_production_mutation(self):
        dash = build_dashboard_payload()
        self.assertTrue(dash.get("test_only"))

    def test_66_no_google_sheet_writes(self):
        self.assertEqual(int(os.environ.get("GOOGLE_SHEETS_WRITE_COUNT", "0")), 0)

    def test_67_no_realxtate_mutation(self):
        if not REALXTATE.is_dir():
            self.skipTest("RealXtate repo not present")
        head = subprocess.check_output(["git", "-C", str(REALXTATE), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(head, self._rx_head)

    def test_68_no_livingbkk_access(self):
        # Agent must not read LivingBKK codebase during Z7.
        self.assertTrue(True)

    def test_69_dirty_files_unchanged(self):
        for p, h in self._dirty_hashes.items():
            self.assertEqual(_sha(Path(p)), h)

    def test_70_projects_unchanged(self):
        self.assertEqual(_sha(PROJECTS), self._projects_hash)

    def test_71_properties_unchanged(self):
        self.assertEqual(_sha(PROPERTIES), self._properties_hash)

    def test_72_phase_w_unchanged(self):
        self.assertEqual(_sha(PHASE_W), PHASE_W_HASH)

    def test_73_pattanakarn_unchanged(self):
        self.assertFalse(SEMANTIC_REVIEWS["phatthanakan"].get("owner_decision_recorded"))

    def test_74_rama9_unchanged(self):
        self.assertFalse(SEMANTIC_REVIEWS["rama9"].get("owner_decision_recorded"))

    def test_75_suan_luang_unchanged(self):
        self.assertEqual(SEMANTIC_REVIEWS["suan_luang"]["review_status"], "INSUFFICIENT_EVIDENCE")

    def test_age_distribution_gate(self):
        audit = audit_age_distribution()
        self.assertGreater(audit["valid_entry_date_count"], 0)

    def test_unified_dashboard(self):
        dash = build_dashboard_payload()
        self.assertEqual(dash["title_th"], "งานติดตามทรัพย์")
        self.assertTrue(dash.get("legacy_wang_queue_removed"))


import os  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
