#!/usr/bin/env python3
"""Phase Y.2 owner review human-readable area labels — offline only."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.hub.marketplace_area_lookup import (  # noqa: E402
    UNNAMED_AREA_LABEL_TH,
    build_approval_gate,
    clear_lookup_cache,
    enrich_area_relation,
    enrich_area_relations,
    role_label_th,
)
from src.hub.master_review_store import (  # noqa: E402
    MasterReviewError,
    apply_decisions_to_items,
    build_review_queue,
    export_promotion_candidate,
    load_crosswalk_rows,
    record_decision,
    source_crosswalk_path,
)

PHASE_W_BACKUP = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
AREA_LOOKUP = ROOT / "data_fixtures" / "master_review" / "marketplace_area_names.json"
KNOWN_AREA_ID = "rxa_23511c474115de48ab6b29971512a66d"


class PhaseY2OwnerReviewLabelsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.data_dir = Path(self._tmp) / "review_data"
        self.data_dir.mkdir()
        os.environ["MASTER_REVIEW_DATA_DIR"] = str(self.data_dir)
        os.environ["MASTER_REVIEW_AREA_LOOKUP_PATH"] = str(AREA_LOOKUP)
        clear_lookup_cache()

    def tearDown(self):
        os.environ.pop("MASTER_REVIEW_DATA_DIR", None)
        os.environ.pop("MASTER_REVIEW_AREA_LOOKUP_PATH", None)
        clear_lookup_cache()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_trusted_area_lookup_thai_name(self):
        rel = enrich_area_relation(
            {"area_id": KNOWN_AREA_ID, "role": "PRIMARY", "confidence": "HIGH"}
        )
        self.assertEqual(rel["area_name_th"], "อโศก")
        self.assertEqual(rel["display_name_th"], "อโศก")
        self.assertTrue(rel["has_trusted_name"])

    def test_area_id_preserved(self):
        rel = enrich_area_relation(
            {"area_id": KNOWN_AREA_ID, "role": "SECONDARY", "confidence": "MEDIUM"}
        )
        self.assertEqual(rel["area_id"], KNOWN_AREA_ID)
        self.assertEqual(rel["role"], "SECONDARY")

    def test_unknown_area_not_guessed(self):
        rel = enrich_area_relation(
            {"area_id": "rxa_deadbeefdeadbeefdeadbeefdeadbeef", "role": "PRIMARY", "confidence": "LOW"}
        )
        self.assertFalse(rel["has_trusted_name"])
        self.assertEqual(rel["area_name_th"], "")
        self.assertEqual(rel["display_name_th"], UNNAMED_AREA_LABEL_TH)
        self.assertNotIn("deadbeef", rel["display_name_th"])

    def test_unknown_area_safe_placeholder(self):
        rel = enrich_area_relation({"area_id": "rxa_missing", "role": "EDGE", "confidence": "LOW"})
        self.assertEqual(rel["display_name_th"], UNNAMED_AREA_LABEL_TH)

    def test_approve_blocked_when_area_name_missing(self):
        item = {
            "review_type": "AREA_REVIEW",
            "proposed_value": {
                "semantic_kind": "MARKETPLACE_AREA",
                "marketplace_area_relations": enrich_area_relations(
                    [{"area_id": "rxa_missing", "role": "PRIMARY", "confidence": "HIGH"}]
                ),
            },
        }
        gate = build_approval_gate(item)
        self.assertFalse(gate["can_approve"])
        self.assertIn("ยังไม่ควรอนุมัติ", gate["blocked_reason_th"])

    def test_defer_allowed_when_area_name_missing(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
        rows, source_hash = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=source_hash)
        item = next(i for i in items if i["project_id"] == "ec5214c9-c9fb-5ca5-98fb-852703044e4a")
        item["proposed_value"]["marketplace_area_relations"] = enrich_area_relations(
            [{"area_id": "rxa_missing", "role": "PRIMARY", "confidence": "HIGH"}]
        )
        item["approval_gate"] = build_approval_gate(item)
        event = record_decision(
            review_item_id=item["review_item_id"],
            project_id=item["project_id"],
            new_status="DEFERRED",
            actor="tester",
            expected_source_snapshot_hash=source_hash,
            items=[item],
            test_only=True,
        )
        self.assertEqual(event["new_status"], "DEFERRED")

    def test_role_labels_thai(self):
        self.assertEqual(role_label_th("PRIMARY"), "ทำเลหลัก")
        self.assertEqual(role_label_th("SECONDARY"), "ทำเลรองที่เกี่ยวข้อง")
        self.assertEqual(role_label_th("EDGE"), "ทำเลบริเวณรอยต่อ")

    def test_canonical_roles_preserved(self):
        rels = enrich_area_relations(
            [
                {"area_id": KNOWN_AREA_ID, "role": "PRIMARY", "confidence": "HIGH"},
                {"area_id": "rxa_40e7f886c58c36f4f1631848e93c3a0b", "role": "SECONDARY", "confidence": "HIGH"},
                {"area_id": "rxa_23511c474115de48ab6b29971512a66d", "role": "EDGE", "confidence": "MEDIUM"},
            ]
        )
        self.assertEqual([r["role"] for r in rels], ["PRIMARY", "SECONDARY", "EDGE"])
        self.assertEqual(rels[0]["role_label_th"], "ทำเลหลัก")

    def test_multi_area_order_preserved(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
        rows, source_hash = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=source_hash)
        item = next(i for i in items if i["project_id"] == "ec5214c9-c9fb-5ca5-98fb-852703044e4a")
        rels = item["proposed_value"]["marketplace_area_relations"]
        self.assertEqual(len(rels), 3)
        self.assertEqual(rels[0]["role"], "PRIMARY")
        self.assertEqual(rels[1]["role"], "SECONDARY")
        self.assertEqual(rels[2]["role"], "EDGE")
        self.assertTrue(all(r["has_trusted_name"] for r in rels))

    def test_promotion_export_uses_canonical_ids_roles(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
        rows, source_hash = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=source_hash)
        item = items[0]
        record_decision(
            review_item_id=item["review_item_id"],
            project_id=item["project_id"],
            new_status="APPROVED",
            actor="tester",
            expected_source_snapshot_hash=source_hash,
            reason="REFERENCE_EVIDENCE_ACCEPTED",
            items=items,
            test_only=True,
        )
        items = apply_decisions_to_items(items, test_only=True)
        export = export_promotion_candidate(items=items, test_only=True)
        rel = export["decisions"][0]["marketplace_area_relations"][0]
        self.assertTrue(str(rel["area_id"]).startswith("rxa_"))
        self.assertIn(rel["role"], {"PRIMARY", "SECONDARY", "EDGE"})

    def test_phase_w_source_not_mutated(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        before = PHASE_W_BACKUP.read_bytes()
        os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
        rows, source_hash = load_crosswalk_rows(PHASE_W_BACKUP)
        build_review_queue(rows, source_hash=source_hash)
        after = PHASE_W_BACKUP.read_bytes()
        self.assertEqual(before, after)

    def test_projects_json_not_mutated_by_y2_code(self):
        projects = ROOT / "data" / "projects.json"
        before = hashlib.sha256(projects.read_bytes()).hexdigest()
        if PHASE_W_BACKUP.is_file():
            os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
            rows, source_hash = load_crosswalk_rows(PHASE_W_BACKUP)
            build_review_queue(rows, source_hash=source_hash)
        after = hashlib.sha256(projects.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_properties_json_not_mutated_by_y2_code(self):
        properties = ROOT / "data" / "properties.json"
        before = hashlib.sha256(properties.read_bytes()).hexdigest()
        if PHASE_W_BACKUP.is_file():
            os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
            rows, source_hash = load_crosswalk_rows(PHASE_W_BACKUP)
            build_review_queue(rows, source_hash=source_hash)
        after = hashlib.sha256(properties.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_record_decision_blocks_approve_when_unnamed(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
        rows, source_hash = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=source_hash)
        item = items[0]
        item["proposed_value"]["marketplace_area_relations"] = enrich_area_relations(
            [{"area_id": "rxa_missing", "role": "PRIMARY", "confidence": "HIGH"}]
        )
        item["approval_gate"] = build_approval_gate(item)
        with self.assertRaises(MasterReviewError) as ctx:
            record_decision(
                review_item_id=item["review_item_id"],
                project_id=item["project_id"],
                new_status="APPROVED",
                actor="tester",
                expected_source_snapshot_hash=source_hash,
                reason="REFERENCE_EVIDENCE_ACCEPTED",
                items=[item],
                test_only=True,
            )
        self.assertEqual(ctx.exception.code, "approval_blocked")

    def test_real_phase_w_area_coverage_complete(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
        rows, source_hash = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=source_hash)
        area_items = [i for i in items if i["review_type"] == "AREA_REVIEW"]
        unnamed = 0
        for item in area_items:
            for rel in item["proposed_value"]["marketplace_area_relations"]:
                if not rel.get("has_trusted_name"):
                    unnamed += 1
        self.assertEqual(unnamed, 0)
        self.assertTrue(all(i["approval_gate"]["can_approve"] for i in area_items))

    def test_future_preview_uses_human_names(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
        rows, source_hash = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=source_hash)
        item = next(i for i in items if i["project_id"] == "ec5214c9-c9fb-5ca5-98fb-852703044e4a")
        lines = "\n".join(item["future_preview_th"]["lines_th"])
        self.assertIn("อโศก", lines)
        self.assertNotIn("7f24e6abd51497eb", lines)


if __name__ == "__main__":
    unittest.main()
