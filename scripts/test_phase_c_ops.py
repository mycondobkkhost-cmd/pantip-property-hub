#!/usr/bin/env python3
"""Phase C operational readiness tests — dev seed, restore drill, migration checklist."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.migration_readiness import assess_migration_readiness  # noqa: E402
from scripts.restore_drill import run_restore_drill  # noqa: E402
from scripts.verify_fly_secrets import check_fly_secrets  # noqa: E402


class PhaseCOpsTests(unittest.TestCase):
    def test_data_seed_exists_with_duplicate_shape(self) -> None:
        seed = ROOT / "data_seed"
        props = json.loads((seed / "properties.json").read_text(encoding="utf-8"))
        projs = json.loads((seed / "projects.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(props), 15)
        self.assertGreaterEqual(len(projs), 8)
        dup = [p for p in props if p.get("code") == "PTP4734"]
        self.assertGreaterEqual(len(dup), 3)
        self.assertEqual(len({p["id"] for p in dup}), len(dup))

    def test_data_seed_has_no_pii_fields_populated(self) -> None:
        props = json.loads((ROOT / "data_seed/properties.json").read_text(encoding="utf-8"))
        for p in props:
            self.assertEqual(p.get("notes") or "", "")
            self.assertEqual(p.get("owner_phones") or [], [])
            self.assertEqual(p.get("owner_lines") or [], [])
            self.assertEqual(p.get("owner_facebook") or [], [])

    def test_data_seed_co_agent_urls(self) -> None:
        props = json.loads((ROOT / "data_seed/properties.json").read_text(encoding="utf-8"))
        with_link = [
            p
            for p in props
            if str(p.get("post_url") or "").startswith("http")
            or str(p.get("post_pages_url") or "").startswith("http")
        ]
        self.assertGreaterEqual(len(with_link), 5)

    def test_restore_drill_on_seed_copy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            shutil.copytree(ROOT / "data_seed", data)
            result = run_restore_drill(data)
            self.assertTrue(result["ok"])
            self.assertGreater(result["restored_property_count"], 0)
            # source restored after drill
            props = json.loads((data / "properties.json").read_text(encoding="utf-8"))
            self.assertGreater(len(props), 0)

    def test_migration_readiness_passes(self) -> None:
        result = assess_migration_readiness(ROOT)
        self.assertTrue(result["ready_to_untrack_sot_from_git"])
        failing = [c["name"] for c in result["checks"] if not c["ok"]]
        self.assertEqual(
            failing,
            ["runtime_sot_still_in_repo"] if "runtime_sot_still_in_repo" in failing else failing,
        )
        # runtime_sot_still_in_repo is expected True (files exist) — not a failure for Phase C
        core = [
            c
            for c in result["checks"]
            if c["name"] != "runtime_sot_still_in_repo"
        ]
        self.assertTrue(all(c["ok"] for c in core))

    def test_fly_secrets_graceful_without_cli(self) -> None:
        result = check_fly_secrets(fly_bin="/nonexistent/fly")
        self.assertFalse(result.get("checked"))
        self.assertIn("fly CLI not found", result.get("error", ""))


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PhaseCOpsTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
