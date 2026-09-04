#!/usr/bin/env python3
"""Phase Z13.3 — mobile boot + catalog performance hardening gates."""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class PhaseZ133BootCatalog(unittest.TestCase):
    def test_01_shared_catalog_promise_helpers_present(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("__ptpHubCatalogPromise", html)
        self.assertIn("isInternalCatalogReady", html)
        self.assertIn("acceptInternalCatalogPayload", html)
        self.assertIn("loadHubSidePanelsOnce", html)
        self.assertIn("refreshHubCatalogUI", html)
        self.assertIn("resetHubCatalogState", html)

    def test_02_zero_property_catalog_is_success(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertNotIn(
            "return (window.PTP_DATA.properties || []).length > 0;",
            html,
        )
        self.assertIn("Array.isArray(data.properties)", html)
        self.assertIn('data.catalog_scope !== "internal"', html)

    def test_03_authenticated_boot_skips_static_preview_data(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        # No static script tag downloading ~8MB on every Hub load
        self.assertIsNone(re.search(r'<script\s+src="preview-data\.js', html))
        self.assertIn("loadPreviewDataScriptOnly", html)
        self.assertIn("protocol === \"file:\"", html)

    def test_04_assets_version_z13_4(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("mobile-operations.css?v=z13_4", html)
        self.assertIn("mobile-operations.js?v=z13_4", html)

    def test_05_internal_catalog_omits_project_map_wire_dup(self) -> None:
        from src.hub.public_projection import build_internal_catalog_payload

        payload = build_internal_catalog_payload(
            [{"id": "proj-1", "canonical_name": "Demo"}],
            [{"id": "prop-1", "project_id": "proj-1", "code": "PTP1"}],
        )
        self.assertNotIn("project_map", payload)
        self.assertEqual(payload.get("catalog_scope"), "internal")
        self.assertTrue(payload.get("ok"))
        self.assertEqual(len(payload["projects"]), 1)
        self.assertEqual(len(payload["properties"]), 1)

    def test_06_zero_property_payload_valid(self) -> None:
        from src.hub.public_projection import build_internal_catalog_payload

        payload = build_internal_catalog_payload(
            [{"id": "proj-1", "canonical_name": "Demo"}],
            [],
            stats={"properties_total": 0, "projects": 1},
        )
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload["properties"], [])
        self.assertEqual(payload["catalog_scope"], "internal")

    def test_07_runHubInit_no_longer_force_on_restore_login(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        # restoreSession / login must not force double init
        self.assertNotIn("runHubInit(true)", html)
        self.assertIn("runHubInit(false)", html)
        self.assertIn("loadHubSidePanelsOnce", html)

    def test_08_reload_uses_catalog_on_http(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("reloadInternalCatalogAndRefresh", html)
        self.assertIn("Authenticated Hub: refresh from /api/hub/catalog", html)

    def test_09_client_ensureProjectMap_still_present(self) -> None:
        html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        self.assertIn("function ensureProjectMap()", html)

    def test_10_public_catalog_strips_owner_private_fields(self) -> None:
        from src.hub.public_projection import build_public_catalog_payload

        payload = build_public_catalog_payload(
            [{"id": "proj-1"}],
            [
                {
                    "id": "prop-1",
                    "code": "PTP1",
                    "owner_phones": ["0812345678"],
                    "owner_lines": ["x"],
                    "owner_facebook": ["y"],
                    "notes": "secret",
                    "contact_history": [],
                }
            ],
        )
        blob = json.dumps(payload)
        for banned in (
            "owner_phones",
            "owner_lines",
            "owner_facebook",
            "notes",
            "contact_history",
        ):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
