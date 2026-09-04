#!/usr/bin/env python3
"""Phase Z10 internal production pilot tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.operational_settings import (  # noqa: E402
    PRODUCTION_WRITE_ENV,
    SETTING_BOUNDS,
    audit_path,
    build_settings_api_payload,
    can_write_operational_settings,
    list_settings_audit,
    load_operational_settings,
    production_write_enabled,
    save_operational_settings,
    validate_setting_value,
    validate_settings_payload,
)
from src.hub.realxtate_export import (  # noqa: E402
    EXPORT_ALLOWLIST,
    EXPORT_SCHEMA,
    assert_export_private_safe,
    evaluate_export_eligibility,
    idempotency_key,
    project_realxtate_export,
)
from src.hub.recheck_capacity import LOCAL_DIR as CAPACITY_DIR  # noqa: E402
from src.hub.source_reference import derive_public_listing_url  # noqa: E402

PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
PHASE_W_HASH = "9c7eba7f1d44354867efc2fa4c01e3524549c442efa244b07c653398b4dc3602"
DIRTY = [
    ROOT / "data" / "properties.json",
    ROOT / "data" / "projects.json",
    ROOT / "hub" / "preview-data.js",
    ROOT / "hub" / "preview-data.meta.json",
    ROOT / "data" / "transit_master.json",
    ROOT / "data" / "zone_master.json",
]

PRIVATE_PROP = {
    "id": "z10-priv",
    "code": "RXTZ100",
    "project_id": "p1",
    "project_name": "Test",
    "rent_price": "20000",
    "post_url": "https://www.facebook.com/public/z10",
    "source_url": "INTERNAL_REF",
    "notes": "SECRET",
    "owner_phones": ["0811111111"],
    "owner_lines": ["line-z10"],
    "owner_facebook": ["https://facebook.com/owner"],
    "text_th": "public th",
}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class PhaseZ10Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._dirty = {str(p): _sha(p) for p in DIRTY if p.exists()}
        cls._phase_w = _sha(PHASE_W) if PHASE_W.exists() else ""

    def setUp(self) -> None:
        if CAPACITY_DIR.exists():
            shutil.rmtree(CAPACITY_DIR)
        if audit_path().exists():
            audit_path().unlink()

    # Settings 1-10
    def test_01_settings_validation_rejects_negative(self) -> None:
        with self.assertRaises(ValueError):
            validate_setting_value("rent_recheck_threshold_days", -1)

    def test_02_settings_validation_rejects_high(self) -> None:
        with self.assertRaises(ValueError):
            validate_setting_value("max_total_active", 9999)

    def test_03_settings_validation_accepts_valid(self) -> None:
        self.assertEqual(validate_setting_value("contact_cooldown_days", 14), 14)

    def test_04_production_write_default_off(self) -> None:
        os.environ.pop(PRODUCTION_WRITE_ENV, None)
        self.assertFalse(production_write_enabled())

    def test_05_local_write_allowed(self) -> None:
        gate = can_write_operational_settings()
        self.assertTrue(gate.get("allowed"))

    def test_06_settings_audit_log(self) -> None:
        save_operational_settings(operator_id="op1", rent_recheck_threshold_days=181, reason="test")
        audits = list_settings_audit()
        self.assertTrue(any(a.get("operator_id") == "op1" for a in audits))

    def test_07_audit_atomic_append(self) -> None:
        save_operational_settings(operator_id="a", new_batch_per_day=20)
        save_operational_settings(operator_id="b", new_batch_per_day=21)
        self.assertGreaterEqual(len(list_settings_audit()), 2)

    def test_08_settings_api_payload(self) -> None:
        p = build_settings_api_payload()
        self.assertIn("write_gate", p)
        self.assertIn("bounds", p["settings"])

    def test_09_unknown_setting_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_settings_payload({"bogus": 1})

    def test_10_bounds_documented(self) -> None:
        self.assertEqual(SETTING_BOUNDS["rent_recheck_threshold_days"], (30, 730))

    # Export 11-20
    def test_11_export_schema_version(self) -> None:
        self.assertEqual(EXPORT_SCHEMA, "pantip_realxtate_export/v1")

    def test_12_export_allowlist_only(self) -> None:
        ex = project_realxtate_export(PRIVATE_PROP, {"id": "p1", "canonical_name": "P"})
        leaked = assert_export_private_safe(ex)
        self.assertEqual(leaked, [])

    def test_13_source_url_never_exported(self) -> None:
        ex = project_realxtate_export(PRIVATE_PROP, {})
        self.assertNotIn("source_url", ex)

    def test_14_notes_never_exported(self) -> None:
        ex = project_realxtate_export(PRIVATE_PROP, {})
        self.assertNotIn("notes", ex)

    def test_15_owner_never_exported(self) -> None:
        ex = project_realxtate_export(PRIVATE_PROP, {})
        for k in ("owner_phones", "owner_lines", "owner_facebook"):
            self.assertNotIn(k, ex)

    def test_16_eligibility_requires_public_url(self) -> None:
        bad = dict(PRIVATE_PROP)
        bad["post_url"] = ""
        ev = evaluate_export_eligibility(bad, {})
        self.assertFalse(ev["eligible"])

    def test_17_eligible_with_public_url(self) -> None:
        ev = evaluate_export_eligibility(PRIVATE_PROP, {"id": "p1"})
        self.assertTrue(ev["eligible"])

    def test_18_idempotency_key(self) -> None:
        k = idempotency_key(PRIVATE_PROP)
        self.assertEqual(k["source_property_id"], "z10-priv")

    def test_19_public_listing_from_post_url(self) -> None:
        ex = project_realxtate_export(PRIVATE_PROP, {})
        self.assertEqual(ex["public_listing_url"], derive_public_listing_url(PRIVATE_PROP))

    def test_20_allowlist_keys_subset(self) -> None:
        ex = project_realxtate_export(PRIVATE_PROP, {})
        for k in ex:
            if not k.startswith("_"):
                self.assertIn(k, EXPORT_ALLOWLIST)

    # UI / docs 21-28
    def test_21_embedded_recheck_panel_html(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn('id="recheck-panel"', html)
        self.assertIn("ติดตามทรัพย์", html)
        dash = (ROOT / "src" / "hub" / "operational_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('"old_record_recheck"', dash)
        self.assertIn('"lease_end_soon"', dash)

    def test_22_recheck_settings_form(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("recheck-settings-save", html)

    def test_23_standalone_page_preserved(self) -> None:
        self.assertTrue((ROOT / "hub" / "operator-follow-up" / "index.html").exists())

    def test_24_export_contract_doc(self) -> None:
        self.assertTrue((ROOT / "docs" / "PANTIP-REALXTATE-EXPORT-CONTRACT.md").exists())

    def test_25_e2e_data_root_support(self) -> None:
        src = (ROOT / "src" / "hub" / "project_store.py").read_text(encoding="utf-8")
        self.assertIn("PANTIP_E2E_DATA_ROOT", src)

    def test_26_settings_production_env_documented(self) -> None:
        self.assertEqual(PRODUCTION_WRITE_ENV, "OPERATIONAL_SETTINGS_PRODUCTION_WRITE")

    def test_27_hub_settings_audit_route(self) -> None:
        src = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")
        self.assertIn("/api/operational-settings/audit", src)

    def test_28_dry_run_script_exists(self) -> None:
        self.assertTrue((ROOT / "scripts" / "realxtate_export_dry_run.py").exists())

    # Safety 29-35
    def test_29_dirty_properties_unchanged(self) -> None:
        p = ROOT / "data" / "properties.json"
        if p.exists():
            self.assertEqual(_sha(p), self._dirty[str(p)])

    def test_30_dirty_projects_unchanged(self) -> None:
        p = ROOT / "data" / "projects.json"
        if p.exists():
            self.assertEqual(_sha(p), self._dirty[str(p)])

    def test_31_phase_w_unchanged(self) -> None:
        if PHASE_W.exists():
            self.assertEqual(_sha(PHASE_W), PHASE_W_HASH)

    def test_32_no_realxtate_in_diff(self) -> None:
        diff = subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=str(ROOT), text=True)
        self.assertNotIn("RealXtate", diff)

    def test_33_coagent_readonly(self) -> None:
        src = (ROOT / "src" / "hub" / "co_catalog.py").read_text(encoding="utf-8")
        self.assertIn("Read-only", src)

    def test_34_production_host_gate(self) -> None:
        from src.hub.operational_settings import is_production_host

        prev = os.environ.get("FLY_APP_NAME")
        os.environ["FLY_APP_NAME"] = "test-app"
        try:
            gate = can_write_operational_settings()
            self.assertFalse(gate.get("allowed"))
        finally:
            if prev is None:
                os.environ.pop("FLY_APP_NAME", None)
            else:
                os.environ["FLY_APP_NAME"] = prev

    def test_35_e2e_script_exists(self) -> None:
        self.assertTrue((ROOT / "scripts" / "phase_z10_authenticated_e2e.py").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
