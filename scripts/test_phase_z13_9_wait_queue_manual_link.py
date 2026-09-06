#!/usr/bin/env python3
"""Phase Z13.9 — manual link for legacy wait_post_queue rows."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class PhaseZ139WaitQueueManualLink(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        cls.store = (ROOT / "src" / "hub" / "queue_store.py").read_text(encoding="utf-8")
        cls.server = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")

    def test_01_link_backend_retained_not_required_in_row_ui(self) -> None:
        # Backend/API retained; waiting-page rows no longer require linking UI.
        self.assertIn("openQueuePropLinkSheet", self.html)
        self.assertIn('path == "/api/queue/link-property"', self.server)
        chunk = self.html.split("function renderQueue()")[1].split("async function loadQueue")[0]
        self.assertNotIn("เชื่อมทรัพย์", chunk)
        self.assertNotIn('data-qact="link"', chunk)

    def test_02_simple_edit_on_waiting_rows(self) -> None:
        chunk = self.html.split("function renderQueue()")[1].split("async function loadQueue")[0]
        self.assertIn('data-qact="edit"', chunk)
        self.assertNotIn('data-qact="edit-property"', chunk)
        self.assertNotIn('data-qact="edit-queue"', chunk)
        self.assertIn("openQueueFormForEdit", self.html)

    def test_03_picker_results_carry_property_id(self) -> None:
        self.assertIn("data-pick-pid=", self.html)
        self.assertIn("function searchQueueLinkProperties", self.html)
        self.assertIn("ensureSearchCaches()", self.html)

    def test_04_api_and_store_link_property(self) -> None:
        self.assertIn('path == "/api/queue/link-property"', self.server)
        self.assertIn("link_queue_property", self.server)
        self.assertIn("def link_queue_property", self.store)
        self.assertIn("validate_property_id", self.store)
        self.assertIn("allow_replace", self.store)

    def test_05_no_code_resolution_in_link(self) -> None:
        fn = self.store.split("def link_queue_property")[1].split("def add_links")[0]
        # Docstring may mention property_code as forbidden; no runtime code lookup.
        self.assertNotIn('.get("code")', fn)
        self.assertNotIn("property_code", fn.replace("Never resolves by property_code.", ""))
        self.assertIn("validate_property_id", fn)
        self.assertIn('item["property_id"] = pid', fn)

    def test_06_assets_z13_12(self) -> None:
        self.assertIn("mobile-operations.css?v=z13_12", self.html)
        self.assertIn("mobile-operations.js?v=z13_12", self.html)

    def test_07_co_agent_privacy(self) -> None:
        from src.hub.public_projection import build_public_catalog_payload

        payload = build_public_catalog_payload(
            [{"id": "p1"}],
            [
                {
                    "id": "x",
                    "code": "C1",
                    "notes": "ว่างเดือนหน้า",
                    "source_url": "https://facebook.com/x",
                    "owner_phones": ["0812345678"],
                }
            ],
        )
        blob = str(payload)
        self.assertNotIn("ว่างเดือนหน้า", blob)
        self.assertNotIn("0812345678", blob)

    def _e2e(self, props, queue_items):
        tmp = Path(tempfile.mkdtemp(prefix="z139_"))
        (tmp / "properties.json").write_text(json.dumps(props), encoding="utf-8")
        (tmp / "projects.json").write_text(
            json.dumps([{"id": "p1", "canonical_name": "Demo"}]), encoding="utf-8"
        )
        (tmp / "wait_post_queue.json").write_text(
            json.dumps({"items": queue_items, "updated_at": "now"}), encoding="utf-8"
        )
        return tmp

    def test_08_link_persists_selected_id_duplicate_code_safe(self) -> None:
        from src.hub.queue_store import link_queue_property, load_queue
        from src.hub.project_store import load_properties

        props = [
            {
                "id": "prop-a",
                "code": "DUP",
                "source_url": "https://facebook.com/a",
                "project_name": "Demo",
                "rent_price": "10000",
                "notes": "ว่างเดือนหน้า",
            },
            {
                "id": "prop-b",
                "code": "DUP",
                "source_url": "https://facebook.com/b",
                "project_name": "Demo",
                "rent_price": "20000",
                "notes": "wrong",
            },
        ]
        queue = [
            {
                "id": "q1",
                "source_url": "https://facebook.com/legacy",
                "url": "https://facebook.com/legacy",
                "project": "Demo",
                "price": "10000",
                "note": "job",
                "status": "pending",
                "property_id": "",
            }
        ]
        tmp = self._e2e(props, queue)
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            item = link_queue_property("q1", "prop-a")
            self.assertEqual(item.get("property_id"), "prop-a")
            # unrelated fields preserved
            self.assertEqual(item.get("project"), "Demo")
            self.assertEqual(item.get("price"), "10000")
            self.assertEqual(item.get("source_url"), "https://facebook.com/legacy")
            self.assertEqual(item.get("note"), "job")
            self.assertEqual(item.get("status"), "pending")
            # properties untouched
            disk_props = load_properties()
            self.assertEqual(disk_props[0].get("notes"), "ว่างเดือนหน้า")
            self.assertEqual(disk_props[1].get("id"), "prop-b")
            # overwrite refused
            with self.assertRaises(ValueError):
                link_queue_property("q1", "prop-b")
            # allow_replace for explicit correction
            item2 = link_queue_property("q1", "prop-b", allow_replace=True)
            self.assertEqual(item2.get("property_id"), "prop-b")
            again = load_queue()
            self.assertEqual(again[0].get("property_id"), "prop-b")

    def test_09_invalid_and_missing_rejected(self) -> None:
        from src.hub.queue_store import link_queue_property

        props = [{"id": "prop-a", "code": "A", "source_url": "https://facebook.com/a"}]
        queue = [{"id": "q1", "source_url": "https://facebook.com/x", "property_id": ""}]
        tmp = self._e2e(props, queue)
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            with self.assertRaises(ValueError):
                link_queue_property("q1", "missing-id")
            with self.assertRaises(ValueError):
                link_queue_property("q1", "")
            with self.assertRaises(ValueError):
                link_queue_property("no-such-queue", "prop-a")

    def test_10_ui_wires_confirm_and_api(self) -> None:
        self.assertIn('apiPost("/api/queue/link-property"', self.html)
        self.assertIn("confirmQueuePropLink", self.html)
        self.assertIn("openQueuePropLinkSheet", self.html)
        self.assertIn('if (act === "link")', self.html)

    def test_11_z13_8_writers_still_present(self) -> None:
        self.assertIn("enqueuePropertyToWaitPost", self.html)
        self.assertIn("property_id: str = \"\"", self.store)


if __name__ == "__main__":
    unittest.main()
