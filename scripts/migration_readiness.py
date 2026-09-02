#!/usr/bin/env python3
"""Git runtime-data migration readiness checklist (read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def assess_migration_readiness(root: Path | None = None) -> dict[str, Any]:
    root = (root or ROOT).resolve()
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("property_resolve_module", (root / "src/hub/property_resolve.py").is_file())
    add("public_projection_module", (root / "src/hub/public_projection.py").is_file())
    add("backup_utility", (root / "scripts/backup_data_dir.py").is_file())
    add("restore_drill", (root / "scripts/restore_drill.py").is_file())
    seed_props = root / "data_seed/properties.json"
    seed_projs = root / "data_seed/projects.json"
    add("data_seed_properties", seed_props.is_file())
    add("data_seed_projects", seed_projs.is_file())

    dup_ok = False
    if seed_props.is_file():
        try:
            props = json.loads(seed_props.read_text(encoding="utf-8"))
            codes = [str(p.get("code") or "") for p in props if isinstance(p, dict)]
            dup_ok = codes.count("PTP4734") >= 3
        except (OSError, json.JSONDecodeError):
            dup_ok = False
    add("data_seed_duplicate_shape", dup_ok, "PTP4734 x3+")

    gitignore = (root / ".gitignore").read_text(encoding="utf-8") if (root / ".gitignore").is_file() else ""
    add("gitignore_has_runtime_jobs", "group_publish_jobs.json" in gitignore)

    tracked_sot_still = (root / "data/properties.json").is_file() and (root / "data/projects.json").is_file()
    add("runtime_sot_still_in_repo", tracked_sot_still, "Expected until owner approves untrack")

    docker = (root / "Dockerfile").read_text(encoding="utf-8") if (root / "Dockerfile").is_file() else ""
    add("dockerfile_uses_data_seed", "COPY data_seed/" in docker and "COPY data/ /app/data_seed/" not in docker)

    passed = sum(1 for c in checks if c["ok"])
    ready_to_untrack = all(
        c["ok"]
        for c in checks
        if c["name"]
        in {
            "property_resolve_module",
            "public_projection_module",
            "backup_utility",
            "restore_drill",
            "data_seed_properties",
            "data_seed_projects",
            "data_seed_duplicate_shape",
            "dockerfile_uses_data_seed",
        }
    )

    return {
        "ok": ready_to_untrack,
        "passed": passed,
        "total": len(checks),
        "ready_to_untrack_sot_from_git": ready_to_untrack,
        "checks": checks,
        "blockers_if_untrack_now": [] if ready_to_untrack else ["complete failing checks first"],
        "owner_still_required": [
            "Fly volume backup schedule configured",
            "Production restore drill on staging volume",
            "fly secrets list verified",
            "Explicit owner approval to git rm --cached data/properties.json data/projects.json",
        ],
    }


def main() -> int:
    result = assess_migration_readiness()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
