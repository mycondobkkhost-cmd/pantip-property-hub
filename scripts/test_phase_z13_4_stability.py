#!/usr/bin/env python3
"""Phase Z13.4 — production stability + mobile smoothness regression gates."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PhaseZ134Stability(unittest.TestCase):
    def test_01_escape_closes_filter_drawer(self) -> None:
        js = (ROOT / "hub" / "mobile-operations.js").read_text(encoding="utf-8")
        self.assertIn("closeFilterDrawer", js)
        self.assertIn('e.key !== "Escape"', js)
        # Escape path must hide backdrop via syncBackdrop / closeFilterDrawer
        self.assertIn("syncBackdrop", js)
        self.assertRegex(
            js,
            re.compile(
                r'keydown[\s\S]{0,220}Escape[\s\S]{0,220}closeFilterDrawer',
                re.M,
            ),
        )

    def test_02_catalog_loading_and_error_states(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("showCatalogLoadingState", html)
        self.assertIn("showCatalogLoadError", html)
        self.assertIn("กำลังโหลดทรัพย์…", html)
        self.assertIn("โหลดข้อมูลไม่สำเร็จ ลองใหม่อีกครั้ง", html)
        # Called on login / session restore / boot paths
        self.assertGreaterEqual(html.count("showCatalogLoadingState()"), 3)
        self.assertIn("showCatalogLoadError()", html)

    def test_03_assets_cache_bust_z13_8(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("mobile-operations.css?v=z13_9", html)
        self.assertIn("mobile-operations.js?v=z13_9", html)

    def test_04_z13_3_boot_invariants_still_hold(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("__ptpHubCatalogPromise", html)
        self.assertNotIn("runHubInit(true)", html)
        self.assertIsNone(re.search(r'<script\s+src="preview-data\.js', html))
        self.assertIn("loadHubSidePanelsOnce", html)

    def test_05_apply_filter_closes_drawer_via_shared_helper(self) -> None:
        js = (ROOT / "hub" / "mobile-operations.js").read_text(encoding="utf-8")
        # apply path should reuse closeFilterDrawer (not diverge backdrop sync)
        apply_idx = js.find('getElementById("apply-filter-btn")')
        self.assertGreater(apply_idx, 0)
        chunk = js[apply_idx : apply_idx + 280]
        self.assertIn("closeFilterDrawer", chunk)


if __name__ == "__main__":
    unittest.main()
