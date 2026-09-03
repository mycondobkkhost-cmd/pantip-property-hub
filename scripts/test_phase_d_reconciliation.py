#!/usr/bin/env python3
"""Phase D reconciliation tests — import consistency and clear_comment_work offline."""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PhaseDReconciliationTests(unittest.TestCase):
    def test_clear_comment_work_importable(self) -> None:
        from src.hub.group_post_store import clear_comment_work

        self.assertTrue(callable(clear_comment_work))

    def test_clear_comment_work_pause_mode_synthetic(self) -> None:
        import src.hub.group_post_store as gps

        with tempfile.TemporaryDirectory() as td:
            links = Path(td) / "group_post_links.json"
            codes = Path(td) / "group_post_codes.json"
            with (
                mock.patch.object(gps, "STORE_PATH", links),
                mock.patch.object(gps, "CODE_STORE_PATH", codes),
            ):
                gps.add_code("PTPTEST")
                gps.update_code("PTPTEST", {"agent_id": "agent-a"})
                gps.add_post_link(
                    property_code="PTPTEST",
                    post_url="https://www.facebook.com/groups/123/posts/456",
                )
                result = gps.clear_comment_work(agent_id="agent-a", mode="pause")
                self.assertEqual(result["mode"], "pause")
                self.assertGreaterEqual(result["codes_paused"], 1)
                self.assertGreaterEqual(result["links_paused"], 1)
                detail = gps.get_code_detail("PTPTEST")
                self.assertFalse(detail["code"].get("active", True))

    def test_clear_comment_work_delete_mode_synthetic(self) -> None:
        import src.hub.group_post_store as gps

        with tempfile.TemporaryDirectory() as td:
            links = Path(td) / "group_post_links.json"
            codes = Path(td) / "group_post_codes.json"
            with (
                mock.patch.object(gps, "STORE_PATH", links),
                mock.patch.object(gps, "CODE_STORE_PATH", codes),
            ):
                gps.add_code("PTPDEL")
                gps.update_code("PTPDEL", {"agent_id": "agent-b"})
                gps.add_post_link(
                    property_code="PTPDEL",
                    post_url="https://www.facebook.com/groups/999/posts/111",
                )
                result = gps.clear_comment_work(agent_id="agent-b", mode="delete")
                self.assertEqual(result["mode"], "delete")
                self.assertGreaterEqual(result["codes_deleted"], 1)
                self.assertIsNone(gps.get_code_by_code("PTPDEL"))

    def test_hub_server_import_smoke(self) -> None:
        env = {
            "HUB_LOCAL_DEV": "1",
            "HUB_ALLOW_SHEET_PULL": "0",
            "HUB_STARTUP_SHEET_SYNC": "0",
            "HUB_AUTO_SYNC_TO_SHEET": "0",
            "OPENAI_API_KEY": "",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            import scripts.hub_server as hub

            self.assertTrue(hasattr(hub, "HubHandler"))
            from src.hub.group_post_store import clear_comment_work

            self.assertTrue(callable(clear_comment_work))


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PhaseDReconciliationTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
