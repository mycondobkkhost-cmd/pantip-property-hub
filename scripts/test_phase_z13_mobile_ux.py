#!/usr/bin/env python3
"""Phase Z13 — mobile UX gates, group_recommend_history isolation."""

from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OWNER_HISTORY = ROOT / "data" / "group_recommend_history.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PhaseZ13MobileUx(unittest.TestCase):
    def test_01_group_history_writer_is_group_store(self):
        from src.hub.group_store import _save_recommend_history

        self.assertEqual(_save_recommend_history.__module__, "src.hub.group_store")

    def test_02_e2e_root_does_not_target_repo_history(self):
        from src.hub.group_store import group_recommend_history_path

        iso = Path(tempfile.mkdtemp(prefix="z13-grp-"))
        self.addCleanup(lambda: shutil.rmtree(iso, ignore_errors=True))
        os.environ["PANTIP_E2E_DATA_ROOT"] = str(iso)
        try:
            path = group_recommend_history_path()
            self.assertEqual(path, iso / "group_recommend_history.json")
            self.assertNotEqual(path.resolve(), OWNER_HISTORY.resolve())
        finally:
            os.environ.pop("PANTIP_E2E_DATA_ROOT", None)

    def test_03_mark_group_used_writes_isolated_only(self):
        pre_owner = _sha(OWNER_HISTORY) if OWNER_HISTORY.exists() else ""
        iso = Path(tempfile.mkdtemp(prefix="z13-mark-"))
        self.addCleanup(lambda: shutil.rmtree(iso, ignore_errors=True))
        os.environ["PANTIP_E2E_DATA_ROOT"] = str(iso)
        import src.hub.group_store as gs

        importlib.reload(gs)
        try:
            gs.mark_group_used("https://facebook.com/groups/z13-test", property_code="Z13TST")
            self.assertTrue((iso / "group_recommend_history.json").exists())
            if pre_owner and OWNER_HISTORY.exists():
                self.assertEqual(_sha(OWNER_HISTORY), pre_owner)
        finally:
            os.environ.pop("PANTIP_E2E_DATA_ROOT", None)
            importlib.reload(gs)

    def test_04_mobile_assets_exist(self):
        self.assertTrue((ROOT / "hub" / "mobile-operations.css").is_file())
        self.assertTrue((ROOT / "hub" / "mobile-operations.js").is_file())

    def test_05_preview_links_mobile_assets(self):
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("mobile-operations.css", html)
        self.assertIn("mobile-operations.js", html)
        self.assertIn('data-view="add"', html)
        self.assertIn("mobile-sticky-save", html)
        self.assertIn("mobile-more-sheet", html)

    def test_06_recheck_thai_labels_not_technical_in_staff_ui(self):
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("ต้องติดตามวันนี้", html)
        self.assertIn("รอเข้าคิว", html)
        self.assertNotIn("OLD_RECORD_RECHECK", html.split("renderRecheckPanel")[0][-5000:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
