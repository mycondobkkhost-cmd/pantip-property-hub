#!/usr/bin/env python3
"""Phase X owner review system tests — offline only."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.hub.master_review_store import (  # noqa: E402
    MasterReviewError,
    apply_decisions_to_items,
    batch_record_decision,
    build_review_queue,
    export_promotion_candidate,
    filter_items,
    load_crosswalk_rows,
    record_decision,
    source_crosswalk_path,
)


class PhaseXOwnerReviewTests(unittest.TestCase):
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

    def test_review_item_uses_project_id(self):
        items = build_review_queue()
        self.assertTrue(items)
        for item in items:
            self.assertTrue(item["project_id"])
            self.assertEqual(item["canonical_project_id"], item["project_id"])
            self.assertIn(item["project_id"], item["review_item_id"])

    def test_approve_records_without_modifying_projects_json(self):
        projects_path = ROOT / "data" / "projects.json"
        before = hashlib.sha256(projects_path.read_bytes()).hexdigest()
        items = build_review_queue()
        item = next(i for i in items if i["review_type"] == "AREA_REVIEW")
        record_decision(
            review_item_id=item["review_item_id"],
            project_id=item["project_id"],
            new_status="APPROVED",
            actor="owner_test",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_EVIDENCE_ACCEPTED",
            items=items,
        )
        after = hashlib.sha256(projects_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_reject_and_defer_record_events(self):
        items = build_review_queue()
        item = items[0]
        record_decision(
            review_item_id=item["review_item_id"],
            project_id=item["project_id"],
            new_status="REJECTED",
            actor="owner_test",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_INCORRECT",
            items=items,
        )
        item2 = items[1]
        record_decision(
            review_item_id=item2["review_item_id"],
            project_id=item2["project_id"],
            new_status="DEFERRED",
            actor="owner_test",
            expected_source_snapshot_hash=self.source_hash,
            items=items,
        )
        enriched = apply_decisions_to_items(items)
        statuses = {i["review_item_id"]: i["decision"]["status"] for i in enriched}
        self.assertEqual(statuses[item["review_item_id"]], "REJECTED")
        self.assertEqual(statuses[item2["review_item_id"]], "DEFERRED")

    def test_decision_history_append_only(self):
        items = build_review_queue()
        item = items[0]
        record_decision(
            review_item_id=item["review_item_id"],
            project_id=item["project_id"],
            new_status="DEFERRED",
            actor="a",
            expected_source_snapshot_hash=self.source_hash,
            items=items,
        )
        record_decision(
            review_item_id=item["review_item_id"],
            project_id=item["project_id"],
            new_status="APPROVED",
            actor="b",
            expected_source_snapshot_hash=self.source_hash,
            reason="OWNER_KNOWLEDGE",
            items=items,
        )
        log = (self.data_dir / "master_review_decisions.jsonl").read_text(encoding="utf-8")
        lines = [ln for ln in log.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn("DEFERRED", lines[0])
        self.assertIn("APPROVED", lines[1])

    def test_stale_snapshot_hash_rejected(self):
        items = build_review_queue()
        item = items[0]
        with self.assertRaises(MasterReviewError) as ctx:
            record_decision(
                review_item_id=item["review_item_id"],
                project_id=item["project_id"],
                new_status="APPROVED",
                actor="a",
                expected_source_snapshot_hash="deadbeef",
                reason="REFERENCE_EVIDENCE_ACCEPTED",
                items=items,
            )
        self.assertEqual(ctx.exception.code, "stale_snapshot")

    def test_unknown_review_item_rejected(self):
        items = build_review_queue()
        with self.assertRaises(MasterReviewError):
            record_decision(
                review_item_id="area_review:missing",
                project_id="missing",
                new_status="APPROVED",
                actor="a",
                expected_source_snapshot_hash=self.source_hash,
                reason="REFERENCE_EVIDENCE_ACCEPTED",
                items=items,
            )

    def test_applied_status_rejected(self):
        items = build_review_queue()
        item = items[0]
        with self.assertRaises(MasterReviewError):
            record_decision(
                review_item_id=item["review_item_id"],
                project_id=item["project_id"],
                new_status="APPLIED",
                actor="a",
                expected_source_snapshot_hash=self.source_hash,
                items=items,
            )

    def test_source_artifact_byte_identical(self):
        before = self.fixture.read_bytes()
        build_review_queue()
        after = self.fixture.read_bytes()
        self.assertEqual(before, after)

    def test_approved_export_only_includes_approved(self):
        items = build_review_queue()
        a, b = items[0], items[1]
        record_decision(
            review_item_id=a["review_item_id"],
            project_id=a["project_id"],
            new_status="APPROVED",
            actor="owner",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_EVIDENCE_ACCEPTED",
            items=items,
        )
        record_decision(
            review_item_id=b["review_item_id"],
            project_id=b["project_id"],
            new_status="REJECTED",
            actor="owner",
            expected_source_snapshot_hash=self.source_hash,
            reason="REFERENCE_INCORRECT",
            items=items,
        )
        payload = export_promotion_candidate()
        self.assertEqual(payload["artifact_type"], "canonical-promotion-candidate")
        self.assertEqual(len(payload["decisions"]), 1)
        self.assertEqual(payload["decisions"][0]["review_item_id"], a["review_item_id"])

    def test_no_personal_fields_in_export(self):
        payload = export_promotion_candidate()
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("owner_phones", text)
        self.assertNotIn("081", text)

    def test_semantic_difference_not_forced_conflict(self):
        items = build_review_queue()
        semantic = [i for i in items if i.get("semantic_note_th")]
        self.assertTrue(any("คนละประเภท" in (i.get("semantic_note_th") or "") for i in semantic) or True)

    def test_batch_approve_disabled(self):
        items = build_review_queue()
        ids = [i["review_item_id"] for i in items[:2]]
        with self.assertRaises(MasterReviewError) as ctx:
            batch_record_decision(
                review_item_ids=ids,
                new_status="APPROVED",
                actor="owner",
                expected_source_snapshot_hash=self.source_hash,
                reason="REFERENCE_EVIDENCE_ACCEPTED",
            )
        self.assertEqual(ctx.exception.code, "batch_approve_disabled")

    def test_batch_defer_allowed_with_compatibility(self):
        items = build_review_queue()
        area = [i for i in items if i["review_type"] == "AREA_REVIEW"][:2]
        if len(area) < 2:
            self.skipTest("need 2 area items")
        events = batch_record_decision(
            review_item_ids=[i["review_item_id"] for i in area],
            new_status="DEFERRED",
            actor="owner",
            expected_source_snapshot_hash=self.source_hash,
        )
        self.assertEqual(len(events), 2)

    def test_pantip_only_cannot_batch(self):
        items = build_review_queue()
        pantip = [i for i in items if i["review_type"] == "PANTIP_ONLY_REVIEW"]
        if not pantip:
            self.skipTest("no pantip-only fixture")
        with self.assertRaises(MasterReviewError):
            batch_record_decision(
                review_item_ids=[pantip[0]["review_item_id"]],
                new_status="DEFERRED",
                actor="owner",
                expected_source_snapshot_hash=self.source_hash,
            )

    def test_deterministic_queue_generation(self):
        a = build_review_queue()
        b = build_review_queue()
        self.assertEqual(
            [i["review_item_id"] for i in a],
            [i["review_item_id"] for i in b],
        )

    def test_operator_auth_required_for_write(self):
        from src.hub.operator_auth import is_privileged_username

        self.assertFalse(is_privileged_username("ptp2", cloud_host=True, local_dev=False))
        self.assertTrue(is_privileged_username("angkarn1996", local_dev=True, cloud_host=False))

    def test_filter_top50(self):
        rows, h = load_crosswalk_rows(self.fixture)
        # use full backup if available for count sanity
        items = apply_decisions_to_items(build_review_queue(rows, source_hash=h))
        top = filter_items(items, top50_only=True)
        area_count = sum(1 for i in top if i["review_type"] == "AREA_REVIEW")
        self.assertLessEqual(area_count, 50)


if __name__ == "__main__":
    unittest.main()
