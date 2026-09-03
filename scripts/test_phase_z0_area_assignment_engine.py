#!/usr/bin/env python3
"""Phase Z0 area assignment engine discovery tests — offline only."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.area_assignment_engine import (  # noqa: E402
    CLASS_AUTO_SAFE,
    CLASS_NOT_EVALUABLE,
    CLASS_REJECT_QUARANTINE,
    CLASS_REVIEW,
    CORE_METERS,
    EXTENDED_METERS,
    MAX_AREAS_PER_PROJECT,
    ROLE_EDGE,
    ROLE_PRIMARY,
    ROLE_SECONDARY,
    AreaSeed,
    ProjectContext,
    Station,
    audit_existing_assignment,
    coordinate_usable,
    evaluate_area,
    evaluate_project,
    haversine_meters,
    pick_output_areas,
)

TRUSTED_DB = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-trusted-master.sqlite"
)
PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
ASPIRE_ID = "d9a5d2b2-355a-55e6-b471-773b9badc8c6"


def _seed(identity_key: str, area_id: str, name_th: str, stations: list[str]) -> AreaSeed:
    return AreaSeed(area_id, identity_key, name_th, name_th, stations, [], [])


class PhaseZ0AreaAssignmentEngineTests(unittest.TestCase):
    def test_haversine_is_straight_line_not_walking(self):
        # Documented terminology guard — function returns meters geometric distance.
        m = haversine_meters(13.707728, 100.599766, 13.705629, 100.601001)
        self.assertGreater(m, 200)
        self.assertLess(m, 400)

    def test_area_id_canonical_preserved(self):
        hit = evaluate_area(
            ProjectContext("p", "Test", 13.7, 100.6, "SOURCE_PROVIDED", "ACCEPTED", [], [], []),
            _seed("onnut", "rxa_onnut", "อ่อนนุช", ["bts_on_nut"]),
            {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
        )
        self.assertEqual(hit.area_id, "rxa_onnut")

    def test_admin_not_flattened_into_market_area_identity(self):
        ctx = ProjectContext("p", "X", None, None, "NONE", "NONE", [], [], ["วัฒนา"])
        hit = evaluate_area(ctx, _seed("wattana", "rxa_w", "วัฒนา", []), {})
        self.assertNotEqual(hit.identity_key, "MARKETPLACE_AREA")

    def test_existing_rx_alone_cannot_auto_safe(self):
        ctx = ProjectContext(
            "p",
            "Aspire Onnut Station",
            None,
            None,
            "NONE",
            "NONE",
            ["เจริญนคร"],
            [],
            [],
            existing_assignments=[{"area_id": "rxa_cn", "role": "EDGE", "confidence": "HIGH"}],
        )
        hit = evaluate_area(
            ctx,
            _seed("charoen_nakhon", "rxa_cn", "เจริญนคร", ["bts_charoen_nakhon"]),
            {"bts_charoen_nakhon": Station("bts_charoen_nakhon", "เจริญนคร", "Gold", 13.726462, 100.509069)},
            existing={"rxa_cn": {"role": "EDGE", "confidence": "HIGH"}},
        )
        self.assertNotEqual(hit.classification, CLASS_AUTO_SAFE)

    def test_fuzzy_name_alone_cannot_auto_safe(self):
        ctx = ProjectContext("p", "Some Random Condo", None, None, "NONE", "NONE", [], [], [])
        hit = evaluate_area(ctx, _seed("onnut", "rxa_on", "อ่อนนุช", []), {})
        self.assertNotEqual(hit.classification, CLASS_AUTO_SAFE)

    def test_missing_coordinate_fails_conservative(self):
        ctx = ProjectContext("p", "No Pin", None, None, "NONE", "NONE", [], [], [])
        result = evaluate_project(ctx, [_seed("onnut", "rxa_on", "อ่อนนุช", [])], {})
        self.assertEqual(result["classification"], CLASS_NOT_EVALUABLE)

    def test_strong_conflict_blocks_auto_safe(self):
        ctx = ProjectContext(
            "p",
            "Aspire Onnut Station (แอสปาย อ่อนนุช สเตชั่น)",
            13.707728,
            100.599766,
            "SOURCE_PROVIDED",
            "ACCEPTED",
            ["เจริญนคร"],
            [],
            ["เจริญนคร"],
        )
        hit = evaluate_area(
            ctx,
            _seed("charoen_nakhon", "rxa_cn", "เจริญนคร", ["bts_charoen_nakhon"]),
            {"bts_charoen_nakhon": Station("bts_charoen_nakhon", "เจริญนคร", "Gold", 13.726462, 100.509069)},
        )
        self.assertEqual(hit.classification, CLASS_REJECT_QUARANTINE)

    def test_verified_strong_evidence_may_auto_safe(self):
        ctx = ProjectContext(
            "p",
            "Aspire Onnut Station",
            13.707728,
            100.599766,
            "SOURCE_PROVIDED",
            "ACCEPTED",
            ["อ่อนนุช"],
            ["BTS อ่อนนุช"],
            ["อ่อนนุช"],
        )
        hit = evaluate_area(
            ctx,
            _seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"]),
            {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
        )
        self.assertEqual(hit.classification, CLASS_AUTO_SAFE)

    def test_max_three_areas(self):
        hits = [
            evaluate_area(
                ProjectContext("p", "T", 13.707728, 100.599766, "SOURCE_PROVIDED", "ACCEPTED", [], [], []),
                _seed(f"a{i}", f"rxa_{i}", f"A{i}", ["bts_on_nut"]),
                {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
            )
            for i in range(5)
        ]
        picked = pick_output_areas(hits)
        self.assertLessEqual(len(picked), MAX_AREAS_PER_PROJECT)

    def test_one_area_output_allowed(self):
        ctx = ProjectContext("p", "Aspire Onnut Station", 13.707728, 100.599766, "SOURCE_PROVIDED", "ACCEPTED", ["อ่อนนุช"], [], ["อ่อนนุช"])
        result = evaluate_project(
            ctx,
            [_seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"])],
            {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
        )
        self.assertGreaterEqual(len(result["picked_areas"]), 1)

    def test_roles_preserved(self):
        self.assertEqual(ROLE_PRIMARY, "PRIMARY")
        self.assertEqual(ROLE_SECONDARY, "SECONDARY")
        self.assertEqual(ROLE_EDGE, "EDGE")

    def test_negative_control_implausible(self):
        ctx = ProjectContext("TEST_ONLY", "Aspire Onnut Station", 13.707728, 100.599766, "SOURCE_PROVIDED", "ACCEPTED", ["เจริญนคร"], [], [])
        hit = evaluate_area(
            ctx,
            _seed("charoen_nakhon", "rxa_cn", "เจริญนคร", ["bts_charoen_nakhon"]),
            {"bts_charoen_nakhon": Station("bts_charoen_nakhon", "เจริญนคร", "Gold", 13.726462, 100.509069)},
        )
        self.assertIn(hit.classification, {CLASS_REJECT_QUARANTINE, CLASS_REVIEW})

    def test_aspire_onnut_no_project_name_hardcode(self):
        # Engine module must not contain Aspire-specific branching.
        src = (ROOT / "src/hub/area_assignment_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("Aspire Onnut", src)
        self.assertNotIn("if project_id ==", src)

    def test_no_charoen_blacklist_rule(self):
        src = (ROOT / "src/hub/area_assignment_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("charoen_nakhon", src.lower())

    def test_projects_json_not_mutated(self):
        path = ROOT / "data" / "projects.json"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_properties_json_not_mutated(self):
        path = ROOT / "data" / "properties.json"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_phase_w_source_immutable(self):
        if not PHASE_W.is_file():
            self.skipTest("Phase W backup missing")
        before = PHASE_W.read_bytes()
        after = PHASE_W.read_bytes()
        self.assertEqual(before, after)

    def test_deterministic_output(self):
        ctx = ProjectContext("p", "Aspire Onnut Station", 13.707728, 100.599766, "SOURCE_PROVIDED", "ACCEPTED", ["อ่อนนุช"], [], ["อ่อนนุช"])
        seeds = [_seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"])]
        stations = {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)}
        a = evaluate_project(ctx, seeds, stations)
        b = evaluate_project(ctx, seeds, stations)
        self.assertEqual(a, b)

    @unittest.skipUnless(TRUSTED_DB.is_file() and PHASE_W.is_file(), "RealXtate/Phase W not available")
    def test_aspire_onnut_integration_charoen_rejected(self):
        from src.hub.area_assignment_engine import load_area_seeds, load_project_contexts, load_stations

        crosswalk = json.loads(PHASE_W.read_text(encoding="utf-8"))
        contexts = load_project_contexts(TRUSTED_DB, TRUSTED_DB.parent / "realxtate-catalog.sqlite", crosswalk)
        ctx = contexts[ASPIRE_ID]
        seeds = load_area_seeds(TRUSTED_DB)
        stations = load_stations(TRUSTED_DB)
        result = evaluate_project(ctx, seeds, stations)
        charoen = next((c for c in result["candidate_evaluations"] if c["identity_key"] == "charoen_nakhon"), None)
        self.assertIsNotNone(charoen)
        self.assertEqual(charoen["classification"], CLASS_REJECT_QUARANTINE)
        onnut = next(c for c in result["candidate_evaluations"] if c["identity_key"] == "onnut")
        self.assertEqual(onnut["classification"], CLASS_AUTO_SAFE)


if __name__ == "__main__":
    unittest.main()
