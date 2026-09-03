#!/usr/bin/env python3
"""Phase F restore-tool immutability and recovery safety tests (offline only)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.backup_data_dir import backup_data_dir, restore_data_dir, verify_backup  # noqa: E402
from scripts.restore_drill import (  # noqa: E402
    run_restore_drill,
    snapshot_directory,
    validate_restored_catalog,
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _write_catalog(
    data_dir: Path,
    *,
    props: list[dict] | None = None,
    projs: list[dict] | None = None,
) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    if props is None:
        props = [
            {"id": "prop-1", "code": "RXT1", "project_id": "proj-1"},
            {"id": "prop-2", "code": "PTP4734", "project_id": "proj-1"},
            {"id": "prop-3", "code": "PTP4734", "project_id": "proj-2"},
        ]
    if projs is None:
        projs = [
            {"id": "proj-1", "canonical_name": "One"},
            {"id": "proj-2", "canonical_name": "Two"},
        ]
    (data_dir / "properties.json").write_text(
        json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (data_dir / "projects.json").write_text(
        json.dumps(projs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (data_dir / "focus_properties.json").write_text("[]", encoding="utf-8")
    (data_dir / "sentinel.txt").write_text("SENTINEL-BYTES-v1", encoding="utf-8")


class PhaseFRestoreSafetyTests(unittest.TestCase):
    def test_01_source_hashes_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "source"
            dest = Path(td) / "restore"
            _write_catalog(src)
            before = snapshot_directory(src)
            run_restore_drill(source_backup=src, restore_destination=dest)
            after = snapshot_directory(src)
            self.assertEqual(before, after)

    def test_02_source_file_list_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "source"
            dest = Path(td) / "restore"
            _write_catalog(src)
            before = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
            run_restore_drill(source_backup=src, restore_destination=dest)
            after = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
            self.assertEqual(before, after)

    def test_03_sentinel_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "source"
            dest = Path(td) / "restore"
            _write_catalog(src)
            digest = _sha256(src / "sentinel.txt")
            run_restore_drill(source_backup=src, restore_destination=dest)
            self.assertEqual(digest, _sha256(src / "sentinel.txt"))
            self.assertEqual((src / "sentinel.txt").read_text(encoding="utf-8"), "SENTINEL-BYTES-v1")

    def test_04_source_equals_destination_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "source"
            _write_catalog(src)
            with self.assertRaises(ValueError) as ctx:
                run_restore_drill(source_backup=src, restore_destination=src)
            self.assertIn("differ", str(ctx.exception).lower())
            self.assertEqual((src / "properties.json").read_text(encoding="utf-8")[:1], "[")

    def test_05_nested_destination_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "source"
            _write_catalog(src)
            nested = src / "nested-restore"
            with self.assertRaises(ValueError) as ctx:
                run_restore_drill(source_backup=src, restore_destination=nested)
            self.assertIn("nested", str(ctx.exception).lower())

    def test_06_existing_nonempty_destination_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "source"
            dest = Path(td) / "restore"
            _write_catalog(src)
            dest.mkdir()
            (dest / "existing.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                run_restore_drill(source_backup=src, restore_destination=dest)
            self.assertIn("empty", str(ctx.exception).lower())
            self.assertEqual((dest / "existing.txt").read_text(encoding="utf-8"), "keep")

    def test_07_corrupt_restore_detected_source_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "source"
            dest = Path(td) / "restore"
            _write_catalog(src)
            before = snapshot_directory(src)
            # drill itself simulates corruption on an isolated copy
            result = run_restore_drill(source_backup=src, restore_destination=dest)
            self.assertTrue(result["corruption_simulation_detected"])
            self.assertEqual(before, snapshot_directory(src))
            # also direct validate of corrupt tree
            bad = Path(td) / "bad"
            shutil.copytree(dest, bad)
            (bad / "properties.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_restored_catalog(bad)
            self.assertEqual(before, snapshot_directory(src))

    def test_08_duplicate_property_id_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            restore = Path(td) / "restore"
            restore.mkdir()
            (restore / "properties.json").write_text(
                json.dumps(
                    [
                        {"id": "same", "code": "A", "project_id": "p1"},
                        {"id": "same", "code": "B", "project_id": "p1"},
                    ]
                ),
                encoding="utf-8",
            )
            (restore / "projects.json").write_text(
                json.dumps([{"id": "p1", "canonical_name": "P"}]), encoding="utf-8"
            )
            result = validate_restored_catalog(restore)
            self.assertFalse(result["ok"])
            self.assertGreaterEqual(result["duplicate_property_id_count"], 1)
            self.assertTrue(result["identity_corruption"])

    def test_09_orphan_project_reference_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            restore = Path(td) / "restore"
            restore.mkdir()
            (restore / "properties.json").write_text(
                json.dumps([{"id": "p1", "code": "A", "project_id": "missing-proj"}]),
                encoding="utf-8",
            )
            (restore / "projects.json").write_text(
                json.dumps([{"id": "other", "canonical_name": "X"}]), encoding="utf-8"
            )
            result = validate_restored_catalog(restore)
            self.assertEqual(result["orphan_project_ref_count"], 1)
            self.assertEqual(result["missing_project_id_count"], 0)

    def test_10_missing_project_id_separate_from_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            restore = Path(td) / "restore"
            restore.mkdir()
            (restore / "properties.json").write_text(
                json.dumps(
                    [
                        {"id": "p1", "code": "A", "project_id": ""},
                        {"id": "p2", "code": "B", "project_id": "ghost"},
                    ]
                ),
                encoding="utf-8",
            )
            (restore / "projects.json").write_text(
                json.dumps([{"id": "real", "canonical_name": "R"}]), encoding="utf-8"
            )
            result = validate_restored_catalog(restore)
            self.assertEqual(result["missing_project_id_count"], 1)
            self.assertEqual(result["orphan_project_ref_count"], 1)

    def test_11_duplicate_property_code_not_identity_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            restore = Path(td) / "restore"
            restore.mkdir()
            (restore / "properties.json").write_text(
                json.dumps(
                    [
                        {"id": "a", "code": "PTP4734", "project_id": "p1"},
                        {"id": "b", "code": "PTP4734", "project_id": "p2"},
                    ]
                ),
                encoding="utf-8",
            )
            (restore / "projects.json").write_text(
                json.dumps(
                    [
                        {"id": "p1", "canonical_name": "One"},
                        {"id": "p2", "canonical_name": "Two"},
                    ]
                ),
                encoding="utf-8",
            )
            result = validate_restored_catalog(restore)
            self.assertTrue(result["ok"])
            self.assertFalse(result["identity_corruption"])
            self.assertFalse(result["duplicate_property_code_is_corruption"])
            self.assertGreaterEqual(result["duplicate_property_code_group_count"], 1)

    def test_12_external_integrations_disabled_flag_in_env(self) -> None:
        """Recovered-Hub smoke must keep Sheets/LINE/OpenAI disabled."""
        env = {
            "HUB_AUTO_SYNC_TO_SHEET": "0",
            "HUB_ALLOW_SHEET_PULL": "0",
            "HUB_STARTUP_SHEET_SYNC": "0",
            "LINE_MENU_WEBHOOK": "0",
            "OPENAI_API_KEY": "",
            "HUB_LOCAL_DEV": "1",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(os.environ.get("HUB_AUTO_SYNC_TO_SHEET"), "0")
            self.assertEqual(os.environ.get("HUB_ALLOW_SHEET_PULL"), "0")
            self.assertEqual(os.environ.get("LINE_MENU_WEBHOOK"), "0")
            self.assertFalse(bool((os.environ.get("OPENAI_API_KEY") or "").strip()))

    def test_backup_excludes_secrets_and_requires_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            _write_catalog(data)
            (data / "fb_agent.json").write_text('{"token":"x"}', encoding="utf-8")
            (data / "preview-data.js").write_text("window.X=1;", encoding="utf-8")
            out = backup_data_dir(data, dest=Path(td) / "backup")
            manifest = json.loads((Path(out["backup_dir"]) / "manifest.json").read_text())
            paths = {f["path"] for f in manifest["files"]}
            self.assertIn("properties.json", paths)
            self.assertNotIn("fb_agent.json", paths)
            self.assertNotIn("preview-data.js", paths)
            self.assertNotIn("sentinel.txt", paths)  # other unclassified optional
            self.assertTrue(verify_backup(Path(out["backup_dir"]))["ok"])

    def test_restore_data_dir_rejects_nonempty_dest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            _write_catalog(data)
            backup = Path(backup_data_dir(data, dest=Path(td) / "backup")["backup_dir"])
            dest = Path(td) / "dest"
            dest.mkdir()
            (dest / "x").write_text("1", encoding="utf-8")
            with self.assertRaises(ValueError):
                restore_data_dir(backup, dest)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PhaseFRestoreSafetyTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
