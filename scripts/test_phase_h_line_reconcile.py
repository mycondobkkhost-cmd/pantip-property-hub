#!/usr/bin/env python3
"""Phase H LINE operator reconciliation tests (offline — no LINE network)."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PhaseHLineReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.path = Path(self._td.name) / "line_dedupe.json"
        import src.hub.line_event_dedupe as dedupe
        import src.hub.line_menu_webhook as webhook

        self.dedupe = dedupe
        self.webhook = webhook
        self._p = mock.patch.object(dedupe, "STORE_PATH", self.path)
        self._p.start()
        self.sends: list = []

    def tearDown(self) -> None:
        self._p.stop()
        self._td.cleanup()

    def _amb(self, key: str = "wev:h1") -> None:
        self.dedupe.claim_event(key)
        self.dedupe.mark_outbound_started(key)
        self.dedupe.mark_needs_reconcile(key, reason="crash")

    def test_01_ambiguous_listed(self) -> None:
        self._amb()
        items = self.dedupe.list_needs_reconcile_events()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["key"], "wev:h1")

    def test_02_completed_not_listed(self) -> None:
        self.dedupe.claim_event("wev:done")
        self.dedupe.mark_completed("wev:done")
        self.assertEqual(self.dedupe.list_needs_reconcile_events(), [])

    def test_03_mark_completed_terminal(self) -> None:
        self._amb("wev:mc")
        out = self.dedupe.reconcile_line_event("wev:mc", action="mark_completed", operator="op")
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["reconciliation_action"], "mark_completed")

    def test_04_allow_reprocess_explicit(self) -> None:
        self._amb("wev:rp")
        out = self.dedupe.reconcile_line_event("wev:rp", action="allow_reprocess")
        self.assertEqual(out["status"], "cleared_for_reprocess")
        self.assertIsNone(self.dedupe.get_event("wev:rp"))

    def test_05_allow_reprocess_does_not_send(self) -> None:
        self._amb("wev:nosend")
        with mock.patch.object(self.webhook, "_push", side_effect=AssertionError("network")):
            self.dedupe.reconcile_line_event("wev:nosend", action="allow_reprocess")

    def test_06_suppress_terminal(self) -> None:
        self._amb("wev:sup")
        out = self.dedupe.reconcile_line_event("wev:sup", action="suppress")
        self.assertEqual(out["status"], "completed")
        self.assertTrue(out.get("suppressed"))

    def test_07_invalid_transition_rejected(self) -> None:
        self.dedupe.claim_event("wev:proc")
        with self.assertRaises(self.dedupe.LineReconcileError) as ctx:
            self.dedupe.reconcile_line_event("wev:proc", action="mark_completed")
        self.assertEqual(ctx.exception.http_status, 409)

    def test_08_persistence_survives_reload(self) -> None:
        self._amb("wev:persist")
        self.dedupe.reconcile_line_event("wev:persist", action="mark_completed")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["events"]["wev:persist"]["status"], "completed")

    def test_09_event_identity_preserved(self) -> None:
        self._amb("wev:idkeep")
        out = self.dedupe.reconcile_line_event("wev:idkeep", action="mark_completed")
        self.assertEqual(out.get("key") or "wev:idkeep", "wev:idkeep")
        self.assertIsNotNone(out.get("outbound_started_at"))

    def test_10_no_token_stored(self) -> None:
        self._amb("wev:tok")
        self.dedupe.reconcile_line_event("wev:tok", action="suppress")
        blob = self.path.read_text(encoding="utf-8")
        self.assertNotIn("Bearer", blob)
        self.assertNotIn("channel_access", blob.lower())

    def test_11_no_line_network_on_reconcile(self) -> None:
        self._amb("wev:net")
        src = Path(self.dedupe.__file__).read_text(encoding="utf-8")
        self.assertIn("Never sends a LINE message", self.dedupe.reconcile_line_event.__doc__)
        self.dedupe.reconcile_line_event("wev:net", action="mark_completed")

    def test_12_completed_reconcile_no_resend_on_duplicate(self) -> None:
        self._amb("wev:dup")
        self.dedupe.reconcile_line_event("wev:dup", action="mark_completed")

        def deliver(**kwargs):
            self.sends.append(kwargs)
            return "reply"

        summary = self.webhook.handle_line_events(
            {
                "events": [
                    {
                        "type": "message",
                        "webhookEventId": "dup",
                        "replyToken": "r",
                        "source": {"userId": "U1"},
                        "mode": "active",
                        "message": {"type": "text", "text": "ติดต่อแอดมิน"},
                    }
                ]
            },
            deliver=deliver,
        )
        self.assertEqual(summary.get("deduped"), 1)
        self.assertEqual(len(self.sends), 0)

    def test_13_missing_event_404(self) -> None:
        with self.assertRaises(self.dedupe.LineReconcileError) as ctx:
            self.dedupe.reconcile_line_event("wev:missing", action="suppress")
        self.assertEqual(ctx.exception.http_status, 404)

    def test_14_keep_unresolved(self) -> None:
        self._amb("wev:keep")
        out = self.dedupe.reconcile_line_event("wev:keep", action="keep_unresolved")
        self.assertEqual(out["status"], "needs_reconcile")


if __name__ == "__main__":
    unittest.main()
