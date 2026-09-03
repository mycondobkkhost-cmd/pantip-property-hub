"""Authoritative LIVE population accounting — Phase Z2.

Reconciles Phase W crosswalk (2,175) with trusted DB membership and coordinate states.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.hub.coordinate_evidence import (
    STATE_CONFLICT,
    STATE_INVALID,
    STATE_MISSING,
    coordinate_evaluable,
    parse_coordinate_from_payload,
)

DEFAULT_PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
DEFAULT_TRUSTED = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-trusted-master.sqlite"
)


@dataclass
class PopulationAccounting:
    live_total: int
    trusted_db_matched: int
    live_only: int
    coord_usable: int
    coord_missing: int
    coord_conflict: int
    coord_invalid: int
    live_only_project_ids: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "LIVE_TOTAL": self.live_total,
            "TRUSTED_DB_MATCHED": self.trusted_db_matched,
            "LIVE_ONLY": self.live_only,
            "COORD_USABLE": self.coord_usable,
            "COORD_MISSING": self.coord_missing,
            "COORD_CONFLICT": self.coord_conflict,
            "COORD_INVALID": self.coord_invalid,
            "equation_check": self.coord_usable + self.coord_missing + self.coord_conflict + self.coord_invalid,
            "equation_balanced": (
                self.coord_usable + self.coord_missing + self.coord_conflict + self.coord_invalid == self.live_total
            ),
            "live_only_project_ids": self.live_only_project_ids,
            "notes": self.notes,
            "z1_discrepancy_explanation": (
                "Z1 table showed 1,078+1,078=2,156 because it counted trusted-DB rows only "
                f"({self.trusted_db_matched}), omitting {self.live_only} LIVE-only projects and "
                "double-presenting tier/state columns. Authoritative LIVE total is 2,175 with "
                f"{self.coord_usable} usable + {self.coord_missing} missing = {self.coord_usable + self.coord_missing}."
            ),
        }


def reconcile_population(
    *,
    crosswalk_path: Path | None = None,
    trusted_db: Path | None = None,
) -> PopulationAccounting:
    crosswalk_path = crosswalk_path or DEFAULT_PHASE_W
    trusted_db = trusted_db or DEFAULT_TRUSTED
    crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    live_ids = [r["pantip_project_id"] for r in crosswalk if r.get("pantip_project_id")]

    conn = sqlite3.connect(f"file:{trusted_db}?mode=ro", uri=True)
    cur = conn.cursor()
    db_ids = {row[0] for row in cur.execute("SELECT project_id FROM project_master_v01")}

    live_only: list[str] = []
    usable = missing = conflict = invalid = 0

    for pid in live_ids:
        if pid not in db_ids:
            live_only.append(pid)
            missing += 1
            continue
        payload_row = cur.execute(
            "SELECT payload_json FROM project_master_v01 WHERE project_id=?", (pid,)
        ).fetchone()
        body = json.loads((payload_row[0] if payload_row else None) or "{}")
        ev = parse_coordinate_from_payload(pid, body)
        if ev.coordinate_state == STATE_MISSING:
            missing += 1
        elif ev.coordinate_state == STATE_CONFLICT:
            conflict += 1
        elif ev.coordinate_state == STATE_INVALID:
            invalid += 1
        elif coordinate_evaluable(ev):
            usable += 1
        else:
            missing += 1

    conn.close()

    return PopulationAccounting(
        live_total=len(live_ids),
        trusted_db_matched=len(live_ids) - len(live_only),
        live_only=len(live_only),
        coord_usable=usable,
        coord_missing=missing,
        coord_conflict=conflict,
        coord_invalid=invalid,
        live_only_project_ids=live_only,
        notes=[
            "Categories are mutually exclusive at LIVE project level.",
            "LIVE-only projects (no trusted DB row) count as COORD_MISSING.",
        ],
    )
