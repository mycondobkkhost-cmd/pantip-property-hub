#!/usr/bin/env python3
"""Phase Z13.8 — wait_post_queue property_id linkage safety."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class PhaseZ138WaitQueueLinkage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        cls.server = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")
        cls.store = (ROOT / "src" / "hub" / "queue_store.py").read_text(encoding="utf-8")

    def test_01_add_job_accepts_property_id(self) -> None:
        self.assertIn("property_id: str = \"\"", self.store)
        self.assertIn("\"property_id\": property_id", self.store)
        self.assertIn("validate_property_id", self.store)

    def test_02_api_queue_add_passes_property_id(self) -> None:
        self.assertIn("property_id = (body.get(\"property_id\")", self.server)
        self.assertIn("property_id=property_id", self.server)

    def test_03_ui_persists_property_id_and_prop_queue_action(self) -> None:
        self.assertIn('id="queue-property-id"', self.html)
        self.assertIn("body.property_id = propertyId", self.html)
        self.assertIn("enqueuePropertyToWaitPost", self.html)
        self.assertIn('data-prop-queue="', self.html)

    def test_04_queue_edit_simple_property_link_backend_kept(self) -> None:
        # Waiting-page Edit is queue-note; property_id writers/backends remain.
        self.assertIn('data-qact="edit"', self.html)
        self.assertIn("openQueueEditSheet", self.html)
        self.assertIn("openPropertyEdit(pid)", self.html)
        self.assertIn("enqueuePropertyToWaitPost", self.html)

    def test_05_assets_z13_11(self) -> None:
        self.assertIn("mobile-operations.css?v=z13_11", self.html)
        self.assertIn("mobile-operations.js?v=z13_11", self.html)

    def test_06_co_agent_notes_absent(self) -> None:
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
        self.assertNotIn("0812345678", blob)

    def _with_e2e(self, props: list[dict], queue_items: list[dict]):
        tmp = Path(tempfile.mkdtemp(prefix="z138_"))
        (tmp / "properties.json").write_text(json.dumps(props), encoding="utf-8")
        (tmp / "projects.json").write_text(json.dumps([{"id": "p1", "canonical_name": "A"}]), encoding="utf-8")
        (tmp / "wait_post_queue.json").write_text(
            json.dumps({"items": queue_items, "updated_at": "now"}), encoding="utf-8"
        )
        return tmp

    def test_07_existing_property_id_retained(self) -> None:
        from src.hub.queue_store import backfill_queue_property_ids, classify_queue_link

        props = [
            {"id": "a", "code": "C1", "source_url": "https://facebook.com/a", "project_name": "A", "rent_price": "1"},
            {"id": "b", "code": "C1", "source_url": "https://facebook.com/b", "project_name": "A", "rent_price": "2"},
        ]
        item = {"id": "q1", "property_id": "a", "source_url": "https://facebook.com/a"}
        r = classify_queue_link(item, properties=props)
        self.assertEqual(r["category"], "already_linked")
        self.assertEqual(r["property_id"], "a")

        tmp = self._with_e2e(props, [item])
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            s = backfill_queue_property_ids(dry_run=False)
        self.assertEqual(s["already_linked"], 1)
        self.assertEqual(s["changed_ids"], [])

    def test_08_exact_unique_source_links(self) -> None:
        from src.hub.queue_store import add_job, backfill_queue_property_ids, classify_queue_link

        props = [
            {"id": "a", "code": "C1", "source_url": "https://facebook.com/unique-a", "project_name": "A", "rent_price": "1"},
            {"id": "b", "code": "C1", "source_url": "https://facebook.com/other", "project_name": "A", "rent_price": "2"},
        ]
        item = {"id": "q2", "property_id": "", "source_url": "https://facebook.com/unique-a"}
        r = classify_queue_link(item, properties=props)
        self.assertEqual(r["category"], "linked_by_exact_source")
        self.assertEqual(r["property_id"], "a")

        tmp = self._with_e2e(props, [item])
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            s1 = backfill_queue_property_ids(dry_run=True)
            self.assertEqual(len(s1["changed_ids"]), 1)
            s2 = backfill_queue_property_ids(dry_run=False)
            self.assertEqual(s2["linked_by_exact_source"], 1)
            s3 = backfill_queue_property_ids(dry_run=False)
            self.assertEqual(s3["already_linked"], 1)
            self.assertEqual(s3["changed_ids"], [])

            # future writer stores property_id when provided
            job = add_job(
                source_url="https://facebook.com/brand-new",
                property_id="a",
                project="A",
                price="1",
            )
            self.assertEqual(job.get("property_id"), "a")

    def test_09_duplicate_code_does_not_auto_select(self) -> None:
        from src.hub.queue_store import classify_queue_link

        props = [
            {"id": "a", "code": "DUP", "source_url": "https://facebook.com/a", "project_name": "A", "rent_price": "10"},
            {"id": "b", "code": "DUP", "source_url": "https://facebook.com/b", "project_name": "A", "rent_price": "20"},
        ]
        item = {
            "id": "q3",
            "property_id": "",
            "property_code": "DUP",
            "source_url": "https://facebook.com/unknown",
            "project": "A",
            "price": "10",
        }
        r = classify_queue_link(item, properties=props)
        self.assertEqual(r["category"], "ambiguous")
        self.assertEqual(r.get("property_id"), "")

    def test_10_verified_unique_code_migration(self) -> None:
        from src.hub.queue_store import classify_queue_link

        props = [
            {"id": "only", "code": "ONLY1", "source_url": "https://facebook.com/x", "project_name": "Tower", "rent_price": "25000"},
        ]
        item = {
            "id": "q4",
            "property_id": "",
            "property_code": "ONLY1",
            "source_url": "https://facebook.com/nope",
            "project": "Tower",
            "price": "25000",
        }
        r = classify_queue_link(item, properties=props)
        self.assertEqual(r["category"], "linked_by_unique_verified_code")
        self.assertEqual(r["property_id"], "only")

    def test_11_no_match_and_ambiguous_source(self) -> None:
        from src.hub.queue_store import classify_queue_link

        props = [
            {"id": "a", "code": "A", "source_url": "https://facebook.com/same", "project_name": "P", "rent_price": "1"},
            {"id": "b", "code": "B", "source_url": "https://facebook.com/same", "project_name": "P", "rent_price": "2"},
        ]
        amb = classify_queue_link(
            {"id": "q5", "source_url": "https://facebook.com/same"}, properties=props
        )
        self.assertEqual(amb["category"], "ambiguous")
        none = classify_queue_link(
            {"id": "q6", "source_url": "https://facebook.com/zzz"}, properties=props
        )
        self.assertEqual(none["category"], "no_match")

    def test_12_add_job_auto_links_unique_source(self) -> None:
        from src.hub.queue_store import add_job

        props = [
            {"id": "a", "code": "C1", "source_url": "https://facebook.com/auto-unique", "project_name": "A", "rent_price": "1"},
        ]
        tmp = self._with_e2e(props, [])
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            job = add_job(source_url="https://facebook.com/auto-unique", project="A", price="1")
            self.assertEqual(job.get("property_id"), "a")

    def test_13_sheet_import_preserves_property_id_field(self) -> None:
        self.assertIn("prev_pid", self.store)
        self.assertIn("find_unique_property_id_by_source_url(source_url)", self.store)

    def test_14_z13_6_step_nav_still_present(self) -> None:
        js = (ROOT / "hub" / "mobile-operations.js").read_text(encoding="utf-8")
        self.assertIn("ptpGoAddStep", js)
        self.assertIn("ptpResetAddStepNav", js)


if __name__ == "__main__":
    unittest.main()
