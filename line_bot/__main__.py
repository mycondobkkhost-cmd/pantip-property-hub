"""Run: python -m line_bot"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main() -> None:
    host = os.getenv("LINE_BOT_HOST", "0.0.0.0")
    port = int(os.getenv("LINE_BOT_PORT", "8787"))
    uvicorn.run(
        "line_bot.app:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
