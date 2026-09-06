#!/usr/bin/env python3
"""Phase Z13.1 — real iPhone Safari polish gates."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PhaseZ131RealIphonePolish(unittest.TestCase):
    def test_01_viewport_fit_cover(self):
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("viewport-fit=cover", html)

    def test_02_mobile_assets_version_z13_2(self):
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertTrue(
            ("mobile-operations.css?v=z13_2" in html)
            or ("mobile-operations.css?v=z13_9" in html)
            or ("mobile-operations.css?v=z13_8" in html)
        )
        self.assertTrue(
            ("mobile-operations.js?v=z13_2" in html)
            or ("mobile-operations.js?v=z13_9" in html)
            or ("mobile-operations.js?v=z13_8" in html)
        )

    def test_03_nav_equal_slot_css(self):
        css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")
        self.assertIn("repeat(5, minmax(0, 1fr))", css)
        self.assertIn("--mobile-nav-bar", css)
        self.assertIn("--mobile-nav-total", css)

    def test_04_desktop_header_hidden_mobile(self):
        css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")
        self.assertIn(".prop-list-head-desktop", css)
        self.assertIn("display: none", css)

    def test_05_compact_search_css(self):
        css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")
        self.assertIn(".search-loc-wrap", css)
        self.assertIn("display: none", css)

    def test_06_card_hierarchy_markup(self):
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("prop-sheet-price-inline", html)
        self.assertIn("prop-sheet-facts", html)
        self.assertIn("prop-more-menu", html)
        self.assertIn("formatListedDateShort", html)

    def test_07_nav_geometry_helper(self):
        js = (ROOT / "hub" / "mobile-operations.js").read_text(encoding="utf-8")
        self.assertIn("ptpMeasureNavGeometry", js)

    def test_08_freshness_label_no_server_wording(self):
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertNotIn("รายการบนเซิร์ฟเวอร์", html.split("updateDataFreshnessLabel")[1][:800])


if __name__ == "__main__":
    unittest.main(verbosity=2)
