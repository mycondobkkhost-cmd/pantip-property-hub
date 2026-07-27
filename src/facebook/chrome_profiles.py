"""Detect Google Chrome profiles on the local machine (Mac / Windows)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def chrome_user_data_dir() -> Path | None:
    if sys.platform == "darwin":
        p = Path.home() / "Library/Application Support/Google/Chrome"
        return p if p.is_dir() else None
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or ""
        p = Path(local) / "Google/Chrome/User Data"
        return p if p.is_dir() else None
    # Linux
    p = Path.home() / ".config/google-chrome"
    return p if p.is_dir() else None


def list_chrome_profiles() -> list[dict[str, str]]:
    """Return [{dir, name, email}, ...] for Chrome profiles on this PC."""
    root = chrome_user_data_dir()
    if not root:
        return []

    out: list[dict[str, str]] = []
    local_state = root / "Local State"
    info_cache: dict[str, Any] = {}
    if local_state.is_file():
        try:
            data = json.loads(local_state.read_text(encoding="utf-8", errors="replace"))
            raw = (data.get("profile") or {}).get("info_cache") or {}
            if isinstance(raw, dict):
                info_cache = raw
        except (OSError, json.JSONDecodeError, TypeError):
            info_cache = {}

    if info_cache:
        for folder, meta in info_cache.items():
            if not isinstance(meta, dict):
                continue
            folder_s = str(folder).strip()
            if not folder_s or folder_s.lower() in {"system profile", "guest profile"}:
                continue
            name = str(meta.get("name") or folder_s).strip() or folder_s
            email = str(
                meta.get("user_name")
                or meta.get("gaia_name")
                or meta.get("user_email")
                or ""
            ).strip()
            out.append({"dir": folder_s, "name": name, "email": email})
    else:
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if child.name == "Default" or child.name.startswith("Profile "):
                out.append({"dir": child.name, "name": child.name, "email": ""})

    # Prefer named work profiles first-ish: keep alphabetical by display name
    out.sort(key=lambda r: (str(r.get("name") or "").lower(), str(r.get("dir") or "")))
    return out


def find_chrome_executable() -> Path | None:
    if sys.platform == "darwin":
        p = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        return p if p.is_file() else None
    if sys.platform.startswith("win"):
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
        for p in candidates:
            if p.is_file():
                return p
        return None
    for cand in ("google-chrome", "google-chrome-stable", "chromium-browser"):
        # PATH lookup left to callers via shutil
        from shutil import which

        found = which(cand)
        if found:
            return Path(found)
    return None
