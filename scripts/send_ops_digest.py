#!/usr/bin/env python3
"""Push ops digest to LINE_OPS_GROUP_ID (or print if unset)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from line_bot.ops import format_digest, notify_ops  # noqa: E402


def main() -> None:
    text = format_digest(limit=20)
    print(text)
    print("---")
    ok = notify_ops(text)
    print("pushed_to_ops_group" if ok else "printed_only_no_LINE_OPS_GROUP_ID")


if __name__ == "__main__":
    main()
