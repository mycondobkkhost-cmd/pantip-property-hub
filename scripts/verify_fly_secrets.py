#!/usr/bin/env python3
"""Read-only Fly secret NAME verification — never prints secret values."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

REQUIRED_SECRETS: tuple[str, ...] = (
    "HUB_USERS_JSON",
    "HUB_SESSION_SECRET",
)

RECOMMENDED_SECRETS: tuple[str, ...] = (
    "GOOGLE_SERVICE_ACCOUNT_JSON",
    "LINE_CHANNEL_ACCESS_TOKEN",
    "LINE_CHANNEL_SECRET",
)

DEFAULT_APP = "property-hub"


def _parse_secret_names(output: str) -> set[str]:
    names: set[str] = set()
    for line in output.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("name"):
            continue
        name = re.split(r"\s+", line, maxsplit=1)[0].strip()
        if name:
            names.add(name)
    return names


def check_fly_secrets(
    *,
    app: str = DEFAULT_APP,
    fly_bin: str | None = None,
) -> dict[str, Any]:
    fly = fly_bin or shutil.which("fly") or shutil.which("flyctl")
    if not fly:
        return {
            "ok": False,
            "checked": False,
            "error": "fly CLI not found",
            "owner_action": f"Install flyctl and run: fly secrets list -a {app}",
            "required": list(REQUIRED_SECRETS),
            "recommended": list(RECOMMENDED_SECRETS),
        }

    try:
        proc = subprocess.run(
            [fly, "secrets", "list", "-a", app],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "checked": False,
            "error": "fly CLI not found",
            "owner_action": f"Install flyctl and run: fly secrets list -a {app}",
            "required": list(REQUIRED_SECRETS),
            "recommended": list(RECOMMENDED_SECRETS),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "checked": False,
            "error": str(exc),
            "owner_action": f"fly secrets list -a {app}",
            "required": list(REQUIRED_SECRETS),
            "recommended": list(RECOMMENDED_SECRETS),
        }

    if proc.returncode != 0:
        return {
            "ok": False,
            "checked": False,
            "error": (proc.stderr or proc.stdout or "fly secrets list failed").strip(),
            "owner_action": "Authenticate: fly auth login",
            "required": list(REQUIRED_SECRETS),
            "recommended": list(RECOMMENDED_SECRETS),
        }

    present = _parse_secret_names(proc.stdout or "")
    missing_required = [s for s in REQUIRED_SECRETS if s not in present]
    missing_recommended = [s for s in RECOMMENDED_SECRETS if s not in present]

    return {
        "ok": not missing_required,
        "checked": True,
        "app": app,
        "present_count": len(present),
        "present_names": sorted(present),
        "missing_required": missing_required,
        "missing_recommended": missing_recommended,
        "note": "Secret values are never displayed — names only.",
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify Fly secret names (read-only)")
    parser.add_argument("--app", default=DEFAULT_APP)
    args = parser.parse_args()
    result = check_fly_secrets(app=args.app)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
