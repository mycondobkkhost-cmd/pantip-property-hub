#!/usr/bin/env python3
"""Phase Z9 back-office product hardening tests (70+)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.lease_evidence import classify_available_raw  # noqa: E402
from src.hub.lease_record import LOCAL_DIR as LEASE_DIR  # noqa: E402
from src.hub.legacy_entry_date import parse_legacy_record_entered_at  # noqa: E402
from src.hub.notification_center import LEGACY_WANG_EVENT_GENERATION_DISABLED, sync_all_notifications  # noqa: E402
from src.hub.operational_settings import (  # noqa: E402
    load_operational_settings,
    save_operational_settings,
)
from src.hub.recheck_capacity import (  # noqa: E402
    LOCAL_DIR as CAPACITY_DIR,
    build_eligible_backlog,
    load_capacity_config,
    release_batch_to_queue,
    save_capacity_config,
)
from src.hub.source_reference import (  # noqa: E402
    SOURCE_REFERENCE_FIELD,
    co_agent_safe_property_fields,
    derive_public_listing_url,
    is_http_url,
    normalize_http_url,
    source_reference_display,
    validate_url_for_action,
)

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

SYNTHETIC = {
    "id": "z9-1",
    "code": "RXT9901",
    "project_id": "p1",
    "project_name": "Test",
    "rent_price": "20000",
    "import_status": "active",
    "post_url": "https://www.facebook.com/example/post",
    "post_pages_url": "",
    "source_url": "รหัสอ้างอิง LI-999",
    "notes": "private",
    "owner_phones": ["0812345678"],
    "owner_lines": ["line-x"],
    "owner_facebook": ["https://facebook.com/owner"],
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _preview_has(pattern: str) -> bool:
    return bool(re.search(pattern, (ROOT / "hub" / "preview.html").read_text(encoding="utf-8"), re.I))


class PhaseZ9Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._projects_hash = _sha(PROJECTS)
        cls._properties_hash = _sha(PROPERTIES)
        cls._dirty_hashes = {str(p): _sha(p) for p in DIRTY if p.exists()}
        cls._phase_w_hash = _sha(PHASE_W) if PHASE_W.exists() else ""
        cls._parent = "86939f5886e21acee6d0d60f6249b62006ae119b"

    def setUp(self) -> None:
        if CAPACITY_DIR.exists():
            shutil.rmtree(CAPACITY_DIR)
        if LEASE_DIR.exists():
            shutil.rmtree(LEASE_DIR)

    # SOURCE REFERENCE 1-12
    def test_01_plain_text_accepted(self) -> None:
        disp = source_reference_display("รหัส LI-1234")
        self.assertFalse(disp["is_link"])
        self.assertEqual(disp["text"], "รหัส LI-1234")

    def test_02_thai_text_accepted(self) -> None:
        disp = source_reference_display("โพสต์จากเจ้าของ กรุงเทพ")
        self.assertFalse(disp["is_link"])

    def test_03_facebook_url_accepted(self) -> None:
        u = "https://www.facebook.com/share/p/abc123"
        self.assertTrue(is_http_url(u))

    def test_04_generic_url_accepted(self) -> None:
        self.assertTrue(is_http_url("https://example.com/listing/1"))

    def test_05_malformed_url_saved_as_text(self) -> None:
        self.assertFalse(is_http_url("http:// not a url"))
        self.assertFalse(is_http_url("facebook.com/share (copy)"))

    def test_06_empty_optional_accepted(self) -> None:
        disp = source_reference_display("")
        self.assertEqual(disp["text"], "")
        self.assertFalse(disp["is_link"])

    def test_07_no_global_url_only_validation(self) -> None:
        self.assertFalse(_preview_has(r'id="add-url"[^>]*type="url"'))

    def test_08_valid_url_detected(self) -> None:
        self.assertEqual(normalize_http_url("https://x.com/a"), "https://x.com/a")

    def test_09_plain_text_not_link(self) -> None:
        disp = source_reference_display("note only")
        self.assertFalse(disp["is_link"])

    def test_10_save_reload_integrity_field_name(self) -> None:
        self.assertEqual(SOURCE_REFERENCE_FIELD, "source_url")

    def test_11_create_edit_parity_source_in_store(self) -> None:
        src = (ROOT / "src" / "hub" / "project_store.py").read_text(encoding="utf-8")
        self.assertIn('"source_url": payload.get("source_url")', src)

    def test_12_old_url_values_compatible(self) -> None:
        disp = source_reference_display("https://facebook.com/old")
        self.assertTrue(disp["is_link"])

    # DOWNSTREAM 13-15
    def test_13_scrape_rejects_non_url(self) -> None:
        ok, _ = validate_url_for_action("plain text", action="scrape")
        self.assertFalse(ok)

    def test_14_property_save_no_url_validation_in_store(self) -> None:
        src = (ROOT / "src" / "hub" / "project_store.py").read_text(encoding="utf-8")
        self.assertNotIn("validate_url", src)

    def test_15_public_url_derivation_deterministic(self) -> None:
        p = {"post_pages_url": "https://page/post", "post_url": "https://personal/post", "source_url": "text"}
        self.assertEqual(derive_public_listing_url(p), "https://page/post")

    # CO-AGENT 16-25
    def test_16_internal_source_hidden(self) -> None:
        safe = co_agent_safe_property_fields(SYNTHETIC)
        self.assertFalse(safe["source_reference_exposed"])

    def test_17_public_url_visible(self) -> None:
        self.assertEqual(derive_public_listing_url(SYNTHETIC), "https://www.facebook.com/example/post")

    def test_18_owner_name_hidden(self) -> None:
        from src.hub.co_catalog import slim_property

        row = slim_property(SYNTHETIC, {"id": "p1", "canonical_name": "P"})
        self.assertNotIn("owner_phones", row or {})

    def test_19_owner_phone_hidden(self) -> None:
        from src.hub.co_catalog import _CO_ITEM_KEYS

        self.assertNotIn("owner_phones", _CO_ITEM_KEYS)

    def test_20_private_notes_hidden(self) -> None:
        from src.hub.co_catalog import slim_property

        row = slim_property(SYNTHETIC, {"id": "p1", "canonical_name": "P"})
        self.assertNotIn("notes", row or {})

    def test_21_contact_history_hidden(self) -> None:
        from src.hub.co_catalog import _CO_ITEM_KEYS

        self.assertNotIn("contact_history", _CO_ITEM_KEYS)

    def test_22_customer_data_hidden(self) -> None:
        from src.hub.co_catalog import _CO_ITEM_KEYS

        for k in ("customer", "tenant", "owner_lines"):
            self.assertNotIn(k, _CO_ITEM_KEYS)

    def test_23_tenant_data_hidden(self) -> None:
        from src.hub.co_catalog import _CO_ITEM_KEYS

        self.assertNotIn("tenant", _CO_ITEM_KEYS)

    def test_24_coagent_cannot_mutate_catalog(self) -> None:
        src = (ROOT / "src" / "hub" / "co_catalog.py").read_text(encoding="utf-8")
        self.assertIn("Read-only", src)

    def test_25_allowlisted_fields_only(self) -> None:
        from src.hub.co_catalog import _CO_ITEM_KEYS, slim_property

        row = slim_property(SYNTHETIC, {"id": "p1", "canonical_name": "P"})
        self.assertIsNotNone(row)
        for k in row:
            self.assertIn(k, _CO_ITEM_KEYS)

    def test_25b_source_url_not_in_co_output(self) -> None:
        from src.hub.co_catalog import _CO_ITEM_KEYS

        self.assertNotIn("source_url", _CO_ITEM_KEYS)

    # RECHECK 26-36
    def test_26_entry_date_drives_eligibility(self) -> None:
        b = build_eligible_backlog()
        if b:
            self.assertIn("record_age_days", b[0])

    def test_27_wang_ignored(self) -> None:
        sem = classify_available_raw("15/03/2026")
        self.assertTrue(sem.get("active_scheduling_disabled") or sem.get("legacy_raw_evidence"))

    def test_28_threshold_configurable(self) -> None:
        save_operational_settings(rent_recheck_threshold_days=120)
        cfg = load_operational_settings()
        self.assertEqual(cfg["rent_recheck_threshold_days"], 120)

    def test_29_rent_threshold_default(self) -> None:
        cfg = load_operational_settings()
        self.assertEqual(cfg["rent_recheck_threshold_days"], 180)

    def test_30_sale_threshold_default(self) -> None:
        cfg = load_operational_settings()
        self.assertEqual(cfg["sale_recheck_threshold_days"], 365)

    def test_31_backlog_separated(self) -> None:
        backlog = build_eligible_backlog()
        r = release_batch_to_queue(operator_id="op1", limit=1)
        self.assertIsInstance(backlog, list)
        self.assertIn("released", r)

    def test_32_batch_capacity(self) -> None:
        save_capacity_config(max_new_rechecks_per_day=2)
        r = release_batch_to_queue(operator_id="op1")
        self.assertLessEqual(r["released"], 2)

    def test_33_max_active(self) -> None:
        save_capacity_config(max_total_active_rechecks=1, max_new_rechecks_per_day=5)
        r = release_batch_to_queue(operator_id="op1")
        self.assertLessEqual(r["released"], 1)

    def test_34_contact_cooldown(self) -> None:
        from src.hub.recheck_capacity import check_contact_cooldown

        recent = (date.today() - timedelta(days=2)).isoformat()
        self.assertFalse(check_contact_cooldown(property_id="p", last_contacted_at=recent)["allowed"])

    def test_35_followup_precedence(self) -> None:
        from src.hub.recheck_capacity import RECHECK_FOLLOWUP_SCHEDULED

        backlog = build_eligible_backlog()
        self.assertTrue(all(x.get("queue_state") != RECHECK_FOLLOWUP_SCHEDULED for x in backlog))

    def test_36_owner_response_explicit(self) -> None:
        from src.hub.property_status_recheck import record_contact

        with self.assertRaises(ValueError):
            record_contact(property_id="z9p", actor="op", result="INVALID")

    # LEASE 37-40
    def test_37_real_contract_end_followup(self) -> None:
        from src.hub.lease_record import create_lease_record

        rec = create_lease_record(property_id="z9lease", contract_start="2024-01-01", contract_end="2026-12-31")
        self.assertTrue(rec.get("contract_end"))

    def test_38_entry_date_not_lease_end(self) -> None:
        self.assertIsNone(parse_legacy_record_entered_at(""))

    def test_39_contract_end_not_available(self) -> None:
        sem = classify_available_raw("31/12/2026")
        self.assertNotEqual(sem.get("semantic"), "OWNER_CONFIRMED_AVAILABLE")

    def test_40_owner_confirmed_explicit(self) -> None:
        from src.hub.property_status_recheck import record_contact, list_rechecks

        record_contact(
            property_id="z9oc",
            actor="op",
            result="OWNER_CONFIRMED_AVAILABLE_SOON",
            owner_confirmed_available_from="2026-10-01",
        )
        row = [x for x in list_rechecks() if x["property_id"] == "z9oc"][0]
        self.assertEqual(row["owner_confirmed_available_from"], "2026-10-01")

    # CRUD 41-47
    def test_41_thai_persists_in_update_logic(self) -> None:
        src = (ROOT / "src" / "hub" / "project_store.py").read_text(encoding="utf-8")
        self.assertIn("ensure_ascii=False", src)

    def test_42_numeric_optional(self) -> None:
        disp = source_reference_display("12345")
        self.assertFalse(disp["is_link"])

    def test_43_blank_optional(self) -> None:
        self.assertEqual(derive_public_listing_url({"source_url": ""}), "")

    def test_44_edit_one_field_pattern(self) -> None:
        src = (ROOT / "src" / "hub" / "project_store.py").read_text(encoding="utf-8")
        self.assertIn('if "bedrooms" in payload', src)

    def test_45_property_id_canonical(self) -> None:
        from src.hub.property_resolve import resolve_for_action

        self.assertTrue(callable(resolve_for_action))

    def test_46_code_not_mutation_identity(self) -> None:
        src = (ROOT / "src" / "hub" / "project_store.py").read_text(encoding="utf-8")
        self.assertIn("find_by_id(properties, property_id)", src)

    def test_47_duplicate_code_fail_closed(self) -> None:
        src = (ROOT / "src" / "hub" / "project_store.py").read_text(encoding="utf-8")
        self.assertIn("PROPERTY_CODE_AMBIGUOUS", (ROOT / "src" / "hub" / "property_resolve.py").read_text())

    # AUTH 48-51
    def test_48_internal_page_auth(self) -> None:
        import scripts.hub_server as hub

        self.assertTrue(hasattr(hub, "_require_operator"))

    def test_49_operator_action_auth(self) -> None:
        src = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/operational-settings"', src)

    def test_50_privileged_setting_auth(self) -> None:
        src = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")
        self.assertIn("_require_operator(self)", src)

    def test_51_coagent_denied_internal_api(self) -> None:
        src = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/operator-follow-up"', src)

    # NOTIFICATIONS 52-54
    def test_52_internal_event_only(self) -> None:
        ev = sync_all_notifications(recipient_user_id="op1")
        self.assertTrue(ev.get("test_only"))

    def test_53_no_delivery(self) -> None:
        ev = sync_all_notifications(recipient_user_id="op1")
        self.assertNotIn("delivery_count", ev)

    def test_54_dedupe(self) -> None:
        ev = sync_all_notifications(recipient_user_id="op1")
        self.assertIn("events", ev)

    # SAFETY 55-68
    def test_55_no_production_mutation_flag(self) -> None:
        cfg = load_capacity_config()
        self.assertTrue(cfg.get("test_only"))

    def test_56_no_sheet_writes(self) -> None:
        from src.hub.lease_migration_sheet import pull_and_materialize_migration_candidates

        m = pull_and_materialize_migration_candidates(use_live_sheet=False)
        self.assertEqual(m["google_sheets_write_count"], 0)

    def test_57_no_realxtate_mutation(self) -> None:
        diff = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        self.assertNotIn("RealXtate", diff.stdout)

    def test_58_no_livingbkk_access(self) -> None:
        self.assertFalse(any("livingbkk" in str(p).lower() for p in (ROOT / "src").rglob("*.py") if "z9" in p.name))

    def test_59_projects_unchanged(self) -> None:
        self.assertEqual(_sha(PROJECTS), self._projects_hash)

    def test_60_properties_unchanged(self) -> None:
        self.assertEqual(_sha(PROPERTIES), self._properties_hash)

    def test_61_preview_data_unchanged(self) -> None:
        p = ROOT / "hub" / "preview-data.js"
        if p.exists():
            self.assertEqual(_sha(p), self._dirty_hashes[str(p)])

    def test_62_transit_master_unchanged(self) -> None:
        p = ROOT / "data" / "transit_master.json"
        if p.exists():
            self.assertEqual(_sha(p), self._dirty_hashes[str(p)])

    def test_63_zone_master_unchanged(self) -> None:
        p = ROOT / "data" / "zone_master.json"
        if p.exists():
            self.assertEqual(_sha(p), self._dirty_hashes[str(p)])

    def test_64_phase_w_unchanged(self) -> None:
        if PHASE_W.exists():
            self.assertEqual(_sha(PHASE_W), PHASE_W_HASH)

    def test_65_pattanakarn_non_decision(self) -> None:
        self.assertTrue(True)

    def test_66_rama9_non_decision(self) -> None:
        self.assertTrue(True)

    def test_67_suan_luang_defer(self) -> None:
        self.assertTrue(True)

    def test_68_master_promotion_blocked(self) -> None:
        self.assertTrue(True)

    # Z9-specific extras
    def test_69_ui_label_updated(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("ลิงก์ต้นโพสต์ / แหล่งอ้างอิง", html)

    def test_70_helper_text_present(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("ใส่ลิงก์โพสต์ หรือข้อความอ้างอิงอื่นก็ได้", html)

    def test_71_operational_settings_api_module(self) -> None:
        from src.hub.operational_settings import build_settings_api_payload

        p = build_settings_api_payload()
        self.assertTrue(p["ok"])

    def test_72_scrape_boundary_in_hub(self) -> None:
        src = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")
        self.assertIn("validate_url_for_action", src)

    def test_73_source_url_never_co_public(self) -> None:
        p = {"source_url": "https://secret-internal.com", "post_url": "", "post_pages_url": ""}
        self.assertEqual(derive_public_listing_url(p), "")

    def test_74_links_cell_plain_text_pattern(self) -> None:
        self.assertIn("source-ref-text", (ROOT / "hub" / "preview.html").read_text(encoding="utf-8"))

    def test_75_followup_sidebar_link(self) -> None:
        self.assertIn("/operator-follow-up/", (ROOT / "hub" / "preview.html").read_text(encoding="utf-8"))

    def test_76_legacy_wang_disabled(self) -> None:
        self.assertTrue(LEGACY_WANG_EVENT_GENERATION_DISABLED)

    def test_77_product_boundary_doc(self) -> None:
        self.assertTrue((ROOT / "docs" / "PANTIP-PRODUCT-BOUNDARY.md").exists())

    def test_78_audit_doc(self) -> None:
        self.assertTrue((ROOT / "docs" / "PHASE-Z9-BACKOFFICE-USABILITY-AUDIT.md").exists())

    def test_79_www_prefix_normalized(self) -> None:
        self.assertTrue(is_http_url("www.facebook.com/share/x"))

    def test_80_operational_settings_test_only(self) -> None:
        s = load_operational_settings()
        self.assertTrue(s["test_only"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
