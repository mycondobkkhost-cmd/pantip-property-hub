#!/usr/bin/env python3
"""DEPRECATED — use ``scripts/reorg_sheet_from_old.py`` instead.

Previously ran aggressive horizontal URL reclassify (moved Q posts → ลิ้งค์โพส).
That logic is retired. This entrypoint now delegates to the trust-column reorg.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def main() -> None:
    print(
        "reclassify_sheet_links.py is deprecated.\n"
        "Delegating to scripts/reorg_sheet_from_old.py (trust-column mapping).",
        flush=True,
    )
    path = BASE_DIR / "scripts" / "reorg_sheet_from_old.py"
    spec = importlib.util.spec_from_file_location("reorg_sheet_from_old", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    sys.argv[0] = str(path)
    mod.main()


if __name__ == "__main__":
    main()
