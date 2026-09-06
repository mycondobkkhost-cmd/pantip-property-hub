#!/usr/bin/env python3
"""Phase Z13.5 — property list page/scroll stability + lag regression gates."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PhaseZ135PropertyListStability(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")

    def test_01_apply_filter_supports_preserve_page(self) -> None:
        self.assertIn("function applyFilter(opts)", self.html)
        self.assertIn("preservePage", self.html)
        self.assertIn("preserveScroll", self.html)
        # Must not unconditionally bounce to page 0 anymore
        self.assertRegex(
            self.html,
            re.compile(
                r"if\s*\(\s*preservePage\s*\)\s*\{[\s\S]{0,180}page\s*=\s*Math\.min",
                re.M,
            ),
        )
        self.assertIn("page = 0;", self.html)  # intentional path still exists

    def test_02_catalog_refresh_preserves_page(self) -> None:
        self.assertIn("function refreshHubCatalogUI(opts)", self.html)
        self.assertIn("applyFilter({ preservePage: preserve, preserveScroll: preserve })", self.html)
        self.assertIn("preservePage !== false", self.html)

    def test_03_runHubInit_repeat_preserves_page(self) -> None:
        self.assertIn("refreshHubCatalogUI({ preservePage: true })", self.html)

    def test_04_resize_debounced_and_does_not_reset_query(self) -> None:
        self.assertIn("__ptpResizeTimer", self.html)
        self.assertIn("if (prev !== PAGE_SIZE)", self.html)
        self.assertIn("renderRows({ preserveScroll: true })", self.html)
        # height-only Safari chrome must not call applyFilter
        resize_chunk = self.html.split("window.addEventListener(\"resize\"")[1].split(
            "function debounce"
        )[0]
        self.assertNotIn("applyFilter(", resize_chunk)

    def test_05_restore_nav_keeps_page(self) -> None:
        self.assertIn(
            "applyFilter({ preservePage: true, preserveScroll: true })",
            self.html,
        )

    def test_06_search_cache_invalidation_gated_by_version(self) -> None:
        self.assertIn("__ptpLastCatalogVersion", self.html)
        self.assertIn("if (nextVer !== __ptpLastCatalogVersion)", self.html)

    def test_07_assets_z13_8(self) -> None:
        self.assertIn("mobile-operations.css?v=z13_11", self.html)
        self.assertIn("mobile-operations.js?v=z13_11", self.html)

    def test_08_intentional_reset_still_default(self) -> None:
        # User search/filter calls applyFilter() without opts → page 0
        self.assertIn("applyFilter();", self.html)
        # Sort change still uses applyFilter (intentional restart)
        self.assertIn('sortEl.addEventListener("change", applyFilter);', self.html)

    def test_09_loading_state_does_not_clear_existing_cards(self) -> None:
        self.assertIn(
            'if (list && !list.querySelector(".prop-sheet-row"))',
            self.html,
        )

    def test_10_boot_invariants_still_hold(self) -> None:
        self.assertIn("__ptpHubCatalogPromise", self.html)
        self.assertNotIn("runHubInit(true)", self.html)
        self.assertIsNone(re.search(r'<script\s+src="preview-data\.js', self.html))


if __name__ == "__main__":
    unittest.main()
