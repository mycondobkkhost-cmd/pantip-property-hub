#!/usr/bin/env python3
"""Phase G LINE durable webhook dedupe tests (offline — no LINE network)."""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PhaseGLineDedupeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.store_path = Path(self._td.name) / "line_event_dedupe.json"
        import src.hub.line_event_dedupe as dedupe
        import src.hub.line_menu_webhook as webhook

        self.dedupe = dedupe
        self.webhook = webhook
        self._patches = [
            mock.patch.object(dedupe, "STORE_PATH", self.store_path),
        ]
        for p in self._patches:
            p.start()
        self.sends: list[dict] = []

        def fake_deliver(**kwargs):
            self.sends.append(dict(kwargs))
            return "reply"

        self.deliver = fake_deliver

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._td.cleanup()

    def _event(self, *, wid: str, text: str = "ติดต่อแอดมิน", mid: str = "") -> dict:
        msg = {"type": "text", "text": text}
        if mid:
            msg["id"] = mid
        ev = {
            "type": "message",
            "replyToken": "tok-" + wid,
            "source": {"userId": "U1", "type": "user"},
            "mode": "active",
            "message": msg,
        }
        if wid:
            ev["webhookEventId"] = wid
        return ev

    def test_01_first_event_processed(self) -> None:
        summary = self.webhook.handle_line_events(
            {"events": [self._event(wid="e1")]},
            deliver=self.deliver,
        )
        self.assertEqual(summary["replied"], 1)
        self.assertEqual(len(self.sends), 1)
        rec = self.dedupe.get_event("wev:e1")
        self.assertEqual(rec["status"], "completed")

    def test_02_duplicate_completed_not_processed(self) -> None:
        payload = {"events": [self._event(wid="e2")]}
        self.webhook.handle_line_events(payload, deliver=self.deliver)
        self.webhook.handle_line_events(payload, deliver=self.deliver)
        self.assertEqual(len(self.sends), 1)

    def test_03_concurrent_claims_one_winner(self) -> None:
        key = "wev:conc1"
        results: list[dict] = []
        barrier = threading.Barrier(2)

        def worker() -> None:
            barrier.wait()
            results.append(self.dedupe.claim_event(key))

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        winners = [r for r in results if r.get("ok")]
        self.assertEqual(len(winners), 1)

    def test_04_ttl_cleanup_removes_old_terminal(self) -> None:
        self.dedupe.claim_event("wev:old")
        self.dedupe.mark_completed("wev:old", now=time.time() - 80 * 3600)
        removed = self.dedupe.cleanup_expired(now=time.time(), ttl_sec=72 * 3600)
        self.assertGreaterEqual(removed, 1)
        self.assertIsNone(self.dedupe.get_event("wev:old"))

    def test_05_active_processing_duplicate_no_send(self) -> None:
        self.dedupe.claim_event("wev:proc")
        summary = self.webhook.handle_line_events(
            {"events": [self._event(wid="proc")]},
            deliver=self.deliver,
        )
        self.assertEqual(summary["deduped"], 1)
        self.assertEqual(len(self.sends), 0)

    def test_06_outbound_started_ambiguous_no_resend(self) -> None:
        self.dedupe.claim_event("wev:amb")
        self.dedupe.mark_outbound_started("wev:amb")
        summary = self.webhook.handle_line_events(
            {"events": [self._event(wid="amb")]},
            deliver=self.deliver,
        )
        self.assertEqual(summary["ambiguous"], 1)
        self.assertEqual(len(self.sends), 0)

    def test_07_invalid_signature_rejected(self) -> None:
        body = b'{"events":[]}'
        with mock.patch.object(self.webhook, "line_menu_enabled", return_value=True), mock.patch.object(
            self.webhook, "line_credentials", return_value=("secret", "token")
        ):
            status, payload = self.webhook.process_webhook(body, "bad-sig")
        self.assertEqual(status, 400)
        self.assertIn("Invalid", payload.get("error", ""))

    def test_08_different_event_ids_independent(self) -> None:
        self.webhook.handle_line_events(
            {"events": [self._event(wid="a"), self._event(wid="b")]},
            deliver=self.deliver,
        )
        self.assertEqual(len(self.sends), 2)

    def test_09_no_line_network_call(self) -> None:
        # deliver is injected fake — prove default path not invoked by patching _push.
        with mock.patch.object(self.webhook, "_push", side_effect=AssertionError("network")):
            self.webhook.handle_line_events(
                {"events": [self._event(wid="net")]},
                deliver=self.deliver,
            )
        self.assertEqual(len(self.sends), 1)

    def test_10_dedupe_survives_reload(self) -> None:
        self.webhook.handle_line_events(
            {"events": [self._event(wid="persist")]},
            deliver=self.deliver,
        )
        # Simulate process restart by reloading from disk.
        rec = self.dedupe.get_event("wev:persist")
        self.assertEqual(rec["status"], "completed")
        data = json.loads(self.store_path.read_text(encoding="utf-8"))
        self.assertIn("wev:persist", data["events"])

    def test_11_valid_signature_path_offline(self) -> None:
        body = json.dumps({"events": [self._event(wid="sig1")]}).encode("utf-8")
        secret = "test-secret"
        sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
        import base64

        header = base64.b64encode(sig).decode("ascii")
        with mock.patch.object(self.webhook, "line_menu_enabled", return_value=True), mock.patch.object(
            self.webhook, "line_credentials", return_value=(secret, "token")
        ), mock.patch.object(self.webhook, "handle_line_events", return_value={"replied": 0}) as h:
            status, payload = self.webhook.process_webhook(body, header)
        self.assertEqual(status, 200)
        self.assertTrue(payload.get("ok"))
        h.assert_called_once()


if __name__ == "__main__":
    unittest.main()
