#!/usr/bin/env python3
"""Phase Z6 lease data + freshness foundation tests."""

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
    Z5_REALXTATE_HEAD,
    build_cross_product_capability_diff_v2,
    build_realxtate_delta_since_z5,
    write_z6_artifacts,
)
from src.hub.lease_evidence import (  # noqa: E402
    AVAILABLE_SEMANTIC_AVAILABLE,
    classify_available_raw,
    classify_lease_evidence_authority,
    classify_property_linkage,
    build_recovery_dry_run,
    LINK_DUPLICATE_CODE,
)
from src.hub.lease_record import (  # noqa: E402
    LOCAL_DIR as LEASE_RECORD_DIR,
    create_lease_record,
    derive_status,
    renew_lease_record,
    validate_lease_dates,
)
from src.hub.listing_freshness import (  # noqa: E402
    LOCAL_DIR as FRESHNESS_DIR,
    derive_freshness_state,
    mark_verified_available,
    upsert_freshness,
)
from src.hub.notification_center import OTP_IS_NOT_NOTIFICATION, create_notification_event  # noqa: E402
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


class PhaseZ6Tests(unittest.TestCase):
    def setUp(self) -> None:
        for d in (LEASE_RECORD_DIR, FRESHNESS_DIR):
            if d.exists():
                shutil.rmtree(d)

    @classmethod
    def setUpClass(cls) -> None:
        cls._projects_hash = _sha(PROJECTS)
        cls._properties_hash = _sha(PROPERTIES)
        cls._dirty_hashes = {str(p): _sha(p) for p in DIRTY if p.exists()}
        cls._phase_w_hash = _sha(PHASE_W)
        cls._rx_head = subprocess.check_output(["git", "-C", str(REALXTATE), "rev-parse", "HEAD"], text=True).strip()

    # --- RealXtate sync ---
    def test_01_realxtate_head_captured(self):
        delta = build_realxtate_delta_since_z5()
        self.assertEqual(delta["z5_observed_head"], Z5_REALXTATE_HEAD)
        self.assertIn("current_head", delta)

    def test_02_realxtate_unchanged(self):
        head = subprocess.check_output(["git", "-C", str(REALXTATE), "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(head, self._rx_head)

    def test_04_delta_deterministic(self):
        self.assertEqual(build_realxtate_delta_since_z5(), build_realxtate_delta_since_z5())

    def test_05_capability_diff_v2_deterministic(self):
        self.assertEqual(
            build_cross_product_capability_diff_v2()["rows"],
            build_cross_product_capability_diff_v2()["rows"],
        )

    # --- Lease evidence ---
    def test_06_available_never_maps_lease_end(self):
        for raw in ("available", "Available", "15/03/2026", "Feb 2025"):
            sem = classify_available_raw(raw)
            self.assertFalse(sem.get("may_map_to_lease_end"))

    def test_07_explicit_contract_end_strong(self):
        c = classify_lease_evidence_authority(contract_end="2026-12-31", source_type="lease_record")
        self.assertTrue(c.get("strong"))

    def test_08_start_term_derives_end(self):
        c = classify_lease_evidence_authority(contract_start="2025-01-01", term_months=12)
        self.assertTrue(c.get("strong"))
        self.assertIn("lease_end_date", c)

    def test_09_start_only_no_term(self):
        c = classify_lease_evidence_authority(contract_start="2025-01-01")
        self.assertFalse(c.get("strong"))

    def test_10_deal_date_not_lease_end(self):
        c = classify_lease_evidence_authority(deal_date="2025-06-01")
        self.assertFalse(c.get("strong"))

    def test_11_availability_date_separate(self):
        c = classify_lease_evidence_authority(available_from="2026-06-01")
        self.assertFalse(c.get("strong"))
        self.assertTrue(c.get("legacy_raw_evidence"))
        self.assertTrue(c.get("active_scheduling_disabled"))

    def test_12_ambiguous_legacy(self):
        c = classify_lease_evidence_authority(contract_start="")
        self.assertFalse(c.get("strong"))

    def test_13_duplicate_code_fails_closed(self):
        from src.hub.lease_evidence import _property_indexes

        _, _, dup = _property_indexes()
        if dup:
            code = next(iter(dup))
            self.assertEqual(classify_property_linkage(property_code=code)["linkage_class"], LINK_DUPLICATE_CODE)

    def test_14_exact_property_id(self):
        from src.hub.project_store import load_properties

        p = load_properties()[0]
        link = classify_property_linkage(property_id=str(p.get("id")))
        self.assertEqual(link["linkage_class"], "EXACT_PROPERTY_ID")

    def test_16_recovery_no_pii_keys(self):
        rec = build_recovery_dry_run(skip_live_sheet=True)
        for row in rec.get("records") or []:
            for bad in ("name", "phone", "line_id", "tenant_name"):
                self.assertNotIn(bad, row)

    # --- Future lease record ---
    def test_17_lease_record_requires_property_id(self):
        with self.assertRaises(ValueError):
            create_lease_record(property_id="")

    def test_18_lease_record_id_independent(self):
        r = create_lease_record(property_id="p1", contract_start="2025-01-01", contract_end="2025-12-31")
        self.assertNotEqual(r["lease_record_id"], r["property_id"])

    def test_20_contract_end_gte_start(self):
        with self.assertRaises(ValueError):
            validate_lease_dates("2026-01-01", "2025-01-01")

    def test_21_invalid_dates_fail(self):
        with self.assertRaises(ValueError):
            validate_lease_dates("bad", "")

    def test_22_renewal_creates_new(self):
        old = create_lease_record(property_id="p2", contract_start="2024-01-01", contract_end="2024-12-31")
        new = renew_lease_record(old["lease_record_id"], contract_start="2025-01-01", contract_end="2025-12-31")
        self.assertNotEqual(old["lease_record_id"], new["lease_record_id"])
        self.assertEqual(new["renewed_from_lease_id"], old["lease_record_id"])

    def test_24_expired_not_ended_confirmed(self):
        past = (date.today() - timedelta(days=30)).isoformat()
        st = derive_status({"contract_start": "2020-01-01", "contract_end": past, "lease_status": "ACTIVE"})
        self.assertEqual(st, "STATUS_CONFIRMATION_DUE")

    def test_25_expired_not_available(self):
        st = derive_status({"contract_end": "2020-01-01"})
        self.assertNotIn(st, {"AVAILABLE", "ENDED_CONFIRMED"})

    def test_26_missing_data_completion(self):
        st = derive_status({})
        self.assertEqual(st, "DATA_COMPLETION_REQUIRED")

    # --- Freshness ---
    def test_31_freshness_maps_realxtate(self):
        from src.hub.listing_freshness import REALXTATE_TO_PANTIP_MAP

        self.assertIn("available", REALXTATE_TO_PANTIP_MAP)
        self.assertIn("expired", REALXTATE_TO_PANTIP_MAP)

    def test_32_verified_stores_timestamp(self):
        r = mark_verified_available("lst1")
        self.assertTrue(r.get("last_verified_at"))

    def test_35_stale_not_rented(self):
        st = derive_freshness_state({"availability_state": "STALE_UNCONFIRMED"})
        self.assertNotEqual(st, "RENTED")

    def test_37_freshness_independent_lease(self):
        st = derive_freshness_state({"availability_state": "STALE_UNCONFIRMED", "lease_status": "ACTIVE"})
        self.assertEqual(st, "STALE_UNCONFIRMED")

    def test_39_verification_independent_bump(self):
        from src.hub.listing_freshness import FRESHNESS_EVENTS

        self.assertIn("LISTING_VERIFIED_AVAILABLE", FRESHNESS_EVENTS)
        self.assertIn("LISTING_BUMP_REQUESTED", FRESHNESS_EVENTS)

    # --- Notifications ---
    def test_40_notification_dedupe(self):
        e1 = create_notification_event(
            event_type="LISTING_VERIFICATION_DUE",
            recipient_user_id="u",
            related_entity_type="listing",
            related_entity_id="l1",
            dedupe_key="f::l1",
        )
        e2 = create_notification_event(
            event_type="LISTING_VERIFICATION_DUE",
            recipient_user_id="u",
            related_entity_type="listing",
            related_entity_id="l1",
            dedupe_key="f::l1",
        )
        self.assertIsNotNone(e1)
        self.assertIsNone(e2)

    def test_42_otp_not_notification(self):
        self.assertTrue(OTP_IS_NOT_NOTIFICATION)

    # --- Safety ---
    def test_43_pattanakarn(self):
        self.assertFalse(SEMANTIC_REVIEWS["phatthanakan"].get("owner_decision_recorded"))

    def test_44_rama9(self):
        self.assertFalse(SEMANTIC_REVIEWS["rama9"].get("owner_decision_recorded"))

    def test_46_shared_master_unpromoted(self):
        self.assertEqual(SEMANTIC_REVIEWS["suan_luang"]["review_status"], "INSUFFICIENT_EVIDENCE")

    def test_54_projects_unchanged(self):
        self.assertEqual(_sha(PROJECTS), self._projects_hash)

    def test_55_properties_unchanged(self):
        self.assertEqual(_sha(PROPERTIES), self._properties_hash)

    def test_56_phase_w_unchanged(self):
        self.assertEqual(_sha(PHASE_W), PHASE_W_HASH)

    def test_57_dirty_files_unchanged(self):
        for p, h in self._dirty_hashes.items():
            self.assertEqual(_sha(Path(p)), h)

    def test_recovery_reconciles(self):
        r = build_recovery_dry_run(skip_live_sheet=True)
        total = r["audited_rental_population"]
        cats = r["categories"]
        assigned = cats.get("STRONG_EXPLICIT_LEASE_END", 0) + cats.get("AVAILABLE_FROM_ONLY", 0) + cats.get(
            "NO_EVIDENCE", 0
        )
        self.assertEqual(assigned, total)

    def test_z6_artifacts(self):
        paths = write_z6_artifacts()
        self.assertTrue(Path(paths["state_path"]).is_file())


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
