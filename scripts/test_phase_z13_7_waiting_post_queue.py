#!/usr/bin/env python3
"""Phase Z13.7 — waiting-to-post queue Edit + property notes + nav shortcut."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PhaseZ137WaitingPostQueue(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        cls.js = (ROOT / "hub" / "mobile-operations.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")
        cls.proj = (ROOT / "src" / "hub" / "public_projection.py").read_text(encoding="utf-8")

    def test_01_queue_edit_is_simple_and_property_edit_path_safe(self) -> None:
        # Z13.12: waiting-page Edit = full Add-equivalent form by queue id.
        self.assertIn('data-qact="edit"', self.html)
        self.assertIn("openQueueFormForEdit", self.html)
        self.assertIn("function resolveQueueLinkedProperty", self.html)
        self.assertIn("openPropertyEdit(pid)", self.html)
        edit_chunk = self.html.split('if (act === "edit" || act === "edit-queue")')[1].split(
            'if (act === "edit-property")'
        )[0]
        self.assertIn("openQueueFormForEdit(id)", edit_chunk)
        self.assertNotIn("property_code", edit_chunk)

    def test_02_duplicate_code_guard_in_resolver(self) -> None:
        # Unique source_url only; never resolve by code field
        chunk = self.html.split("function resolveQueueLinkedProperty")[1].split(
            "function renderQueuePropNotes"
        )[0]
        self.assertIn("hits.length !== 1", chunk)
        self.assertIn("item.property_id", chunk)
        self.assertNotIn("property_code", chunk.replace("property_code.", ""))  # comment ok
        self.assertNotRegex(chunk, re.compile(r"\bproperty_code\b\s*[=!]|\.code\s*==="))
        # Returning display code is fine; matching on it is not
        self.assertIn("hits[0].id", chunk)

    def test_03_notes_from_queue_field(self) -> None:
        self.assertIn("function renderQueuePropNotes", self.html)
        self.assertIn("queueNote", self.html)
        self.assertIn("esc(qNote)", self.html)

    def test_04_notes_html_escaped(self) -> None:
        notes_fn = self.html.split("function renderQueuePropNotes")[1].split("function renderQueue()")[0]
        self.assertIn("esc(qNote)", notes_fn)
        self.assertNotIn("innerHTML = text", notes_fn)

    def test_05_empty_note_omitted(self) -> None:
        notes_fn = self.html.split("function renderQueuePropNotes")[1].split("function renderQueue()")[0]
        self.assertIn('if (!qNote) return "—";', notes_fn)

    def test_06_edit_return_to_queue(self) -> None:
        self.assertIn('editReturnView = "queue"', self.html)
        self.assertIn("editReturnView", self.html)
        self.assertIn("queueScrollBeforeEdit", self.html)
        self.assertIn('var ret = editReturnView || "properties"', self.html)

    def test_07_bottom_nav_five_slots_with_queue(self) -> None:
        nav = self.html.split('id="mobile-nav"')[1].split("</nav>")[0]
        views = re.findall(r'data-view="([^"]+)"', nav)
        self.assertEqual(views, ["properties", "focus", "add", "queue", "more"])
        self.assertNotIn("recheck", views)
        self.assertIn("repeat(5, minmax(0, 1fr))", self.css)

    def test_08_recheck_still_in_more(self) -> None:
        self.assertIn('data-more-view="recheck"', self.html)
        more = self.html.split('id="mobile-more-sheet"')[1].split("mobile-more-backdrop")[0]
        self.assertIn("ติดตาม", more)

    def test_09_mobile_queue_badge_reused(self) -> None:
        self.assertIn('id="mobile-queue-badge"', self.html)
        self.assertIn("updateQueueBadge", self.html)

    def test_10_z13_6_step_nav_still_present(self) -> None:
        self.assertIn("ptpGoAddStep", self.js)
        self.assertIn("ptpResetAddStepNav", self.js)
        self.assertIn("add-zone-source", self.html)

    def test_11_assets_z13_8(self) -> None:
        self.assertIn("mobile-operations.css?v=z13_12", self.html)
        self.assertIn("mobile-operations.js?v=z13_12", self.html)

    def test_12_co_agent_notes_not_in_public_projection(self) -> None:
        # Public projection must keep stripping notes
        self.assertTrue(
            "notes" in self.proj
            and (
                "PRIVATE" in self.proj
                or "strip" in self.proj.lower()
                or "omit" in self.proj.lower()
                or "drop" in self.proj.lower()
                or "forbidden" in self.proj.lower()
                or "exclude" in self.proj.lower()
            )
        )
        from src.hub.public_projection import build_public_catalog_payload

        payload = build_public_catalog_payload(
            [{"id": "proj-1"}],
            [
                {
                    "id": "prop-1",
                    "code": "PTP1",
                    "notes": "ว่างเดือนหน้า",
                    "source_url": "https://facebook.com/x",
                    "owner_phones": ["0812345678"],
                }
            ],
        )
        blob = str(payload)
        self.assertNotIn("ว่างเดือนหน้า", blob)
        self.assertNotIn("owner_phones", blob)
        self.assertNotIn("0812345678", blob)

    def test_13_queue_edit_always_enabled_z13_12(self) -> None:
        self.assertIn('data-qact="edit"', self.html)
        self.assertNotIn('data-qact="edit" disabled', self.html)
        chunk = self.html.split("function renderQueue()")[1].split("async function loadQueue")[0]
        self.assertNotIn("เชื่อมทรัพย์", chunk)
        self.assertIn(">แก้ไข</button>", chunk)

    def test_15_catalog_reload_forces_refetch(self) -> None:
        # After Save, queue must see updated notes — stale PTP_DATA short-circuit is forbidden.
        ready = self.html.split("function isInternalCatalogReady")[1].split(
            "function resetHubCatalogState"
        )[0]
        self.assertIn("__ptpHubInternalCatalogReady", ready)
        reload = self.html.split("async function reloadInternalCatalogAndRefresh")[1].split(
            "function reloadPreviewData"
        )[0]
        self.assertIn("PTP_DATA = null", reload)
        self.assertIn("__ptpHubInternalCatalogReady = false", reload)