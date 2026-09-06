#!/usr/bin/env python3
"""Phase Z13.2 — production real-iPhone hotfix regression gates."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PhaseZ132ProductionHotfix(unittest.TestCase):
    def test_01_recheck_existing_unbound_local_fixed(self) -> None:
        from src.hub.recheck_capacity import build_eligible_backlog

        prop_under = {
            "id": "p-under-threshold",
            "code": "PTP-UNDER",
            "last_listed_at": date.today().strftime("%d/%m/%Y"),
            "rent_price": "18000",
            "sale_price": "",
        }
        with mock.patch("src.hub.recheck_capacity.load_properties", return_value=[prop_under]):
            with mock.patch("src.hub.recheck_capacity._active_lease_property_ids", return_value=set()):
                with mock.patch("src.hub.recheck_capacity._load_json", return_value={"items": []}):
                    backlog = build_eligible_backlog(today=date.today())
        self.assertIsInstance(backlog, list)

    def test_02_mobile_more_sheet_hidden_by_default(self) -> None:
        css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")
        self.assertIn(".mobile-more-sheet", css)
        self.assertIn("display: none", css)
        self.assertIn(".mobile-more-sheet.open", css)

    def test_03_mobile_more_icon_bounded(self) -> None:
        css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")
        self.assertIn(".mobile-more-item svg", css)
        self.assertIn("22px", css)

    def test_04_hub_catalog_boot_helpers(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("ensureHubCatalogLoaded", html)
        self.assertIn("runHubInit", html)

    def test_05_internal_catalog_omits_wire_project_map(self) -> None:
        from src.hub.public_projection import build_internal_catalog_payload

        payload = build_internal_catalog_payload(
            [{"id": "proj-1", "canonical_name": "Demo"}],
            [{"id": "prop-1", "project_id": "proj-1", "code": "PTP1"}],
        )
        self.assertNotIn("project_map", payload)
        self.assertEqual(payload.get("catalog_scope"), "internal")

    def test_06_assets_version_z13_2_or_later(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertTrue(
            ("mobile-operations.css?v=z13_2" in html)
            or ("mobile-operations.css?v=z13_3" in html)
            or ("mobile-operations.css?v=z13_4" in html)
            or ("mobile-operations.css?v=z13_7" in html)
            or ("mobile-operations.css?v=z13_8" in html)
            or ("mobile-operations.css?v=z13_9" in html)
            or ("mobile-operations.css?v=z13_12" in html)
            or ("mobile-operations.css?v=z13_6" in html)
            or ("mobile-operations.css?v=z13_5" in html)
        )
        self.assertTrue(
            ("mobile-operations.js?v=z13_2" in html)
            or ("mobile-operations.js?v=z13_3" in html)
            or ("mobile-operations.js?v=z13_4" in html)
            or ("mobile-operations.js?v=z13_7" in html)
            or ("mobile-operations.js?v=z13_8" in html)
            or ("mobile-operations.js?v=z13_9" in html)
            or ("mobile-operations.js?v=z13_12" in html)
            or ("mobile-operations.js?v=z13_6" in html)
            or ("mobile-operations.js?v=z13_5" in html)
        )

    def test_07_lifecycle_sections_remain_separate(self) -> None:
        dash = (ROOT / "src" / "hub" / "operational_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('"old_record_recheck"', dash)
        self.assertIn('"lease_end_soon"', dash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
