#!/usr/bin/env python3
"""Local dry-run for RealXtate export eligibility — no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.project_store import load_projects, load_properties  # noqa: E402
from src.hub.realxtate_export import (  # noqa: E402
    EXPORT_SCHEMA,
    assert_export_private_safe,
    evaluate_export_eligibility,
    project_realxtate_export,
)


def main() -> int:
    projects = {p.get("id"): p for p in load_projects()}
    props = load_properties()
    eligible = 0
    ineligible = 0
    samples: list[dict] = []
    for prop in props[:500]:
        proj = projects.get(prop.get("project_id")) or {}
        ev = evaluate_export_eligibility(prop, proj)
        if ev["eligible"]:
            eligible += 1
            if len(samples) < 3:
                ex = project_realxtate_export(prop, proj)
                leaked = assert_export_private_safe(ex)
                if leaked:
                    print("LEAK:", leaked, file=sys.stderr)
                    return 1
                samples.append({k: v for k, v in ex.items() if not k.startswith("_")})
        else:
            ineligible += 1
    out = {
        "schema": EXPORT_SCHEMA,
        "scanned": min(len(props), 500),
        "eligible_count": eligible,
        "ineligible_count": ineligible,
        "network_calls": 0,
        "samples": samples,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
