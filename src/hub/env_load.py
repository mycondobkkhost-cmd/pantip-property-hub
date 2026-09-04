"""Load project `.env` for local Hub / sheet tools.

On Render, platform env vars are the source of truth — never override them.
Locally, `.env` must win over stale shell exports (common cause of syncing
the wrong Google Sheet after switching SOURCE/HUB IDs).
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
_LOADED = False


def load_hub_env(*, force: bool = False) -> bool:
    """Load `BASE_DIR/.env`. Returns True if a file was applied."""
    global _LOADED
    if _LOADED and not force:
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:
        _LOADED = True
        return False

    path = BASE_DIR / ".env"
    if not path.is_file():
        _LOADED = True
        return False

    on_render = bool((os.environ.get("RENDER") or "").strip())
    # Isolated E2E: keep process env (users/port/data root) authoritative.
    e2e = bool((os.environ.get("PANTIP_E2E_DATA_ROOT") or "").strip())
    # Local: override stale shell/launchd exports so `.env` is authoritative.
    # Render: keep platform env; only fill missing keys from a bundled `.env`.
    # E2E: never override injected test env with owner `.env`.
    load_dotenv(path, override=(not on_render) and (not e2e))
    _LOADED = True
    return True
