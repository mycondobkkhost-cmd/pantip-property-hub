#!/usr/bin/env python3
"""Phase Z9 authenticated local QA checklist (static + module checks)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT / "hub" / "preview.html"


def main() -> int:
    html = PREVIEW.read_text(encoding="utf-8")
    checks = [
        ("add-url type=text", not re.search(r'id="add-url"[^>]*type="url"', html)),
        ("label generalized", "ลิงก์ต้นโพสต์ / แหล่งอ้างอิง" in html),
        ("helper text", "ใส่ลิงก์โพสต์ หรือข้อความอ้างอิงอื่นก็ได้" in html),
        ("scrape url guard", "ดึงจากลิงก์ต้องเป็น URL" in html),
        ("follow-up link", "/operator-follow-up/" in html),
        ("plain text cell", "source-ref-text" in html),
    ]
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
