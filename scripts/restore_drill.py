#!/usr/bin/env python3
"""Synthetic restore drill — backup, corrupt, restore, verify (local only)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from scripts.backup_data_dir import backup_data_dir, restore_data_dir, verify_backup


def run_restore_drill(data_dir: Path) -> dict[str, Any]:
    """End-to-end drill: backup → mutate source → restore to new dir → verify."""
    data_dir = data_dir.resolve()
    if not (data_dir / "properties.json").is_file():
        raise ValueError(f"properties.json missing in {data_dir}")
    if not (data_dir / "projects.json").is_file():
        raise ValueError(f"projects.json missing in {data_dir}")

    with tempfile.TemporaryDirectory(prefix="ptp-drill-") as td:
        root = Path(td)
        backup = backup_data_dir(data_dir, dest=root / "backup")
        backup_dir = Path(backup["backup_dir"])

        props_path = data_dir / "properties.json"
        original = props_path.read_text(encoding="utf-8")
        props_path.write_text("[]", encoding="utf-8")

        restore_dir = root / "restored"
        result = restore_data_dir(backup_dir, restore_dir, dry_run=False)

        restored_props = json.loads((restore_dir / "properties.json").read_text(encoding="utf-8"))
        if not isinstance(restored_props, list) or not restored_props:
            raise ValueError("restored properties.json empty")

        verify = verify_backup(backup_dir)
        if not verify.get("ok"):
            raise ValueError("backup verify failed after restore drill")

        props_path.write_text(original, encoding="utf-8")

        return {
            "ok": True,
            "backup_dir": str(backup_dir),
            "restore_dir": str(restore_dir),
            "restored_property_count": len(restored_props),
            "verify": verify,
            "restore": result,
        }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run synthetic backup/restore drill")
    parser.add_argument("data_dir", type=Path, nargs="?", default=Path("data"))
    args = parser.parse_args()
    try:
        result = run_restore_drill(args.data_dir)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
