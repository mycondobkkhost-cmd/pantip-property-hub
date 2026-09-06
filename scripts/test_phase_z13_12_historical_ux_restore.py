#!/usr/bin/env python3
"""Phase Z13.12 — restore historical property + waiting-queue UX."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _format_compact_date_time(raw: str) -> str:
    """Mirror hub/preview.html formatCompactDateTime for regression checks."""
    if not raw or raw == "—":
        return ""
    s = str(raw).strip()
    y = mo = d = 0
    hh = mi = -1
    m_iso = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2})(?::\d{2})?)?", s
    )
    if m_iso:
        y, mo, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        if m_iso.group(4) is not None:
            hh, mi = int(m_iso.group(4)), int(m_iso.group(5))
    else:
        m_dmy = re.match(
            r"^(\d{1,2})/(\d{1,2})/(\d{2,4})(?:[ T](\d{1,2}):(\d{2})(?::\d{2})?)?", s
        )
        if not m_dmy:
            return s
        d, mo, y = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
        if y < 100:
            y += 2000
        if m_dmy.group(4) is not None:
            hh, mi = int(m_dmy.group(4)), int(m_dmy.group(5))
    if not y or not mo or not d:
        return s
    date_part = f"{d}/{mo}/{y % 100}"
    if hh < 0 or mi < 0:
        return date_part
    ap = "PM" if hh >= 12 else "AM"
    h12 = hh % 12
    if h12 == 0:
        h12 = 12
    return f"{date_part} ({h12}:{mi:02d}{ap}.)"


class PhaseZ1312HistoricalUxRestore(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")

    def _prop_actions(self) -> str:
        return self.html.split("function propQuickActionsHtml")[1].split(
            "function propCardHtml"
        )[0]

    def _render_queue(self) -> str:
        return self.html.split("function renderQueue()")[1].split(
            "async function loadQueue"
        )[0]

    def _add_form(self) -> str:
        return self.html.split('id="queue-form-section"')[1].split(
            'id="queue-rows"'
        )[0]

    # --- MAIN ---
    def test_01_no_per_card_wait_post(self) -> None:
        chunk = self._prop_actions()
        self.assertNotIn("data-prop-queue", chunk)
        self.assertNotIn('title="ใส่คิวรอโพสต์"', chunk)
        self.assertNotIn(">รอโพสต์</button>", chunk)

    def test_02_small_edit_exists(self) -> None:
        chunk = self._prop_actions()
        self.assertIn("prop-qa-btn edit", chunk)
        self.assertIn('data-prop-edit="', chunk)
        self.assertIn(">แก้ไข</button>", chunk)
        self.assertNotIn("edit primary", chunk)

    def test_03_source_link_mapping(self) -> None:
        chunk = self._prop_actions()
        self.assertIn('propQuickLinkBtn(p.source_url, "ลิงก์ต้นโพส"', chunk)

    def test_04_page_post_link_mapping(self) -> None:
        chunk = self._prop_actions()
        self.assertIn('propQuickLinkBtn(p.post_pages_url, "ลิงก์โพสเพจ"', chunk)

    def test_05_compact_timestamp_format(self) -> None:
        self.assertIn("function formatCompactDateTime", self.html)
        self.assertIn("formatListedDateShort(p.last_listed_at)", self.html)
        self.assertEqual(
            _format_compact_date_time("2026-08-04T11:00:00"), "4/8/26 (11:00AM.)"
        )
        self.assertEqual(
            _format_compact_date_time("2026-08-04T23:05:00"), "4/8/26 (11:05PM.)"
        )
        self.assertEqual(_format_compact_date_time("25/07/2026"), "25/7/26")
        self.assertEqual(
            _format_compact_date_time("2026-07-20 04:02"), "20/7/26 (4:02AM.)"
        )
        fn = self.html.split("function formatCompactDateTime")[1].split(
            "function formatListedDateShort"
        )[0]
        self.assertIn("AM", fn)
        self.assertIn("PM", fn)

    def test_06_bottom_nav_queue_preserved(self) -> None:
        nav = self.html.split('id="mobile-nav"')[1].split("</nav>")[0]
        self.assertIn('data-view="queue"', nav)
        self.assertIn("รอโพสต์", nav)

    # --- WAITING ---
    def test_07_waiting_actions(self) -> None:
        chunk = self._render_queue()
        self.assertIn('data-qact="edit"', chunk)
        self.assertIn(">เพิ่มโพส</button>", chunk)
        self.assertIn(">เสร็จ</button>", chunk)
        self.assertIn(">ลบ</button>", chunk)

    def test_08_no_linking_workflow_controls(self) -> None:
        chunk = self._render_queue()
        self.assertNotIn("เชื่อมทรัพย์", chunk)
        self.assertNotIn("แก้ไขคิว", chunk)
        self.assertNotIn("แก้ไขทรัพย์", chunk)
        self.assertNotIn('data-qact="link"', chunk)

    def test_09_unlinked_edit_enabled(self) -> None:
        chunk = self._render_queue()
        self.assertNotIn("disabled", chunk)
        self.assertNotIn("property_id", chunk)

    def test_10_edit_uses_queue_id_full_form(self) -> None:
        act = self.html.split('if (act === "edit" || act === "edit-queue")')[1].split(
            'if (act === "edit-property")'
        )[0]
        self.assertIn("openQueueFormForEdit(id)", act)
        self.assertNotIn("openPropertyEdit", act)
        self.assertIn("function openQueueFormForEdit", self.html)
        self.assertIn("function fillQueueFormFromItem", self.html)
        self.assertIn("__queueFormEditId", self.html)

    def test_11_same_form_fields_as_add(self) -> None:
        form = self._add_form()
        for fid in (
            "queue-source",
            "queue-owner-contact",
            "queue-project",
            "queue-price",
            "queue-queued-at",
            "queue-note",
        ):
            self.assertIn(f'id="{fid}"', form)
        fill = self.html.split("function fillQueueFormFromItem")[1].split(
            "function openQueueAddForm"
        )[0]
        for needle in (
            "queue-source",
            "queue-owner-contact",
            "queue-note",
            "queue-project",
            "queue-price",
            "queue-queued-at",
            "ownerContactFromQueue",
        ):
            self.assertIn(needle, fill)

    def test_12_edit_save_all_add_fields(self) -> None:
        fn = self.html.split("async function addToQueue()")[1].split(
            "async function enqueuePropertyToWaitPost"
        )[0]
        self.assertIn("__queueFormEditId", fn)
        self.assertIn('apiPost("/api/queue/update"', fn)
        for key in (
            "source_url",
            "owner_contact",
            "note",
            "project",
            "price",
            "queued_at",
        ):
            self.assertIn(key, fn)
        self.assertNotIn("/api/hub/catalog", fn)
        self.assertNotIn("reloadPreviewData", fn)

    def test_13_queue_compact_timestamp(self) -> None:
        chunk = self._render_queue()
        self.assertIn("formatCompactDateTime(item.created_at || item.queued_at", chunk)

    def test_14_assets_z14(self) -> None:
        self.assertIn("mobile-operations.css?v=z14", self.html)
        self.assertIn("mobile-operations.js?v=z14", self.html)

    def test_15_queue_update_persists_all_fields_no_property_mutation(self) -> None:
        from src.hub.queue_store import update_item, load_queue

        tmp = Path(tempfile.mkdtemp(prefix="z1312_"))
        props_path = tmp / "properties.json"
        projects_path = tmp / "projects.json"
        props_blob = json.dumps(
            [
                {
                    "id": "prop-a",
                    "code": "A1",
                    "notes": "property permanent",
                    "source_url": "https://facebook.com/orig",
                }
            ]
        )
        projects_blob = json.dumps([{"id": "p1", "canonical_name": "Demo"}])
        props_path.write_text(props_blob, encoding="utf-8")
        projects_path.write_text(projects_blob, encoding="utf-8")
        (tmp / "wait_post_queue.json").write_text(
            json.dumps(
                {
                    "items": [
                        {
                            "id": "q1",
                            "status": "pending",
                            "source_url": "https://facebook.com/a",
                            "url": "https://facebook.com/a",
                            "owner_contact": "0811111111",
                            "note": "n1",
                            "project": "Proj A",
                            "price": "10000",
                            "queued_at": "2026-08-01",
                            "created_at": "2026-08-01 11:00",
                            "created_ts": 1,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            updated = update_item(
                "q1",
                source_url="https://facebook.com/b",
                owner_contact="0822222222",
                note="n2",
                project="Proj B",
                price="20000",
                queued_at="2026-08-04",
            )
            items = load_queue()
        self.assertEqual(updated["source_url"], "https://facebook.com/b")
        self.assertEqual(updated["owner_contact"], "0822222222")
        self.assertEqual(updated["note"], "n2")
        self.assertEqual(updated["project"], "Proj B")
        self.assertEqual(updated["price"], "20000")
        self.assertEqual(str(updated["queued_at"])[:10], "2026-08-04")
        self.assertEqual(items[0]["note"], "n2")
        self.assertEqual(props_path.read_text(encoding="utf-8"), props_blob)
        self.assertEqual(projects_path.read_text(encoding="utf-8"), projects_blob)

    def test_16_co_agent_privacy(self) -> None:
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
