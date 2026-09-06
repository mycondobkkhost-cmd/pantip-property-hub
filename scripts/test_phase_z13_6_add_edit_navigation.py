#!/usr/bin/env python3
"""Phase Z13.6 — Add/Edit property step navigation + post-link re-edit gates."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PhaseZ136AddEditNavigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "hub" / "mobile-operations.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")

    def test_01_go_expands_target_zone(self) -> None:
        self.assertIn("function useAddStepAccordion", self.js)
        self.assertIn("applyAccordion(zoneId)", self.js)
        self.assertIn("window.ptpGoAddStep = go", self.js)
        self.assertIn("window.ptpResetAddStepNav", self.js)
        # Must not skip zone 0 head binding
        self.assertNotRegex(
            self.js,
            re.compile(r"if\s*\(\s*!zone\s*\|\|\s*i\s*===\s*0\s*\)\s*return"),
        )

    def test_02_all_zone_heads_bound(self) -> None:
        self.assertIn('head.dataset.z136Bound = "1"', self.js)
        self.assertIn("zones.forEach(function (z)", self.js)
        self.assertIn("go(z.id)", self.js)

    def test_03_edit_open_resets_to_step_1(self) -> None:
        self.assertIn("ptpResetAddStepNav", self.html)
        self.assertIn('ptpGoAddStep("add-zone-source")', self.html)
        self.assertIn('else if (view === "add")', self.html)

    def test_04_source_url_field_canonical(self) -> None:
        self.assertIn('id="add-url"', self.html)
        self.assertIn("source_url: document.getElementById(\"add-url\").value", self.html)
        self.assertIn("source_url: prop.source_url", self.html)
        self.assertIn("data.source_url != null", self.html)

    def test_05_link_edit_unlock_exists(self) -> None:
        self.assertIn("data-link-edit", self.html)
        self.assertIn("function setLinkFieldLocked", self.html)
        self.assertIn("function lockAllLinkFields", self.html)

    def test_06_sticky_step_nav_css(self) -> None:
        self.assertIn("position: sticky", self.css)
        self.assertIn(".add-step-nav", self.css)
        self.assertIn("pointer-events: auto", self.css)

    def test_07_tablet_accordion_css(self) -> None:
        # iPad band must also hide collapsed grids
        tablet = self.css.split("@media (min-width: 769px) and (max-width: 1024px)")[1].split(
            "@media (min-width: 1025px)"
        )[0]
        self.assertIn(".add-zone.collapsed-mobile .add-grid", tablet)
        self.assertIn(".add-step-nav", tablet)

    def test_08_recheck_uses_openPropertyEdit(self) -> None:
        self.assertIn("openPropertyEdit(prop.id)", self.html)
        self.assertNotIn("openEditProperty(prop)", self.html)

    def test_09_assets_z13_7(self) -> None:
        self.assertIn("mobile-operations.css?v=z13_7", self.html)
        self.assertIn("mobile-operations.js?v=z13_7", self.html)

    def test_10_zones_markup_present(self) -> None:
        for zid in (
            "add-zone-source",
            "add-zone-details",
            "add-zone-post",
            "add-zone-groups",
        ):
            self.assertIn(f'id="{zid}"', self.html)


if __name__ == "__main__":
    unittest.main()
