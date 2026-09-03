#!/usr/bin/env python3
"""Phase Y owner review pilot tests — offline only."""

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

from src.hub.master_review_store import (  # noqa: E402
    MAX_MARKETPLACE_AREAS,
    MasterReviewError,
    PILOT_PROJECT_IDS,
    apply_decisions_to_items,
    build_review_queue,
    decisions_log_path,
    export_promotion_candidate,
    filter_items,
    load_crosswalk_rows,
    pilot_project_ids,
    pilot_selection,
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

PHASE_W_HASHES = {
    "live-project-crosswalk.json": "9c7eba7f1d44354867efc2fa4c01e3524549c442efa244b07c653398b4dc3602",
}


class PhaseYOwnerReviewPilotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.data_dir = Path(self._tmp) / "review_data"
        self.data_dir.mkdir()
        self.fixture = ROOT / "data_fixtures" / "master_review" / "sample_crosswalk.json"
        self.source_hash = hashlib.sha256(self.fixture.read_bytes()).hexdigest()
        os.environ["MASTER_REVIEW_DATA_DIR"] = str(self.data_dir)
        os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(self.fixture)

    def tearDown(self):
        os.environ.pop("MASTER_REVIEW_DATA_DIR", None)
        os.environ.pop("MASTER_REVIEW_SOURCE_PATH", None)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_real_phase_w_source_loads_readonly(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        before = PHASE_W_BACKUP.read_bytes()
        rows, h = load_crosswalk_rows(PHASE_W_BACKUP)
        after = PHASE_W_BACKUP.read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(h, PHASE_W_HASHES["live-project-crosswalk.json"])
        self.assertGreater(len(rows), 2000)

    def test_queue_counts_correct(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        rows, h = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=h)
        area = sum(1 for i in items if i["review_type"] == "AREA_REVIEW")
        pantip = sum(1 for i in items if i["review_type"] == "PANTIP_ONLY_REVIEW")
        self.assertEqual(area, 134)
        self.assertEqual(pantip, 19)
        self.assertEqual(len(items), 153)
        top = filter_items(items, top50_only=True)
        self.assertEqual(sum(1 for i in top if i["review_type"] == "AREA_REVIEW"), 50)

    def test_pilot_selection_deterministic(self):
        a = pilot_project_ids()
        b = pilot_project_ids()
        self.assertEqual(a, b)
        self.assertEqual(len(a), 8)
        sel = pilot_selection()
        self.assertEqual(len(sel), 8)
        for entry in sel:
            self.assertTrue(entry["reason_th"])

    def test_semantic_dimensions_remain_distinct(self):
        items = build_review_queue()
        area = next(i for i in items if i["review_type"] == "AREA_REVIEW")
        cur = area["current_value"]
        prop = area["proposed_value"]
        self.assertIn("zone_dimensions", cur)
        self.assertIn("dimension_note_th", cur)
        self.assertIn("dimension_note_th", prop)
        self.assertNotEqual(cur.get("semantic_kind"), prop.get("semantic_kind"))

    def test_multi_area_assignments_preserved(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        rows, h = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=h)
        multi = [
            i
            for i in items
            if len((i.get("proposed_value") or {}).get("marketplace_area_relations") or []) >= 2
        ]
        self.assertTrue(multi)
        rels = multi[0]["proposed_value"]["marketplace_area_relations"]
        self.assertTrue(all("role" in r for r in rels))

    def test_max_three_marketplace_areas_enforced(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        rows, h = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=h)
        for item in items:
            rels = (item.get("proposed_value") or {}).get("marketplace_area_relations") or []
            self.assertLessEqual(len(rels), MAX_MARKETPLACE_AREAS)

    def test_primary_secondary_edge_preserved(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        rows, h = load_crosswalk_rows(PHASE_W_BACKUP)
        items = build_review_queue(rows, source_hash=h)
        pid = "ec5214c9-c9fb-5ca5-98fb-852703044e4a"
        item = next(i for i in items if i["project_id"] == pid)
        roles = {r["role"] for r in item["proposed_value"]["marketplace_area_relations"]}
        self.assertIn("PRIMARY", roles)
        self.assertIn("SECONDARY", roles)
        self.assertIn("EDGE", roles)

    def test_umbrella_compatibility_does_not_flatten(self):
        items = build_review_queue()
        for item in items:
            prop = item.get("proposed_value") or {}
            if prop.get("marketplace_area_relations"):
                self.assertIsInstance(prop["marketplace_area_relations"], list)
                self.assertNotIn("zone =", json.dumps(prop, ensure_ascii=False))

    def test_test_only_decisions_separated(self):
        items = build_review_queue()
        item = items[0]
        record_decision(
            review_item_id=item["review_item_id"],
            project_id=item["project_id"],
            new_status="DEFERRED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            items=items,
            test_only=True,
        )
        self.assertFalse(decisions_log_path(test_only=False).exists())
        self.assertTrue(decisions_log_path(test_only=True).exists())
        owner_map = apply_decisions_to_items(items, test_only=False)
        self.assertEqual(owner_map[0]["decision"]["status"], "PENDING")

    def test_append_only_decision_history(self):
        items = build_review_queue()
        item = items[0]
        record_decision(
            review_item_id=item["review_item_id"],
            project_id=item["project_id"],
            new_status="DEFERRED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            items=items,
            test_only=True,
        )
        record_decision(
            review_item_id=item["review_item_id"],
            project_id=item["project_id"],
            new_status="APPROVED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_EVIDENCE_ACCEPTED",
            items=items,
            test_only=True,
        )
        log = decisions_log_path(test_only=True).read_text(encoding="utf-8")
        lines = [ln for ln in log.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn('"test_only": true', lines[0])

    def test_stale_snapshot_rejected(self):
        items = build_review_queue()
        with self.assertRaises(MasterReviewError) as ctx:
            record_decision(
                review_item_id=items[0]["review_item_id"],
                project_id=items[0]["project_id"],
                new_status="APPROVED",
                actor="TEST_ONLY",
                expected_source_snapshot_hash="deadbeef",
                reason="REFERENCE_EVIDENCE_ACCEPTED",
                items=items,
                test_only=True,
            )
        self.assertEqual(ctx.exception.code, "stale_snapshot")

    def test_promotion_export_approved_only(self):
        items = build_review_queue()
        a, b, c = items[0], items[1], items[2]
        record_decision(
            review_item_id=a["review_item_id"],
            project_id=a["project_id"],
            new_status="APPROVED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_EVIDENCE_ACCEPTED",
            items=items,
            test_only=True,
        )
        record_decision(
            review_item_id=b["review_item_id"],
            project_id=b["project_id"],
            new_status="REJECTED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_INCORRECT",
            items=items,
            test_only=True,
        )
        record_decision(
            review_item_id=c["review_item_id"],
            project_id=c["project_id"],
            new_status="DEFERRED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            items=items,
            test_only=True,
        )
        enriched = apply_decisions_to_items(items, test_only=True)
        payload = export_promotion_candidate(enriched, test_only=True)
        self.assertEqual(payload["decision_count"], 1)
        self.assertEqual(payload["decisions"][0]["review_item_id"], a["review_item_id"])
        self.assertTrue(payload["test_only"])

    def test_no_projects_json_mutation(self):
        projects_path = ROOT / "data" / "projects.json"
        before = hashlib.sha256(projects_path.read_bytes()).hexdigest()
        build_review_queue()
        record_decision(
            review_item_id=build_review_queue()[0]["review_item_id"],
            project_id=build_review_queue()[0]["project_id"],
            new_status="APPROVED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_EVIDENCE_ACCEPTED",
            items=build_review_queue(),
            test_only=True,
        )
        after = hashlib.sha256(projects_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_no_properties_json_mutation(self):
        props_path = ROOT / "data" / "properties.json"
        if not props_path.is_file():
            self.skipTest("no properties.json in repo")
        before = hashlib.sha256(props_path.read_bytes()).hexdigest()
        export_promotion_candidate()
        after = hashlib.sha256(props_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_no_production_write_code_path(self):
        store_path = ROOT / "src" / "hub" / "master_review_store.py"
        text = store_path.read_text(encoding="utf-8")
        self.assertNotIn("/app/data", text)
        self.assertNotIn("fly deploy", text.lower())

    def test_future_preview_present(self):
        items = build_review_queue()
        item = items[0]
        fp = item.get("future_preview_th") or {}
        self.assertEqual(fp.get("title_th"), "ถ้าอนุมัติข้อเสนอนี้")
        self.assertTrue(fp.get("lines_th"))

    def test_pantip_only_notice(self):
        items = build_review_queue()
        pantip = next(i for i in items if i["review_type"] == "PANTIP_ONLY_REVIEW")
        notice = pantip["current_value"].get("pantip_only_notice_th", "")
        self.assertIn("Canonical Master", notice)

    def test_pilot_filter(self):
        if not PHASE_W_BACKUP.is_file():
            self.skipTest("Phase W backup not on this machine")
        os.environ["MASTER_REVIEW_SOURCE_PATH"] = str(PHASE_W_BACKUP)
        rows, h = load_crosswalk_rows()
        items = build_review_queue(rows, source_hash=h)
        pilot = filter_items(items, pilot_only=True)
        self.assertEqual(len(pilot), len(PILOT_PROJECT_IDS))
        self.assertEqual({i["project_id"] for i in pilot}, set(PILOT_PROJECT_IDS))

    def test_decision_pilot_transitions(self):
        """APPROVE, REJECT, DEFER, DEFER→APPROVE, APPROVE→DEFER."""
        items = build_review_queue()
        targets = items[:3]
        record_decision(
            review_item_id=targets[0]["review_item_id"],
            project_id=targets[0]["project_id"],
            new_status="APPROVED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_EVIDENCE_ACCEPTED",
            items=items,
            test_only=True,
        )
        record_decision(
            review_item_id=targets[1]["review_item_id"],
            project_id=targets[1]["project_id"],
            new_status="REJECTED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_INCORRECT",
            items=items,
            test_only=True,
        )
        record_decision(
            review_item_id=targets[2]["review_item_id"],
            project_id=targets[2]["project_id"],
            new_status="DEFERRED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            items=items,
            test_only=True,
        )
        record_decision(
            review_item_id=targets[2]["review_item_id"],
            project_id=targets[2]["project_id"],
            new_status="APPROVED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            reason="OWNER_KNOWLEDGE",
            items=items,
            test_only=True,
        )
        record_decision(
            review_item_id=targets[0]["review_item_id"],
            project_id=targets[0]["project_id"],
            new_status="DEFERRED",
            actor="TEST_ONLY",
            expected_source_snapshot_hash=self.source_hash,
            items=items,
            test_only=True,
        )
        enriched = apply_decisions_to_items(items, test_only=True)
        statuses = {i["review_item_id"]: i["decision"]["status"] for i in enriched}
        self.assertEqual(statuses[targets[0]["review_item_id"]], "DEFERRED")
        self.assertEqual(statuses[targets[1]["review_item_id"]], "REJECTED")
        self.assertEqual(statuses[targets[2]["review_item_id"]], "APPROVED")


if __name__ == "__main__":
    unittest.main()
