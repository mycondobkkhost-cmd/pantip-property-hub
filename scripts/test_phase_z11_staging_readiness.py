#!/usr/bin/env python3
"""Phase Z11 — staging readiness, test isolation, settings concurrency, backup policy."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.hub.operational_settings import (  # noqa: E402
    PRODUCTION_WRITE_ENV,
    audit_path,
    list_settings_audit,
    save_operational_settings,
    validate_settings_payload,
)
from src.hub.realxtate_export import assert_export_private_safe, project_realxtate_export  # noqa: E402
from src.hub.source_reference import is_http_url, validate_url_for_action  # noqa: E402


def _run_script(name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / name)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


class PhaseZ11StagingReadiness(unittest.TestCase):
    def test_01_z8_test_27_isolation_root_cause_documented(self):
        """Contact events persist under property_status_recheck; Z8 setUp clears RECHECK_STATE_DIR."""
        from src.hub.property_status_recheck import CONTACT_EVENTS_PATH

        self.assertIn("property_status_recheck", str(CONTACT_EVENTS_PATH))

    def test_02_z8_repeatability_three_runs(self):
        for i in range(3):
            proc = _run_script("test_phase_z8_operational_dry_run.py")
            self.assertEqual(
                proc.returncode,
                0,
                f"Z8 run {i + 1} failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}",
            )

    def test_03_settings_concurrent_writes_no_lost_audit(self):
        root = Path(tempfile.mkdtemp(prefix="z11-settings-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        os.environ["PANTIP_OPERATIONAL_STATE_ROOT"] = str(root)
        try:
            writer_count = 20
            barrier = threading.Barrier(writer_count)

            def _writer(idx: int) -> tuple[bool, list[str]]:
                barrier.wait(timeout=30)
                try:
                    save_operational_settings(
                        operator_id="z11-concurrent",
                        reason=f"concurrent-{idx}",
                        rent_recheck_threshold_days=120 + (idx % 50),
                    )
                    audits = list_settings_audit(limit=500)
                    last = audits[-1] if audits else {}
                    changed = last.get("changed_keys") or []
                    return True, changed
                except Exception:
                    return False, []

            results: list[tuple[bool, list[str]]] = []
            with ThreadPoolExecutor(max_workers=writer_count) as pool:
                futures = [pool.submit(_writer, i) for i in range(writer_count)]
                for fut in as_completed(futures):
                    results.append(fut.result())

            successful = sum(1 for ok, changed in results if ok and changed)
            self.assertGreater(successful, 0)

            audit_file = audit_path()
            self.assertTrue(audit_file.exists())
            lines = [ln for ln in audit_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
            self.assertEqual(len(lines), successful, "audit record count must match successful writes")
            for line in lines:
                rec = json.loads(line)
                self.assertIn("changed_keys", rec)
                self.assertEqual(rec.get("operator_id"), "z11-concurrent")
                self.assertTrue(rec["changed_keys"])
        finally:
            os.environ.pop("PANTIP_OPERATIONAL_STATE_ROOT", None)

    def test_04_settings_validation_failure_no_audit_record(self):
        root = Path(tempfile.mkdtemp(prefix="z11-settings-invalid-"))
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        os.environ["PANTIP_OPERATIONAL_STATE_ROOT"] = str(root)
        try:
            before = len(list_settings_audit(limit=500))
            with self.assertRaises(ValueError):
                validate_settings_payload({"rent_recheck_threshold_days": 9999})
            after = len(list_settings_audit(limit=500))
            self.assertEqual(before, after)
        finally:
            os.environ.pop("PANTIP_OPERATIONAL_STATE_ROOT", None)

    def test_05_production_write_gate_default_off(self):
        env = os.environ.copy()
        env.pop(PRODUCTION_WRITE_ENV, None)
        env["FLY_APP_NAME"] = "property-hub"
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; from src.hub.operational_settings import can_write_operational_settings; "
                "g = can_write_operational_settings(); print(g.get('allowed'), g.get('reason'))",
            ],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertIn("False", proc.stdout)
        self.assertIn("not enabled", (proc.stdout + proc.stderr).lower())

    def test_06_source_reference_cases_contract(self):
        cases = {
            "A": "https://www.facebook.com/groups/test/posts/123",
            "B": "https://example.com/listing/42",
            "C": "โพสต์จากกลุ่มเฟส",
            "D": "Owner repost thread",
            "E": "plain text with spaces",
            "F": "Line 081234 mixed 99",
            "G": "",
            "H": "ht!tp://bad url",
        }
        for key, raw in cases.items():
            norm = str(raw or "").strip()
            if key == "G":
                self.assertEqual(norm, "")
            else:
                self.assertEqual(norm, raw.strip())
            if key == "A":
                self.assertTrue(is_http_url(norm))
            if key in {"C", "D", "E", "F", "H"}:
                self.assertFalse(is_http_url(norm))

    def test_07_scrape_boundary_plain_text_rejected(self):
        ok, err = validate_url_for_action("ข้อความธรรมดา", action="scrape")
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_08_coagent_export_privacy(self):
        private_prop = {
            "id": "z11-private",
            "code": "Z11-PRIV",
            "project_id": "p1",
            "rent_price": "25000",
            "source_url": "https://internal.example/secret",
            "notes": "SECRET_NOTE",
            "owner_phones": ["0890000001"],
            "post_url": "https://www.facebook.com/example/public",
        }
        ex = project_realxtate_export(private_prop, {"id": "p1", "canonical_name": "P"})
        leaked = assert_export_private_safe(ex)
        self.assertEqual(leaked, [])
        blob = json.dumps(ex, ensure_ascii=False)
        for forbidden in ("source_url", "owner_phones", "owner_lines", "owner_facebook"):
            self.assertNotIn(forbidden, blob)

    def test_09_mobile_recheck_selectors_present(self):
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        for sel in ("recheck-panel", "follow-tab-recheck", "recheck-filter-kind", 'data-view="followup"'):
            self.assertIn(sel, html)

    def test_10_backup_include_policy_constants(self):
        from scripts.production_backup_fly import AUTHORITATIVE

        self.assertIn("properties.json", AUTHORITATIVE)
        self.assertIn("projects.json", AUTHORITATIVE)

    def test_11_restore_identity_validation_helper(self):
        from scripts.backup_data_dir import validate_backup_identity

        tmp = Path(tempfile.mkdtemp(prefix="z11-restore-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        props = [
            {"property_id": "p1", "property_code": "DUP", "project_id": "pr1"},
            {"property_id": "p2", "property_code": "DUP", "project_id": "pr1"},
        ]
        projects = [{"project_id": "pr1", "name": "Test"}]
        (tmp / "properties.json").write_text(json.dumps(props), encoding="utf-8")
        (tmp / "projects.json").write_text(json.dumps(projects), encoding="utf-8")
        report = validate_backup_identity(tmp)
        self.assertTrue(report["json_parse_ok"])
        self.assertTrue(report["duplicate_property_code_allowed"])

    def test_12_protected_files_exist(self):
        for rel in (
            "data/properties.json",
            "data/projects.json",
            "hub/preview-data.js",
            "data/transit_master.json",
            "data/zone_master.json",
        ):
            self.assertTrue((ROOT / rel).exists(), rel)

    def test_13_e2e_result_contract_if_present(self):
        result_path = Path("/tmp/pantip-phase-z11-e2e/e2e-result.json")
        if not result_path.exists():
            self.skipTest("E2E not run yet")
        data = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertTrue(data.get("browser_launched"))
        self.assertTrue(data.get("login_ok"))
        for key in "ABCDEFGH":
            self.assertIn(key, data.get("source_ui_cases", {}))
            case = data["source_ui_cases"][key]
            self.assertTrue(case.get("ui_save"))
            self.assertTrue(case.get("reopen_match"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
