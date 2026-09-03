#!/usr/bin/env python3
"""Phase G Facebook publish claim/lease + ambiguous-result tests (offline)."""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BANGKOK = ZoneInfo("Asia/Bangkok")


def _props():
    return [
        {"id": "pid-1", "code": "RXT1", "project_id": "proj-1"},
        {"id": "pid-2", "code": "DUP1", "project_id": "proj-1"},
        {"id": "pid-3", "code": "DUP1", "project_id": "proj-2"},
    ]


class PhaseGFacebookPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.store_path = Path(self._td.name) / "group_publish_jobs.json"
        self.props = _props()
        import src.hub.group_post_publish_store as store

        self.store = store
        self._patches = [
            mock.patch.object(store, "STORE_PATH", self.store_path),
            mock.patch("src.hub.project_store.load_properties", return_value=self.props),
        ]
        for p in self._patches:
            p.start()
        self.store_path.write_text(
            json.dumps({"jobs": [], "group_last_post": {}}, indent=2), encoding="utf-8"
        )

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._td.cleanup()

    def _add_job(self, **overrides) -> dict:
        now = datetime.now(tz=BANGKOK)
        job = {
            "id": overrides.pop("id", self.store._new_id()),
            "property_id": "pid-1",
            "property_code": "RXT1",
            "group_url": "https://www.facebook.com/groups/testg",
            "group_name": "Test",
            "fb_account_id": "acc1",
            "agent_id": "owner",
            "caption": "hello",
            "image_urls": [],
            "status": "pending",
            "next_post_at": (now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
            "posted_at": "",
            "permalink": "",
            "error": "",
            "action": "",
            "detail": "",
            "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "campaign_id": "camp1",
            "needs_manual_join": False,
            "join_status": "",
            "idempotency_key": "",
            "attempt_id": "",
            "attempt_count": 0,
            "claimed_at": "",
            "claimed_by": "",
            "lease_until": "",
            "external_action_started_at": "",
            "external_action_confirmed_at": "",
            "last_error_class": "",
        }
        job.update(overrides)
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        data["jobs"].append(job)
        self.store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return job

    def test_01_pending_claimed_once(self) -> None:
        job = self._add_job()
        claimed, blocked = self.store.claim_due_for_publish(limit=5)
        self.assertEqual(blocked, 0)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["id"], job["id"])
        self.assertEqual(claimed[0]["status"], "running")
        self.assertTrue(claimed[0]["attempt_id"])
        self.assertTrue(claimed[0]["idempotency_key"])
        self.assertEqual(claimed[0]["attempt_count"], 1)
        again, _ = self.store.claim_due_for_publish(limit=5)
        self.assertEqual(again, [])

    def test_02_two_workers_cannot_claim_same(self) -> None:
        self._add_job()
        results: list[list] = []
        barrier = threading.Barrier(2)

        def worker() -> None:
            barrier.wait()
            claimed, _ = self.store.claim_due_for_publish(limit=1, claimed_by=threading.current_thread().name)
            results.append(claimed)

        t1 = threading.Thread(target=worker, name="w1")
        t2 = threading.Thread(target=worker, name="w2")
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        winners = [c for c in results if c]
        self.assertEqual(len(winners), 1)
        self.assertEqual(sum(len(c) for c in results), 1)

    def test_03_pre_external_failure_retryable(self) -> None:
        job = self._add_job()
        claimed, _ = self.store.claim_due_for_publish(limit=1)
        aid = claimed[0]["attempt_id"]
        with mock.patch.object(
            self.store.policy,
            "schedule_next_slot",
            return_value=datetime.now(tz=BANGKOK) - timedelta(minutes=1),
        ):
            out = self.store.mark_result(
                job["id"], ok=False, action="pre_external_failed", error="switch", attempt_id=aid
            )
        self.assertEqual(out["status"], "failed")
        again, _ = self.store.claim_due_for_publish(limit=1)
        self.assertEqual(len(again), 1)

    def test_04_external_started_callback_lost_needs_reconcile(self) -> None:
        job = self._add_job()
        claimed, _ = self.store.claim_due_for_publish(limit=1)
        aid = claimed[0]["attempt_id"]
        self.store.mark_external_action_started(job["id"], attempt_id=aid)
        out = self.store.mark_result(
            job["id"], ok=False, ambiguous=True, error="callback lost", attempt_id=aid
        )
        self.assertEqual(out["status"], "needs_reconcile")

    def test_05_needs_reconcile_never_auto_claimed(self) -> None:
        self._add_job(status="needs_reconcile", last_error_class="ambiguous_external_result")
        claimed, _ = self.store.claim_due_for_publish(limit=5)
        self.assertEqual(claimed, [])

    def test_06_posted_never_auto_claimed(self) -> None:
        self._add_job(status="posted", posted_at="2026-01-01 00:00:00")
        claimed, _ = self.store.claim_due_for_publish(limit=5)
        self.assertEqual(claimed, [])

    def test_07_lease_expire_before_external_recovers(self) -> None:
        now = datetime.now(tz=BANGKOK)
        job = self._add_job(
            status="running",
            claimed_at=(now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
            lease_until=(now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
            attempt_id="old",
            external_action_started_at="",
        )
        stats = self.store.recover_expired_leases(now=now)
        self.assertEqual(stats["requeued_pending"], 1)
        self.assertEqual(self.store.get_job(job["id"])["status"], "pending")

    def test_08_lease_expire_after_external_needs_reconcile(self) -> None:
        now = datetime.now(tz=BANGKOK)
        job = self._add_job(
            status="running",
            claimed_at=(now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"),
            lease_until=(now - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
            attempt_id="old",
            external_action_started_at=(now - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
        )
        stats = self.store.recover_expired_leases(now=now)
        self.assertEqual(stats["needs_reconcile"], 1)
        self.assertEqual(self.store.get_job(job["id"])["status"], "needs_reconcile")

    def test_09_duplicate_success_callback_harmless(self) -> None:
        job = self._add_job()
        claimed, _ = self.store.claim_due_for_publish(limit=1)
        aid = claimed[0]["attempt_id"]
        self.store.mark_result(job["id"], ok=True, permalink="https://fb/p/1", attempt_id=aid)
        again = self.store.mark_result(job["id"], ok=True, permalink="https://fb/p/OTHER", attempt_id=aid)
        self.assertEqual(again["status"], "posted")
        self.assertEqual(again["permalink"], "https://fb/p/1")

    def test_10_failure_cannot_reopen_posted(self) -> None:
        job = self._add_job()
        claimed, _ = self.store.claim_due_for_publish(limit=1)
        aid = claimed[0]["attempt_id"]
        self.store.mark_result(job["id"], ok=True, permalink="https://fb/p/1", attempt_id=aid)
        again = self.store.mark_result(job["id"], ok=False, error="nope", attempt_id=aid)
        self.assertEqual(again["status"], "posted")

    def test_11_stale_attempt_callback_ignored(self) -> None:
        job = self._add_job()
        claimed, _ = self.store.claim_due_for_publish(limit=1)
        aid = claimed[0]["attempt_id"]
        self.store.mark_external_action_started(job["id"], attempt_id=aid)
        # Simulate new claim after... actually cannot re-claim while running.
        # Stale attempt: report with wrong attempt_id while still running.
        out = self.store.mark_result(
            job["id"], ok=True, permalink="https://fb/stale", attempt_id="not-current"
        )
        self.assertEqual(out["status"], "running")
        self.assertNotEqual(out.get("permalink"), "https://fb/stale")

    def test_12_duplicate_property_code_blocked(self) -> None:
        self._add_job(property_id="", property_code="DUP1")
        claimed, blocked = self.store.claim_due_for_publish(limit=5)
        self.assertEqual(claimed, [])
        self.assertGreaterEqual(blocked, 1)
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        self.assertEqual(data["jobs"][0]["status"], "needs_reconcile")

    def test_13_property_id_canonical(self) -> None:
        self._add_job(property_id="pid-2", property_code="DUP1")
        claimed, _ = self.store.claim_due_for_publish(limit=1)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["property_id"], "pid-2")

    def test_14_legacy_unsafe_fails_closed(self) -> None:
        self._add_job(property_id="", property_code="MISSING999")
        claimed, blocked = self.store.claim_due_for_publish(limit=1)
        self.assertEqual(claimed, [])
        self.assertGreaterEqual(blocked, 1)
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        self.assertEqual(data["jobs"][0]["status"], "needs_reconcile")


if __name__ == "__main__":
    unittest.main()
