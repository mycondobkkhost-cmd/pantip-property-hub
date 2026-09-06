#!/usr/bin/env python3
"""Phase Z13.11 — restore waiting-to-post UX; simple Edit = queue note."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class PhaseZ1311WaitQueueUxRestore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")

    def _render_queue_chunk(self) -> str:
        return self.html.split("function renderQueue()")[1].split("async function loadQueue")[0]

    def test_01_edit_always_enabled_no_property_id(self) -> None:
        chunk = self._render_queue_chunk()
        self.assertIn('data-qact="edit"', chunk)
        self.assertIn(">แก้ไข</button>", chunk)
        self.assertNotIn("disabled", chunk)
        self.assertNotIn("property_id", chunk)
        self.assertNotIn("edit-queue", chunk)
        self.assertNotIn("edit-property", chunk)
        self.assertNotIn("data-qact=\"link\"", chunk)
        self.assertNotIn("เชื่อมทรัพย์", chunk)

    def test_02_familiar_row_actions(self) -> None:
        chunk = self._render_queue_chunk()
        self.assertIn(">เพิ่มโพส</button>", chunk)
        self.assertIn(">เสร็จ</button>", chunk)
        self.assertIn(">ลบ</button>", chunk)
        self.assertNotIn("ลบออกจากคิว", chunk)

    def test_03_edit_opens_queue_sheet_by_queue_id(self) -> None:
        self.assertIn("openQueueFormForEdit", self.html)
        act = self.html.split('if (act === "edit" || act === "edit-queue")')[1].split(
            'if (act === "edit-property")'
        )[0]
        self.assertIn("openQueueFormForEdit(id)", act)
        self.assertNotIn("openPropertyEdit", act)

    def test_04_save_updates_queue_no_catalog(self) -> None:
        fn = self.html.split("async function addToQueue()")[1].split(
            "async function enqueuePropertyToWaitPost"
        )[0]
        self.assertIn('apiPost("/api/queue/update"', fn)
        self.assertIn("renderQueue()", fn)
        self.assertNotIn("/api/hub/catalog", fn)
        self.assertNotIn("reloadPreviewData", fn)

    def test_05_note_display_is_queue_note(self) -> None:
        notes = self.html.split("function renderQueuePropNotes")[1].split(
            "function renderQueue()"
        )[0]
        self.assertIn("esc(qNote)", notes)
        self.assertNotIn("หมายเหตุคิว", notes)
        self.assertNotIn("หมายเหตุทรัพย์", notes)

    def test_06_bottom_nav_queue_shortcut(self) -> None:
        nav = self.html.split('id="mobile-nav"')[1].split("</nav>")[0]
        self.assertIn('data-view="queue"', nav)
        self.assertIn("รอโพสต์", nav)

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

    def test_09_queue_note_persist_independent(self) -> None:
        from src.hub.queue_store import update_item, load_queue
        from src.hub.project_store import load_properties

        tmp = Path(tempfile.mkdtemp(prefix="z1311_"))
        (tmp / "properties.json").write_text(
            json.dumps(
                [
                    {
                        "id": "prop-a",
                        "code": "A1",
                        "notes": "property permanent",
                        "source_url": "https://facebook.com/a",
                    }
                ]
            ),
            encoding="utf-8",
        )
        (tmp / "projects.json").write_text(
            json.dumps([{"id": "p1", "canonical_name": "Demo"}]), encoding="utf-8"
        )
        (tmp / "wait_post_queue.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "q1",
                            "source_url": "https://facebook.com/legacy",
                            "project": "Demo",
                            "price": "10000",
                            "note": "old",
                            "status": "pending",
                            "property_id": "",
                        }
                    ],
                    "updated_at": "now",
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            item = update_item("q1", note="ว่างเดือนหน้า")
            self.assertEqual(item.get("note"), "ว่างเดือนหน้า")
            self.assertEqual(item.get("id"), "q1")
            self.assertEqual(item.get("property_id"), "")
            self.assertEqual(load_properties()[0].get("notes"), "property permanent")
            self.assertEqual(load_queue()[0].get("note"), "ว่างเดือนหน้า")


if __name__ == "__main__":
    unittest.main()
