#!/usr/bin/env python3
"""Phase H Facebook operator reconciliation tests (offline)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BANGKOK = ZoneInfo("Asia/Bangkok")


class PhaseHFacebookReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.store_path = Path(self._td.name) / "jobs.json"
        import src.hub.group_post_publish_store as store

        self.store = store
        self._p = mock.patch.object(store, "STORE_PATH", self.store_path)
        self._p.start()
        self.store_path.write_text(
            json.dumps({"jobs": [], "group_last_post": {}}, indent=2), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self._p.stop()
        self._td.cleanup()

    def _add(self, **kw) -> dict:
        now = datetime.now(tz=BANGKOK)
        job = {
            "id": kw.pop("id", self.store._new_id()),
            "property_id": "pid-1",
            "property_code": "RXT1",
            "group_url": "https://www.facebook.com/groups/g1",
            "group_name": "G1",
            "fb_account_id": "a1",
            "agent_id": "owner",
            "caption": "c",
            "image_urls": [],
            "status": "needs_reconcile",
            "next_post_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "posted_at": "",
            "permalink": "",
            "error": "ambiguous",
            "action": "",
            "detail": "lost callback",
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "campaign_id": "camp",
            "idempotency_key": "idem-abc",
            "attempt_id": "att1",
            "attempt_count": 2,
            "claimed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "external_action_started_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "last_error_class": "ambiguous_external_result",
        }
        job.update(kw)
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        data["jobs"].append(job)
        self.store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return job

    def test_01_needs_reconcile_listed(self) -> None:
        j = self._add()
        items = self.store.list_needs_reconcile()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], j["id"])

    def test_02_pending_not_listed(self) -> None:
        self._add(status="pending", last_error_class="")
        self.assertEqual(self.store.list_needs_reconcile(), [])

    def test_03_confirm_posted_requires_job_id(self) -> None:
        with self.assertRaises(self.store.ReconcileError) as ctx:
            self.store.reconcile_publish_job("", action="confirm_posted", external_post_url="https://fb/p/1")
        self.assertEqual(ctx.exception.http_status, 400)

    def test_04_confirm_posted_preserves_property_id(self) -> None:
        j = self._add(property_id="pid-keep")
        out = self.store.reconcile_publish_job(
            j["id"], action="confirm_posted", external_post_url="https://fb/p/1", operator="op"
        )
        self.assertEqual(out["property_id"], "pid-keep")

    def test_05_confirm_posted_preserves_idempotency_key(self) -> None:
        j = self._add(idempotency_key="idem-keep")
        out = self.store.reconcile_publish_job(
            j["id"], action="confirm_posted", external_post_url="https://fb/p/1"
        )
        self.assertEqual(out["idempotency_key"], "idem-keep")

    def test_06_confirm_posted_stores_evidence(self) -> None:
        j = self._add()
        out = self.store.reconcile_publish_job(
            j["id"], action="confirm_posted", external_post_url="https://fb/p/evidence"
        )
        self.assertEqual(out["external_post_url"], "https://fb/p/evidence")
        self.assertEqual(out["permalink"], "https://fb/p/evidence")

    def test_07_confirm_posted_to_posted(self) -> None:
        j = self._add()
        out = self.store.reconcile_publish_job(
            j["id"], action="confirm_posted", external_post_url="https://fb/p/1"
        )
        self.assertEqual(out["status"], "posted")
        self.assertTrue(out.get("reconciled_at"))
        self.assertEqual(out.get("reconciliation_action"), "confirm_posted")

    def test_08_duplicate_confirm_posted_harmless(self) -> None:
        j = self._add()
        self.store.reconcile_publish_job(
            j["id"], action="confirm_posted", external_post_url="https://fb/p/1"
        )
        again = self.store.reconcile_publish_job(
            j["id"], action="confirm_posted", external_post_url="https://fb/p/OTHER"
        )
        self.assertEqual(again["status"], "posted")
        self.assertEqual(again["permalink"], "https://fb/p/1")

    def test_09_confirm_not_posted_to_pending(self) -> None:
        j = self._add()
        out = self.store.reconcile_publish_job(j["id"], action="confirm_not_posted", operator="op")
        self.assertEqual(out["status"], "pending")
        self.assertEqual(out["reconciliation_action"], "confirm_not_posted")

    def test_10_retry_only_after_explicit_action(self) -> None:
        j = self._add()
        # Still needs_reconcile — not claimable
        claimed, _ = self.store.claim_due_for_publish(limit=5)
        self.assertEqual(claimed, [])
        self.store.reconcile_publish_job(j["id"], action="confirm_not_posted")
        with mock.patch("src.hub.project_store.load_properties", return_value=[
            {"id": "pid-1", "code": "RXT1", "project_id": "p1"}
        ]):
            claimed2, _ = self.store.claim_due_for_publish(limit=5)
        self.assertEqual(len(claimed2), 1)

    def test_11_cancel_to_cancelled(self) -> None:
        j = self._add()
        out = self.store.reconcile_publish_job(j["id"], action="cancel")
        self.assertEqual(out["status"], "cancelled")

    def test_12_invalid_transition_rejected(self) -> None:
        j = self._add(status="pending")
        with self.assertRaises(self.store.ReconcileError) as ctx:
            self.store.reconcile_publish_job(j["id"], action="confirm_not_posted")
        self.assertEqual(ctx.exception.http_status, 409)

    def test_13_missing_job_rejected(self) -> None:
        with self.assertRaises(self.store.ReconcileError) as ctx:
            self.store.reconcile_publish_job("missing", action="cancel")
        self.assertEqual(ctx.exception.http_status, 404)

    def test_14_property_code_not_mutation_identity(self) -> None:
        # reconcile API only accepts job_id — property_code ignored if passed as id incorrectly
        j = self._add(property_code="DUPCODE")
        with self.assertRaises(self.store.ReconcileError):
            self.store.reconcile_publish_job("DUPCODE", action="cancel")
        self.assertEqual(self.store.get_job(j["id"])["status"], "needs_reconcile")

    def test_15_confirm_posted_requires_evidence(self) -> None:
        j = self._add()
        with self.assertRaises(self.store.ReconcileError) as ctx:
            self.store.reconcile_publish_job(j["id"], action="confirm_posted", external_post_url="")
        self.assertEqual(ctx.exception.code, "missing_evidence")

    def test_16_keep_unresolved_no_mutation(self) -> None:
        j = self._add()
        out = self.store.reconcile_publish_job(j["id"], action="keep_unresolved")
        self.assertEqual(out["status"], "needs_reconcile")
        self.assertFalse(out.get("reconciled_at"))

    def test_17_reconciled_posted_not_auto_claimed(self) -> None:
        j = self._add()
        self.store.reconcile_publish_job(
            j["id"], action="confirm_posted", external_post_url="https://fb/p/1"
        )
        with mock.patch("src.hub.project_store.load_properties", return_value=[
            {"id": "pid-1", "code": "RXT1"}
        ]):
            claimed, _ = self.store.claim_due_for_publish(limit=5)
        self.assertEqual(claimed, [])

    def test_18_no_facebook_network_in_module(self) -> None:
        src = Path(self.store.__file__).read_text(encoding="utf-8")
        self.assertNotIn("facebook.com/api", src.lower())
        self.assertIn("Never posts to Facebook", self.store.reconcile_publish_job.__doc__)

    def test_19_audit_metadata_recorded(self) -> None:
        j = self._add()
        out = self.store.reconcile_publish_job(
            j["id"], action="cancel", operator="alice"
        )
        self.assertEqual(out["reconciled_by"], "alice")
        self.assertTrue(out["reconciled_at"])


if __name__ == "__main__":
    unittest.main()
