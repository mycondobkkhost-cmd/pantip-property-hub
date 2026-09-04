#!/usr/bin/env python3
"""Read-only production backup from Fly volume — no production mutation."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKUP_ROOT = Path.home() / "Backups" / "pantip-property-automation"
APP = "property-hub"
REMOTE_DATA = "/app/data"
AUTHORITATIVE = ("properties.json", "projects.json")
EXCLUDED_PATTERNS = ("secrets", "fb_agent.json", ".env", "cache", "derived")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fly_cat(remote_path: str) -> bytes:
    cmd = ["fly", "ssh", "console", "-a", APP, "-C", f"cat {remote_path}"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace") or "fly ssh failed")
    return proc.stdout


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_id = f"production-fly-{stamp}"
    out_dir = BACKUP_ROOT / backup_id
    out_dir.mkdir(parents=True, exist_ok=True)

    files_meta: list[dict] = []
    for name in AUTHORITATIVE:
        remote = f"{REMOTE_DATA}/{name}"
        raw = _fly_cat(remote)
        json.loads(raw.decode("utf-8"))  # validate
        dest = out_dir / name
        dest.write_bytes(raw)
        files_meta.append(
            {
                "path": name,
                "size": len(raw),
                "sha256": _sha256_bytes(raw),
                "classification": "authoritative",
            }
        )

    props = json.loads((out_dir / "properties.json").read_text(encoding="utf-8"))
    projs = json.loads((out_dir / "projects.json").read_text(encoding="utf-8"))
    manifest = {
        "schema": "pantip-production-backup/v1",
        "backup_id": backup_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_app": APP,
        "source_volume": "vol_vz8qondpo5pkpmxv",
        "source_path": REMOTE_DATA,
        "method": "fly_ssh_cat_readonly",
        "files": files_meta,
        "counts": {"properties": len(props), "projects": len(projs)},
        "excluded": ["secrets", "fb_agent.json", ".env", "cache", "derived"],
        "consistency": "BEST_EFFORT",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "backup_dir": str(out_dir), "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise SystemExit(1)
