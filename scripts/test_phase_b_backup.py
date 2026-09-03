#!/usr/bin/env python3
"""Phase B backup/restore dry-run tests (synthetic DATA_DIR only)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.backup_data_dir import (  # noqa: E402
    backup_data_dir,
    classify_relative_path,
    restore_data_dir,
    verify_backup,
)


class PhaseBBackupTests(unittest.TestCase):
    def _write_sample(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "properties.json").write_text(
            json.dumps([{"id": "a", "code": "RXT1"}], ensure_ascii=False),
            encoding="utf-8",
        )
        (data_dir / "projects.json").write_text(
            json.dumps([{"id": "p1", "canonical_name": "P"}], ensure_ascii=False),
            encoding="utf-8",
        )
        (data_dir / "focus_properties.json").write_text("[]", encoding="utf-8")
        (data_dir / "preview-data.js").write_text("window.PTP_DATA={};", encoding="utf-8")
        (data_dir / "fb_agent.json").write_text('{"token":"secret"}', encoding="utf-8")
        cache = data_dir / "propertyhub_cache"
        cache.mkdir()
        (cache / "x.json").write_text("{}", encoding="utf-8")

    def test_authoritative_included_cache_secret_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            self._write_sample(data_dir)
            out = backup_data_dir(data_dir, dest=Path(td) / "backup")
            manifest = json.loads((Path(out["backup_dir"]) / "manifest.json").read_text())
            paths = {x["path"] for x in manifest["files"]}
            self.assertIn("properties.json", paths)
            self.assertIn("projects.json", paths)
            self.assertIn("focus_properties.json", paths)
            self.assertNotIn("preview-data.js", paths)
            self.assertNotIn("fb_agent.json", paths)
            self.assertTrue(all("propertyhub_cache" not in p for p in paths))

    def test_manifest_checksums_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / "data"
            self._write_sample(data_dir)
            backup = backup_data_dir(data_dir, dest=root / "backup")
            backup_dir = Path(backup["backup_dir"])
            verify = verify_backup(backup_dir)
            self.assertTrue(verify["ok"])

            # mutate source
            (data_dir / "properties.json").write_text("[]", encoding="utf-8")
            restore_dir = root / "restored"
            result = restore_data_dir(backup_dir, restore_dir, dry_run=False)
            self.assertTrue(result["ok"])
            restored = json.loads((restore_dir / "properties.json").read_text())
            self.assertEqual(restored[0]["code"], "RXT1")

    def test_missing_critical_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td) / "data"
            data_dir.mkdir()
            (data_dir / "projects.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                backup_data_dir(data_dir, dest=Path(td) / "backup")

    def test_corrupt_manifest_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            backup_dir = Path(td) / "backup"
            backup_dir.mkdir()
            (backup_dir / "manifest.json").write_text("{bad", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_backup(backup_dir)

    def test_path_traversal_rejected(self) -> None:
        from scripts.backup_data_dir import _resolve_in_data_dir

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            with self.assertRaises(ValueError):
                _resolve_in_data_dir(data_dir, "../outside.txt")

    def test_classify_paths(self) -> None:
        self.assertEqual(classify_relative_path("properties.json"), "authoritative")
        self.assertEqual(classify_relative_path("preview-data.js"), "derived")
        self.assertEqual(classify_relative_path("fb_agent.json"), "secret")
        self.assertEqual(classify_relative_path("propertyhub_cache/x.json"), "cache")


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PhaseBBackupTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
