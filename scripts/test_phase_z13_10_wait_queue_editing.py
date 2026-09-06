#!/usr/bin/env python3
"""Phase Z13.10 — waiting-to-post as editable pre-publish queue."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class PhaseZ1310WaitQueueEditing(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        cls.store = (ROOT / "src" / "hub" / "queue_store.py").read_text(encoding="utf-8")
        cls.server = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")

    def test_01_simple_edit_always_enabled(self) -> None:
        self.assertIn('data-qact="edit"', self.html)
        self.assertIn(">แก้ไข</button>", self.html)
        self.assertIn("openQueueFormForEdit", self.html)
        self.assertNotIn('data-qact="edit" disabled', self.html)
        chunk = self.html.split("function renderQueue()")[1].split("async function loadQueue")[0]
        self.assertNotIn("แก้ไขคิว", chunk)
        self.assertNotIn("แก้ไขทรัพย์", chunk)

    def test_02_property_edit_backend_path_kept(self) -> None:
        self.assertIn("openPropertyEdit(pid)", self.html)
        self.assertIn('if (act === "edit-property")', self.html)

    def test_03_link_not_required_on_waiting_rows(self) -> None:
        chunk = self.html.split("function renderQueue()")[1].split("async function loadQueue")[0]
        self.assertNotIn("เชื่อมทรัพย์", chunk)
        self.assertNotIn('data-qact="link"', chunk)

    def test_04_queue_note_editor_present(self) -> None:
        # Z13.12: full Add form is the editor (note field = #queue-note).
        self.assertIn('id="queue-note"', self.html)
        self.assertIn("openQueueFormForEdit", self.html)
        self.assertIn("fillQueueFormFromItem", self.html)

    def test_05_delete_confirmation_and_label(self) -> None:
        self.assertIn("ลบรายการนี้ออกจากคิว?", self.html)
        chunk = self.html.split("function renderQueue()")[1].split("async function loadQueue")[0]
        self.assertIn(">ลบ</button>", chunk)
        self.assertIn('path == "/api/queue/delete"', self.server)
        self.assertIn("def delete_item", self.store)

    def test_06_save_uses_queue_update_no_catalog_reload(self) -> None:
        fn = self.html.split("async function addToQueue()")[1].split(
            "async function enqueuePropertyToWaitPost"
        )[0]
        self.assertIn('apiPost("/api/queue/update"', fn)
        self.assertIn("renderQueue()", fn)
        self.assertNotIn("reloadInternalCatalog", fn)
        self.assertNotIn("reloadPreviewData", fn)
        self.assertNotIn("/api/hub/catalog", fn)

    def test_07_assets_z13_12(self) -> None:
        self.assertIn("mobile-operations.css?v=z13_12", self.html)
        self.assertIn("mobile-operations.js?v=z13_12", self.html)

    def test_08_co_agent_privacy(self) -> None:
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

    def test_09_notes_escaped(self) -> None:
        chunk = self.html.split("function renderQueuePropNotes")[1].split(
            "function renderQueue()"
        )[0]
        self.assertIn("esc(qNote)", chunk)

    def _e2e(self, props, queue_items, projects=None):
        tmp = Path(tempfile.mkdtemp(prefix="z1310_"))
        (tmp / "properties.json").write_text(json.dumps(props), encoding="utf-8")
        (tmp / "projects.json").write_text(
            json.dumps(projects or [{"id": "p1", "canonical_name": "Demo"}]),
            encoding="utf-8",
        )
        (tmp / "wait_post_queue.json").write_text(
            json.dumps({"items": queue_items, "updated_at": "now"}), encoding="utf-8"
        )
        return tmp

    def test_10_unlinked_and_linked_note_edit_independent(self) -> None:
        from src.hub.queue_store import update_item, load_queue
        from src.hub.project_store import load_properties

        props = [
            {
                "id": "prop-a",
                "code": "A1",
                "source_url": "https://facebook.com/a",
                "notes": "property permanent note",
                "project_name": "Demo",
            }
        ]
        queue = [
            {
                "id": "q-unlinked",
                "source_url": "https://facebook.com/legacy",
                "project": "Demo",
                "price": "10000",
                "note": "old queue",
                "status": "pending",
                "property_id": "",
            },
            {
                "id": "q-linked",
                "source_url": "https://facebook.com/a",
                "project": "Demo",
                "price": "10000",
                "note": "linked queue note",
                "status": "pending",
                "property_id": "prop-a",
            },
        ]
        tmp = self._e2e(props, queue)
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            u = update_item("q-unlinked", note="ว่างเดือนหน้า")
            self.assertEqual(u.get("note"), "ว่างเดือนหน้า")
            self.assertEqual(u.get("property_id"), "")
            self.assertEqual(u.get("project"), "Demo")
            self.assertEqual(u.get("price"), "10000")
            self.assertEqual(u.get("source_url"), "https://facebook.com/legacy")
            self.assertEqual(u.get("status"), "pending")

            linked = update_item("q-linked", note="โพสต์ต้นเดือนหน้า")
            self.assertEqual(linked.get("note"), "โพสต์ต้นเดือนหน้า")
            self.assertEqual(linked.get("property_id"), "prop-a")

            disk_props = load_properties()
            self.assertEqual(disk_props[0].get("notes"), "property permanent note")
            self.assertEqual(disk_props[0].get("id"), "prop-a")

            again = load_queue()
            notes = {x["id"]: x.get("note") for x in again}
            self.assertEqual(notes["q-unlinked"], "ว่างเดือนหน้า")
            self.assertEqual(notes["q-linked"], "โพสต์ต้นเดือนหน้า")

    def test_11_delete_queue_only_keeps_property(self) -> None:
        from src.hub.queue_store import delete_item, load_queue
        from src.hub.project_store import load_properties

        props = [
            {
                "id": "prop-a",
                "code": "A1",
                "source_url": "https://facebook.com/a",
                "notes": "keep me",
            }
        ]
        queue = [
            {
                "id": "q1",
                "source_url": "https://facebook.com/a",
                "note": "temp",
                "status": "pending",
                "property_id": "prop-a",
            },
            {
                "id": "q2",
                "source_url": "https://facebook.com/b",
                "note": "other",
                "status": "pending",
                "property_id": "",
            },
        ]
        tmp = self._e2e(props, queue)
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            delete_item("q1")
            ids = [x.get("id") for x in load_queue()]
            self.assertEqual(ids, ["q2"])
            disk_props = load_properties()
            self.assertEqual(len(disk_props), 1)
            self.assertEqual(disk_props[0].get("id"), "prop-a")
            self.assertEqual(disk_props[0].get("notes"), "keep me")
            with self.assertRaises(ValueError):
                delete_item("missing-qid")

    def test_12_api_update_and_delete_present(self) -> None:
        self.assertIn('path == "/api/queue/update"', self.server)
        self.assertIn("update_item(", self.server)
        self.assertIn('path == "/api/queue/delete"', self.server)
        self.assertIn("delete_item(item_id)", self.server)

    def test_13_z13_9_link_flow_still_present(self) -> None:
        self.assertIn("openQueuePropLinkSheet", self.html)
        self.assertIn('apiPost("/api/queue/link-property"', self.html)


if __name__ == "__main__":
    unittest.main()
