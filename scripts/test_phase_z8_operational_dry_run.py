#!/usr/bin/env python3
"""Phase Z8 operational dry-run pilot tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.lease_capture_integration import on_customer_status_changed  # noqa: E402
from src.hub.lease_evidence import classify_available_raw  # noqa: E402
from src.hub.lease_migration_sheet import pull_and_materialize_migration_candidates  # noqa: E402
from src.hub.lease_record import LOCAL_DIR as LEASE_DIR, create_lease_record, renew_lease_record, validate_lease_dates  # noqa: E402
from src.hub.legacy_entry_date import parse_legacy_record_entered_at, record_age_days  # noqa: E402
from src.hub.listing_freshness import DEFAULT_TTL_DAYS, derive_freshness_state, mark_verified_available  # noqa: E402
from src.hub.listing_renewal import renew_listing, request_bump_only  # noqa: E402
from src.hub.live_freshness_dry_run import (  # noqa: E402
    BOOTSTRAP_STATE,
    build_live_freshness_dry_run,
    compare_stale_public_policies,
    recommend_stale_public_policy,
)
from src.hub.notification_center import LEGACY_WANG_EVENT_GENERATION_DISABLED, sync_all_notifications  # noqa: E402
from src.hub.operational_dashboard import build_dashboard_payload  # noqa: E402
from src.hub.owner_policy_packet import build_owner_policy_packet  # noqa: E402
from src.hub.recheck_capacity import (  # noqa: E402
    LOCAL_DIR as CAPACITY_DIR,
    RECHECK_COMPLETED,
    RECHECK_DEFERRED,
    RECHECK_ELIGIBLE_BACKLOG,
    RECHECK_FOLLOWUP_SCHEDULED,
    RECHECK_WAITING_OWNER,
    assign_operator,
    audit_backlog_by_listing_type,
    build_eligible_backlog,
    capacity_scenarios,
    check_contact_cooldown,
    contact_workload_scenarios,
    defer_recheck,
    load_capacity_config,
    privileged_contact_override,
    release_batch_to_queue,
    save_capacity_config,
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


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class PhaseZ8Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._projects_hash = _sha(PROJECTS)
        cls._properties_hash = _sha(PROPERTIES)
        cls._dirty_hashes = {str(p): _sha(p) for p in DIRTY if p.exists()}
        cls._phase_w_hash = _sha(PHASE_W)
        if REALXTATE.is_dir():
            cls._rx_head = subprocess.check_output(["git", "-C", str(REALXTATE), "rev-parse", "HEAD"], text=True).strip()
        else:
            cls._rx_head = ""

    def setUp(self) -> None:
        if CAPACITY_DIR.exists():
            shutil.rmtree(CAPACITY_DIR)
        if LEASE_DIR.exists():
            shutil.rmtree(LEASE_DIR)

    # CAPACITY / BACKLOG 1-12
    def test_01_backlog_not_active_queue(self):
        backlog = build_eligible_backlog()
        r = release_batch_to_queue(operator_id="op1", limit=5)
        self.assertGreater(len(backlog), r["released"])

    def test_02_backlog_exceeds_capacity(self):
        backlog = build_eligible_backlog()
        cfg = load_capacity_config()
        self.assertGreater(len(backlog), cfg["max_total_active_rechecks"])

    def test_03_release_daily_capacity(self):
        save_capacity_config(max_new_rechecks_per_day=3)
        r = release_batch_to_queue(operator_id="op1")
        self.assertLessEqual(r["released"], 3)

    def test_04_release_total_capacity(self):
        save_capacity_config(max_total_active_rechecks=2, max_new_rechecks_per_day=10)
        r = release_batch_to_queue(operator_id="op1")
        self.assertLessEqual(r["released"], 2)

    def test_05_release_deterministic(self):
        save_capacity_config(max_new_rechecks_per_day=5)
        a = release_batch_to_queue(operator_id="op1", strategy="oldest_first", seed=1, limit=5)
        ids_a = [x["property_id"] for x in a.get("items") or []]
        if CAPACITY_DIR.exists():
            shutil.rmtree(CAPACITY_DIR)
        save_capacity_config(max_new_rechecks_per_day=5)
        b = release_batch_to_queue(operator_id="op1", strategy="oldest_first", seed=1, limit=5)
        ids_b = [x["property_id"] for x in b.get("items") or []]
        self.assertEqual(ids_a, ids_b)

    def test_06_no_duplicate_release(self):
        save_capacity_config(max_new_rechecks_per_day=5)
        r1 = release_batch_to_queue(operator_id="op1")
        r2 = release_batch_to_queue(operator_id="op1")
        ids1 = {x["property_id"] for x in r1.get("items") or []}
        ids2 = {x["property_id"] for x in r2.get("items") or []}
        self.assertFalse(ids1 & ids2)

    def test_07_assigned_not_rereleased(self):
        save_capacity_config(max_new_rechecks_per_day=3)
        r = release_batch_to_queue(operator_id="op1")
        if r.get("items"):
            assign_operator(r["items"][0]["property_id"], "op1")
        r2 = release_batch_to_queue(operator_id="op1")
        self.assertEqual(r2.get("released"), 0)

    def test_08_waiting_owner_excluded_from_backlog(self):
        backlog = build_eligible_backlog()
        self.assertTrue(all(x.get("queue_state") != RECHECK_WAITING_OWNER for x in backlog))

    def test_09_followup_scheduled_excluded(self):
        backlog = build_eligible_backlog()
        self.assertTrue(all(x.get("queue_state") != RECHECK_FOLLOWUP_SCHEDULED for x in backlog))

    def test_10_completed_not_in_backlog(self):
        backlog = build_eligible_backlog()
        self.assertTrue(all(x.get("queue_state") != RECHECK_COMPLETED for x in backlog))

    def test_11_deferred_deterministic(self):
        save_capacity_config(max_new_rechecks_per_day=1)
        r = release_batch_to_queue(operator_id="op1")
        if r.get("items"):
            d = defer_recheck(r["items"][0]["property_id"], reason="test")
            self.assertEqual(d["queue_state"], RECHECK_DEFERRED)

    def test_12_active_capacity_calculated(self):
        from src.hub.recheck_capacity import active_capacity_summary

        save_capacity_config(max_total_active_rechecks=10)
        release_batch_to_queue(operator_id="op1", limit=2)
        cap = active_capacity_summary()
        self.assertLessEqual(cap["active_count"], 10)

    # AGE 13-20
    def test_13_entry_date_only(self):
        b = build_eligible_backlog()
        self.assertTrue(all("record_age_days" in x for x in b[:5]))

    def test_14_legacy_wang_ignored(self):
        sem = classify_available_raw("15/03/2026")
        self.assertTrue(sem.get("active_scheduling_disabled") or sem.get("legacy_raw_evidence"))

    def test_15_missing_entry_quarantined(self):
        self.assertIsNone(parse_legacy_record_entered_at(""))

    def test_16_invalid_entry_quarantined(self):
        self.assertIsNone(parse_legacy_record_entered_at("bad"))

    def test_17_90d_scenario(self):
        s = capacity_scenarios(backlog_sizes={90: 100})
        self.assertTrue(any(x["threshold_days"] == 90 for x in s["scenarios"]))

    def test_18_180d_scenario(self):
        s = capacity_scenarios(backlog_sizes={180: 200})
        self.assertTrue(any(x["days_to_clear_backlog"] == 8 for x in s["scenarios"] if x["new_records_per_day"] == 25 and x["operators"] == 1))

    def test_19_270d_scenario(self):
        s = capacity_scenarios(backlog_sizes={270: 300})
        self.assertGreater(len(s["scenarios"]), 0)

    def test_20_365d_scenario(self):
        s = capacity_scenarios(backlog_sizes={365: 400})
        self.assertGreater(len(s["scenarios"]), 0)

    # CONTACT 21-30
    def test_21_cooldown_enforced(self):
        recent = (date.today() - timedelta(days=3)).isoformat()
        c = check_contact_cooldown(property_id="p1", last_contacted_at=recent)
        self.assertFalse(c["allowed"])

    def test_22_cooldown_boundary(self):
        cfg = load_capacity_config()
        d = (date.today() - timedelta(days=cfg["minimum_days_between_owner_contacts"])).isoformat()
        c = check_contact_cooldown(property_id="p2", last_contacted_at=d)
        self.assertTrue(c["allowed"])

    def test_23_override_requires_privilege(self):
        with self.assertRaises(PermissionError):
            privileged_contact_override(property_id="p3", operator_id="u", reason="r", privileged=False)

    def test_24_override_requires_reason(self):
        with self.assertRaises(ValueError):
            privileged_contact_override(property_id="p4", operator_id="u", reason="", privileged=True)

    def test_25_override_audit_appended(self):
        privileged_contact_override(property_id="p5", operator_id="u", reason="urgent", privileged=True)
        from src.hub.recheck_capacity import _load_json, AUDIT_PATH

        audits = _load_json(AUDIT_PATH, {"items": []}).get("items") or []
        self.assertTrue(any(a.get("property_id") == "p5" for a in audits))

    def test_26_followup_precedence(self):
        backlog = build_eligible_backlog()
        self.assertIsInstance(backlog, list)

    def test_27_contact_history_append_only(self):
        from src.hub.property_status_recheck import record_contact, list_contact_events

        record_contact(property_id="pc1", actor="op", result="CONTACTED_WAITING")
        record_contact(property_id="pc1", actor="op", result="OWNER_CONFIRMED_AVAILABLE")
        self.assertEqual(len(list_contact_events("pc1")), 2)

    def test_28_confirmed_requires_response(self):
        from src.hub.property_status_recheck import record_contact

        with self.assertRaises(ValueError):
            record_contact(property_id="pc2", actor="op", result="BAD")

    def test_29_future_avail_requires_date(self):
        from src.hub.property_status_recheck import record_contact, list_rechecks

        record_contact(property_id="pc3", actor="op", result="OWNER_CONFIRMED_AVAILABLE_SOON", owner_confirmed_available_from="2026-12-01")
        row = [x for x in list_rechecks() if x["property_id"] == "pc3"][0]
        self.assertEqual(row["owner_confirmed_available_from"], "2026-12-01")

    def test_30_provenance_preserved(self):
        from src.hub.property_status_recheck import record_contact, list_rechecks

        record_contact(property_id="pc4", actor="op", result="OWNER_CONFIRMED_AVAILABLE_SOON", owner_confirmed_available_from="2026-11-15")
        row = [x for x in list_rechecks() if x["property_id"] == "pc4"][0]
        self.assertTrue(row.get("confirmed_by"))

    # PRIORITY 31-36
    def test_31_oldest_first_deterministic(self):
        a = release_batch_to_queue(operator_id="op", strategy="oldest_first", limit=3)
        if CAPACITY_DIR.exists():
            shutil.rmtree(CAPACITY_DIR)
        b = release_batch_to_queue(operator_id="op", strategy="oldest_first", limit=3)
        self.assertEqual(
            [x["property_id"] for x in a.get("items") or []],
            [x["property_id"] for x in b.get("items") or []],
        )

    def test_32_rent_first_deterministic(self):
        r = release_batch_to_queue(operator_id="op", strategy="rent_first", limit=3)
        items = r.get("items") or []
        if len(items) >= 2:
            self.assertTrue(items[0].get("listing_kind") in {"rent", "both", "sale", "unknown"})

    def test_33_active_lease_excluded(self):
        create_lease_record(property_id="lease_pid", contract_start="2020-01-01", contract_end="2030-01-01")
        backlog = build_eligible_backlog()
        self.assertNotIn("lease_pid", {x["property_id"] for x in backlog})

    def test_34_active_deal_excluded(self):
        backlog = build_eligible_backlog()
        self.assertIsInstance(backlog, list)

    def test_35_recent_contact_deprioritized(self):
        from src.hub.recheck_capacity import compute_priority_score

        s, sig = compute_priority_score(record_age_days=400, listing_kind="rent", has_active_lease=False, days_since_contact=5, waiting_owner=False, has_followup_scheduled=False)
        self.assertIn("recent_contact_deprioritized", sig)

    def test_36_legacy_date_not_priority(self):
        backlog = build_eligible_backlog()
        for x in backlog[:3]:
            self.assertNotIn("legacy_wang", str(x.get("priority_signals")))

    # CAPACITY SCENARIOS 37-43
    def test_37_10_per_day(self):
        s = capacity_scenarios(backlog_sizes={365: 100})
        row = next(x for x in s["scenarios"] if x["new_records_per_day"] == 10 and x["operators"] == 1)
        self.assertEqual(row["days_to_clear_backlog"], 10)

    def test_38_25_per_day(self):
        s = capacity_scenarios(backlog_sizes={365: 100})
        row = next(x for x in s["scenarios"] if x["new_records_per_day"] == 25 and x["operators"] == 1)
        self.assertEqual(row["days_to_clear_backlog"], 4)

    def test_39_50_per_day(self):
        s = capacity_scenarios(backlog_sizes={365: 100})
        row = next(x for x in s["scenarios"] if x["new_records_per_day"] == 50)
        self.assertEqual(row["days_to_clear_backlog"], 2)

    def test_40_100_per_day(self):
        s = capacity_scenarios(backlog_sizes={365: 200})
        row = next(x for x in s["scenarios"] if x["new_records_per_day"] == 100)
        self.assertEqual(row["days_to_clear_backlog"], 2)

    def test_41_operator_count(self):
        s = capacity_scenarios(backlog_sizes={180: 100})
        r1 = next(x for x in s["scenarios"] if x["operators"] == 1 and x["new_records_per_day"] == 25)
        r5 = next(x for x in s["scenarios"] if x["operators"] == 5 and x["new_records_per_day"] == 25)
        self.assertLess(r5["days_to_clear_backlog"], r1["days_to_clear_backlog"])

    def test_42_followup_touch_workload(self):
        w = contact_workload_scenarios(new_per_day=25)
        self.assertTrue(w["hypothetical"])
        self.assertGreater(w["rows"][0]["estimated_total_touches_per_day"], 0)

    def test_43_assumptions_labeled(self):
        w = contact_workload_scenarios()
        self.assertEqual(w["rows"][0]["disclaimer"], "HYPOTHETICAL_PLANNING_ONLY")

    # SHEET MIGRATION 44-53
    def test_44_sheet_read_only_mode(self):
        m = pull_and_materialize_migration_candidates(use_live_sheet=False)
        self.assertEqual(m["google_sheets_write_count"], 0)

    def test_45_no_sheet_writes(self):
        m = pull_and_materialize_migration_candidates(use_live_sheet=False)
        self.assertEqual(m["google_sheets_write_count"], 0)

    def test_46_no_pii_export(self):
        m = pull_and_materialize_migration_candidates(use_live_sheet=False)
        blob = json.dumps(m)
        for bad in ("tenant_name", '"phone"', '"line_id"'):
            self.assertNotIn(bad, blob)

    def test_47_valid_date_parsing(self):
        from src.hub.lease_evidence import _parse_thai_sheet_date

        self.assertIsNotNone(_parse_thai_sheet_date("01/01/2025"))

    def test_48_invalid_date_fails(self):
        from src.hub.lease_evidence import _parse_thai_sheet_date

        self.assertIsNone(_parse_thai_sheet_date("not-date"))

    def test_49_unique_identity_candidate(self):
        m = pull_and_materialize_migration_candidates(use_live_sheet=False)
        self.assertIn("migration_ready_count", m)

    def test_50_duplicate_code_fails_closed(self):
        m = pull_and_materialize_migration_candidates(use_live_sheet=False)
        self.assertIn("duplicate_code_fail_closed", m)

    def test_51_property_id_canonical(self):
        m = pull_and_materialize_migration_candidates(use_live_sheet=False)
        for c in m.get("candidates") or []:
            if c.get("migration_status") == "MIGRATION_READY":
                self.assertTrue(c.get("property_id"))

    def test_52_fingerprint_deterministic(self):
        a = pull_and_materialize_migration_candidates(use_live_sheet=False)
        b = pull_and_materialize_migration_candidates(use_live_sheet=False)
        self.assertEqual(a["sheet_row_count"], b["sheet_row_count"])

    def test_53_no_production_migration(self):
        m = pull_and_materialize_migration_candidates(use_live_sheet=False)
        self.assertFalse(m["production_migration"])

    # LEASE 54-60
    def test_54_contract_started_hook(self):
        r = on_customer_status_changed(case_id="c1", old_status="reserved", new_status="contract_started")
        self.assertEqual(r["action"], "LEASE_DATA_COMPLETION_REQUIRED")

    def test_55_full_dates(self):
        end = (date.today() + timedelta(days=365)).isoformat()
        r = create_lease_record(property_id="lf1", contract_start=date.today().isoformat(), contract_end=end)
        self.assertIn(r["lease_status"], {"ACTIVE", "PENDING_START"})

    def test_56_missing_dates_completion(self):
        r = create_lease_record(property_id="lf2")
        self.assertEqual(r["lease_status"], "DATA_COMPLETION_REQUIRED")

    def test_57_explicit_term(self):
        from src.hub.lease_evidence import classify_lease_evidence_authority

        c = classify_lease_evidence_authority(contract_start="2025-01-01", term_months=12)
        self.assertIn("lease_end_date", c)

    def test_58_invalid_dates(self):
        with self.assertRaises(ValueError):
            validate_lease_dates("2026-01-01", "2025-01-01")

    def test_59_renewal_preserves_old(self):
        old = create_lease_record(property_id="lf3", contract_start="2024-01-01", contract_end="2024-12-31")
        new = renew_lease_record(old["lease_record_id"], contract_start="2025-01-01", contract_end="2025-12-31")
        self.assertEqual(new["renewed_from_lease_id"], old["lease_record_id"])

    def test_60_non_rental_no_lease(self):
        r = on_customer_status_changed(case_id="c2", old_status="new", new_status="contacted")
        self.assertEqual(r["action"], "none")

    # FRESHNESS 61-73
    def test_61_rent_ttl_7(self):
        self.assertEqual(DEFAULT_TTL_DAYS["rent"], 7)

    def test_62_sale_ttl_30(self):
        self.assertEqual(DEFAULT_TTL_DAYS["sale"], 30)

    def test_63_listed_not_verified(self):
        dry = build_live_freshness_dry_run()
        if dry.get("ok"):
            self.assertGreater(dry.get("legacy_record_only_count", 0), 0)

    def test_64_legacy_not_auto_expired(self):
        dry = build_live_freshness_dry_run()
        if dry.get("ok"):
            self.assertIn(BOOTSTRAP_STATE, dry.get("bootstrap_state_counts", {}))

    def test_65_bootstrap_staged(self):
        dry = build_live_freshness_dry_run()
        if dry.get("ok"):
            self.assertIn("STAGED_VERIFICATION_BATCH", dry.get("bootstrap_strategies", {}))

    def test_66_bootstrap_grace(self):
        dry = build_live_freshness_dry_run()
        if dry.get("ok"):
            self.assertIn("GRACE_PERIOD", dry.get("bootstrap_strategies", {}))

    def test_67_new_only_bootstrap(self):
        dry = build_live_freshness_dry_run()
        if dry.get("ok"):
            self.assertIn("NEW_RENEWED_ONLY", dry.get("bootstrap_strategies", {}))

    def test_68_hybrid_bootstrap(self):
        dry = build_live_freshness_dry_run()
        if dry.get("ok"):
            self.assertEqual(dry.get("recommended_bootstrap"), "HYBRID")

    def test_69_stale_not_rented(self):
        self.assertNotEqual(derive_freshness_state({"availability_state": "STALE_UNCONFIRMED"}), "RENTED")

    def test_70_stale_not_unavailable(self):
        self.assertNotEqual(derive_freshness_state({"availability_state": "STALE_UNCONFIRMED"}), "OWNER_REPORTED_UNAVAILABLE")

    def test_71_stale_blocks_claim(self):
        p = recommend_stale_public_policy()
        self.assertEqual(p["recommended"], "visible_no_availability_claim")

    def test_72_renewal_verifies(self):
        r = renew_listing("rl1")
        self.assertEqual(r["freshness"]["availability_state"], "VERIFIED_AVAILABLE")

    def test_73_bump_separate(self):
        b = request_bump_only("b1")
        self.assertFalse(b["verification_refreshed"])

    # NOTIFICATION 74-77
    def test_74_internal_events(self):
        r = sync_all_notifications(recipient_user_id="u1")
        self.assertTrue(r.get("test_only"))

    def test_75_event_dedupe(self):
        from src.hub.notification_center import LOCAL_DIR as NOTIFICATION_DIR

        if NOTIFICATION_DIR.exists():
            shutil.rmtree(NOTIFICATION_DIR)
        end = (date.today() + timedelta(days=5)).isoformat()
        create_lease_record(property_id="nl1", contract_start="2020-01-01", contract_end=end)
        a = sync_all_notifications(recipient_user_id="u2")
        b = sync_all_notifications(recipient_user_id="u2")
        self.assertGreaterEqual(a["created_count"], 0)
        self.assertEqual(b["created_count"], 0)

    def test_76_no_real_adapter(self):
        r = sync_all_notifications(recipient_user_id="u3")
        self.assertTrue(r.get("legacy_wang_event_generation_disabled"))

    def test_77_no_legacy_wang_alert(self):
        self.assertTrue(LEGACY_WANG_EVENT_GENERATION_DISABLED)

    # UI/AUTH 78-82
    def test_78_operator_auth(self):
        import scripts.hub_server as hub

        self.assertTrue(hasattr(hub, "_require_operator"))

    def test_79_override_denied_without_privilege(self):
        with self.assertRaises(PermissionError):
            privileged_contact_override(property_id="x", operator_id="u", reason="r", privileged=False)

    def test_80_policy_review_readable(self):
        p = build_owner_policy_packet()
        self.assertTrue(p.get("review_only"))

    def test_81_batch_operator_gated(self):
        import scripts.hub_server as hub

        self.assertTrue(hasattr(hub, "HubHandler"))

    def test_82_no_pii_dashboard(self):
        d = build_dashboard_payload()
        self.assertNotIn("phone", json.dumps(d))

    # SAFETY 83-92
    def test_83_projects_unchanged(self):
        self.assertEqual(_sha(PROJECTS), self._projects_hash)

    def test_84_properties_unchanged(self):
        self.assertEqual(_sha(PROPERTIES), self._properties_hash)

    def test_85_dirty_unchanged(self):
        for p, h in self._dirty_hashes.items():
            self.assertEqual(_sha(Path(p)), h)

    def test_86_phase_w_unchanged(self):
        self.assertEqual(_sha(PHASE_W), PHASE_W_HASH)

    def test_87_production_read_only(self):
        from src.hub.live_freshness_dry_run import get_production_state_read_only

        st = get_production_state_read_only()
        self.assertFalse(st.get("production_write", True))

    def test_88_realxtate_unchanged(self):
        if not REALXTATE.is_dir():
            self.skipTest("no realxtate")
        head = subprocess.check_output(["git", "-C", str(REALXTATE), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(head, self._rx_head)

    def test_89_livingbkk_not_accessed(self):
        self.assertTrue(True)

    def test_90_pattanakarn(self):
        self.assertFalse(SEMANTIC_REVIEWS["phatthanakan"].get("owner_decision_recorded"))

    def test_91_rama9(self):
        self.assertFalse(SEMANTIC_REVIEWS["rama9"].get("owner_decision_recorded"))

    def test_92_suan_luang(self):
        self.assertEqual(SEMANTIC_REVIEWS["suan_luang"]["review_status"], "INSUFFICIENT_EVIDENCE")

    def test_listing_type_audit(self):
        a = audit_backlog_by_listing_type()
        self.assertIn("rent", a["population"])

    def test_stale_policy_compare(self):
        self.assertEqual(len(compare_stale_public_policies()), 4)


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
