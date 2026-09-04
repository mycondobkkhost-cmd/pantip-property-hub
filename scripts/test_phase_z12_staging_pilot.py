#!/usr/bin/env python3
"""Phase Z12 — hub_sheet_export forensics, staging config, isolation gates."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REPO_HUB_EXPORT = ROOT / "data" / "hub_sheet_export.csv"
STAGING_TOML = ROOT / "fly.staging.toml"
PRODUCTION_APP = "property-hub"
STAGING_APP = "property-hub-staging"
BACKUP_DIR = Path.home() / "Backups" / "pantip-property-automation" / "production-fly-20260904T011836Z"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhaseZ12StagingPilot(unittest.TestCase):
    def test_01_hub_export_writer_is_sheet_write(self):
        from src.hub.sheet_write import write_hub_export_csv

        self.assertEqual(write_hub_export_csv.__module__, "src.hub.sheet_write")

    def test_02_e2e_root_does_not_target_repo_csv(self):
        from src.hub.sheet_write import hub_export_csv_path

        iso = Path(tempfile.mkdtemp(prefix="z12-csv-"))
        self.addCleanup(lambda: shutil.rmtree(iso, ignore_errors=True))
        os.environ["PANTIP_E2E_DATA_ROOT"] = str(iso)
        try:
            path = hub_export_csv_path()
            self.assertEqual(path, iso / "hub_sheet_export.csv")
            self.assertNotEqual(path.resolve(), REPO_HUB_EXPORT.resolve())
        finally:
            os.environ.pop("PANTIP_E2E_DATA_ROOT", None)

    def test_03_save_property_writes_isolated_export_only(self):
        from src.hub.project_store import save_new_property, load_projects

        iso = Path(tempfile.mkdtemp(prefix="z12-save-"))
        self.addCleanup(lambda: shutil.rmtree(iso, ignore_errors=True))
        projects_src = ROOT / "data_seed" / "projects.json"
        shutil.copy(projects_src, iso / "projects.json")
        (iso / "properties.json").write_text("[]", encoding="utf-8")
        pre_repo = _sha(REPO_HUB_EXPORT) if REPO_HUB_EXPORT.exists() else ""
        os.environ["PANTIP_E2E_DATA_ROOT"] = str(iso)
        try:
            proj = load_projects()[0]
            save_new_property(
                {
                    "project_id": proj["id"],
                    "rent_price": "25000",
                    "source_url": "Z12-iso-test",
                }
            )
            self.assertTrue((iso / "hub_sheet_export.csv").exists())
            if pre_repo and REPO_HUB_EXPORT.exists():
                self.assertEqual(_sha(REPO_HUB_EXPORT), pre_repo)
        finally:
            os.environ.pop("PANTIP_E2E_DATA_ROOT", None)

    def test_04_hub_export_classified_derived(self):
        from scripts.backup_data_dir import classify_relative_path

        self.assertEqual(classify_relative_path("hub_sheet_export.csv"), "derived")

    def test_05_staging_toml_not_production(self):
        self.assertTrue(STAGING_TOML.exists())
        text = STAGING_TOML.read_text(encoding="utf-8")
        self.assertIn(f'app = "{STAGING_APP}"', text)
        self.assertNotIn(f'app = "{PRODUCTION_APP}"', text)
        self.assertIn("hub_data_staging", text)
        self.assertNotIn('source = "hub_data"', text)
        self.assertIn("HUB_AUTO_SYNC_TO_SHEET = \"0\"", text)
        self.assertIn("HUB_ALLOW_SHEET_PULL = \"0\"", text)

    def test_06_data_seed_synthetic(self):
        props = json.loads((ROOT / "data_seed" / "properties.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(props), 10)
        for p in props:
            pid = str(p.get("id") or "")
            self.assertTrue(pid.startswith("seed-"), pid)
        blob = json.dumps(props)
        for forbidden in ("089", "line@", "fb_agent", "owner_secret"):
            self.assertNotIn(forbidden, blob.lower())

    def test_07_production_write_gate_unchanged(self):
        from src.hub.operational_settings import can_write_operational_settings

        env = os.environ.copy()
        env["FLY_APP_NAME"] = PRODUCTION_APP
        env.pop("OPERATIONAL_SETTINGS_PRODUCTION_WRITE", None)
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from src.hub.operational_settings import can_write_operational_settings; "
                "print(can_write_operational_settings().get('allowed'))",
            ],
            cwd=str(ROOT),
            env={**env, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
        )
        self.assertIn("False", proc.stdout)

    def test_08_staging_auth_requires_users_not_local_dev(self):
        text = STAGING_TOML.read_text(encoding="utf-8")
        self.assertNotIn("HUB_LOCAL_DEV", text)

    def test_09_coagent_export_allowlist(self):
        from src.hub.realxtate_export import EXPORT_ALLOWLIST, FORBIDDEN_EXPORT_FIELDS

        self.assertIn("public_listing_url", EXPORT_ALLOWLIST)
        self.assertIn("source_url", FORBIDDEN_EXPORT_FIELDS)

    def test_10_backup_outside_repo(self):
        self.assertTrue(BACKUP_DIR.exists())
        self.assertFalse(str(BACKUP_DIR).startswith(str(ROOT)))

    def test_11_staging_single_machine_config(self):
        text = STAGING_TOML.read_text(encoding="utf-8")
        self.assertIn("min_machines_running = 1", text)

    def test_12_writer_call_sites_documented(self):
        from src.hub import project_store, sheet_sync

        save_src = inspect.getsource(project_store._save_new_property_locked)
        sync_src = inspect.getsource(sheet_sync.refresh_main_sheet)
        self.assertIn("write_hub_export_csv", save_src)
        self.assertIn("write_hub_export_csv", sync_src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
