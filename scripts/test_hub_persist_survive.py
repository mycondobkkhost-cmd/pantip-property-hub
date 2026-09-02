#!/usr/bin/env python3
"""Backend checks: saves land on volume catalog + merge never wipes local CRM."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PersistSurviveTests(unittest.TestCase):
    def test_preview_js_lives_under_data(self) -> None:
        from src.hub import project_store as ps

        self.assertEqual(ps.PREVIEW_JS, ROOT / "data" / "preview-data.js")
        self.assertTrue(str(ps.PREVIEW_JS).endswith("/data/preview-data.js"))

    def test_ensure_preview_rebuilds_when_json_newer(self) -> None:
        from src.hub import project_store as ps

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            data = base / "data"
            hub = base / "hub"
            data.mkdir()
            hub.mkdir()

            props = [
                {
                    "id": "p1",
                    "code": "RXT0001",
                    "project_id": "proj1",
                    "import_status": "active",
                }
            ]
            projects = [
                {
                    "id": "proj1",
                    "canonical_name": "Test Condo",
                    "bucket_key": "testcondo",
                }
            ]
            (data / "properties.json").write_text(
                json.dumps(props, ensure_ascii=False), encoding="utf-8"
            )
            (data / "projects.json").write_text(
                json.dumps(projects, ensure_ascii=False), encoding="utf-8"
            )
            # Stale catalog under hub/ (old bug) + empty/missing volume catalog
            (hub / "preview-data.js").write_text(
                "window.PTP_DATA={stats:{properties_total:999}};", encoding="utf-8"
            )
            (hub / "preview-data.meta.json").write_text(
                json.dumps({"properties_total": 999, "data_version": "old"}),
                encoding="utf-8",
            )

            with mock.patch.object(ps, "BASE_DIR", base), mock.patch.object(
                ps, "PROPERTIES_JSON", data / "properties.json"
            ), mock.patch.object(
                ps, "PROJECTS_JSON", data / "projects.json"
            ), mock.patch.object(
                ps, "PREVIEW_JS", data / "preview-data.js"
            ), mock.patch.object(
                ps, "PREVIEW_META", data / "preview-data.meta.json"
            ), mock.patch.object(
                ps, "PREVIEW_JS_LEGACY", hub / "preview-data.js"
            ), mock.patch.object(
                ps, "PREVIEW_META_LEGACY", hub / "preview-data.meta.json"
            ), mock.patch.object(
                ps, "DB_PATH", data / "hub.db"
            ):
                # migrate legacy copy first
                out = ps.ensure_preview_js()
                self.assertTrue(out.get("ok"))
                # force count mismatch path
                (data / "preview-data.meta.json").write_text(
                    json.dumps({"properties_total": 999}), encoding="utf-8"
                )
                out2 = ps.ensure_preview_js()
                self.assertTrue(out2.get("rebuilt") or out2.get("ok"))
                body = (data / "preview-data.js").read_text(encoding="utf-8")
                self.assertIn("PTP_DATA", body)
                meta = json.loads(
                    (data / "preview-data.meta.json").read_text(encoding="utf-8")
                )
                self.assertEqual(int(meta.get("properties_total") or 0), 1)

    def test_merge_focus_keeps_local_when_sheet_empty(self) -> None:
        from src.hub import focus_store as fs

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "focus.json"
            local = [{"id": "keep-me", "code": "RXT9", "pinned_at": "2026-01-01T00:00:00Z"}]
            path.write_text(json.dumps({"items": local}), encoding="utf-8")
            with mock.patch.object(fs, "FOCUS_PATH", path), mock.patch(
                "src.hub.hub_state_sheet.pull_focus_from_sheet", return_value=[]
            ):
                meta = fs.merge_focus_from_sheet()
                self.assertEqual(meta.get("count"), 1)
                saved = json.loads(path.read_text(encoding="utf-8"))
                items = saved.get("items") if isinstance(saved, dict) else saved
                self.assertEqual(items[0]["id"], "keep-me")

    def test_merge_cases_keeps_local_when_sheet_empty(self) -> None:
        from src.hub import customer_store as cs

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "cases.json"
            local = [
                {
                    "id": "fu_keep",
                    "case_code": "FU0001",
                    "name": "ลูกค้าทดสอบ",
                    "status": "new",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ]
            path.write_text(json.dumps({"items": local}), encoding="utf-8")
            with mock.patch.object(cs, "CASES_PATH", path), mock.patch(
                "src.hub.hub_state_sheet.pull_customers_from_sheet", return_value=[]
            ):
                meta = cs.merge_cases_from_sheet()
                self.assertEqual(meta.get("count"), 1)
                saved = json.loads(path.read_text(encoding="utf-8"))
                items = saved.get("items") if isinstance(saved, dict) else saved
                self.assertEqual(items[0]["id"], "fu_keep")

    def test_merge_tenants_keeps_local_when_sheet_empty(self) -> None:
        from src.hub import tenant_store as ts

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tenants.json"
            local = [
                {
                    "id": "tn_keep",
                    "tenant_code": "TN0001",
                    "name": "ผู้เช่าทดสอบ",
                    "status": "active",
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ]
            path.write_text(json.dumps({"items": local}), encoding="utf-8")
            with mock.patch.object(ts, "TENANTS_PATH", path), mock.patch(
                "src.hub.hub_state_sheet.pull_tenants_from_sheet", return_value=[]
            ):
                meta = ts.merge_tenants_from_sheet()
                self.assertEqual(meta.get("count"), 1)
                saved = json.loads(path.read_text(encoding="utf-8"))
                items = saved.get("items") if isinstance(saved, dict) else saved
                self.assertEqual(items[0]["id"], "tn_keep")

    def test_schedule_auto_sync_queues(self) -> None:
        import scripts.hub_server as hub

        with mock.patch.object(hub, "_auto_sync_to_sheet_enabled", return_value=True):
            # reset state lightly
            with hub._AUTO_SYNC_LOCK:
                hub._AUTO_SYNC_TO_SHEET["pending"] = False
                hub._AUTO_SYNC_TO_SHEET["running"] = False
                hub._AUTO_SYNC_TO_SHEET["worker_started"] = True  # don't spawn thread
            out = hub.schedule_auto_sync_to_sheet(reason="unit-test")
            self.assertTrue(out.get("queued"))
            with hub._AUTO_SYNC_LOCK:
                self.assertTrue(hub._AUTO_SYNC_TO_SHEET.get("pending"))
                hub._AUTO_SYNC_TO_SHEET["pending"] = False

    def test_flush_idle(self) -> None:
        import scripts.hub_server as hub

        with hub._AUTO_SYNC_LOCK:
            hub._AUTO_SYNC_TO_SHEET["pending"] = False
            hub._AUTO_SYNC_TO_SHEET["running"] = False
        out = hub._flush_pending_sheet_sync(timeout_sec=1.0)
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("flushed"))
        self.assertEqual(out.get("reason"), "idle")

    def test_queue_adds_do_not_overwrite_each_other(self) -> None:
        from src.hub import queue_store as qs

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wait_post_queue.json"
            with mock.patch.object(qs, "QUEUE_PATH", path):
                a = qs.add_job(
                    source_url="https://www.facebook.com/share/p/aaaa/",
                    project="Oka Haus",
                )
                b = qs.add_job(
                    source_url="https://www.facebook.com/share/p/bbbb/",
                    project="Witthayu Complex",
                )
                items = qs.load_queue()
                ids = {x.get("id") for x in items}
                self.assertIn(a["id"], ids)
                self.assertIn(b["id"], ids)
                names = {(x.get("project") or "") for x in items}
                self.assertIn("Oka Haus", names)
                self.assertIn("Witthayu Complex", names)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PersistSurviveTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
