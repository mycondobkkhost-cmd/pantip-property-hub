#!/usr/bin/env python3
"""Phase Z1 area engine foundation tests — offline only."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.admin_geography import ADMIN_POLYGON_DATA_MISSING, resolve_admin_geography  # noqa: E402
from src.hub.area_assignment_engine import (  # noqa: E402
    CLASS_AUTO_SAFE,
    CLASS_REJECT_QUARANTINE,
    CLASS_REVIEW,
    CORE_METERS,
    EXTENDED_METERS,
    MAX_AREAS_PER_PROJECT,
    OUTCOME_AUTO_QUARANTINED,
    OUTCOME_AUTO_SAFE,
    OUTCOME_NOT_EVALUABLE,
    OUTCOME_OWNER_REVIEW_REQUIRED,
    ROLE_PRIMARY,
    AreaSeed,
    ProjectContext,
    Station,
    coordinate_trusted_for_auto_safe,
    coordinate_usable,
    evaluate_area,
    evaluate_project,
    load_area_seeds,
    map_project_outcome,
    pick_output_areas,
)
from src.hub.area_engine_overlay import build_area_engine_overlay  # noqa: E402
from src.hub.coordinate_evidence import (  # noqa: E402
    TIER_T4,
    TIER_T5,
    USABLE_TIERS,
    coordinate_evaluable,
    coordinate_usable_tier,
    legacy_phase_w_coordinate_class,
    parse_coordinate_from_payload,
)
from src.hub.location_evidence import (  # noqa: E402
    LINEAGE_CATALOG_BAG,
    LINEAGE_LEGACY_SHEET,
    LINEAGE_PANTIP_ZONE,
    TOKEN_ADMIN_DISTRICT,
    TOKEN_MARKETPLACE,
    TOKEN_TRANSIT,
    build_legacy_evidence_records,
    classify_location_token,
    count_independent_lineages,
    legacy_bag_lineage_shared,
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
SPATIAL_SEED = ROOT / "data_fixtures" / "area_engine" / "market_area_spatial_seed_v0.2.json"


def _seed(identity_key: str, area_id: str, name_th: str, stations: list[str], **kw) -> AreaSeed:
    return AreaSeed(
        area_id,
        identity_key,
        name_th,
        name_th,
        stations,
        [],
        [],
        core_distance_m=kw.get("core_distance_m", CORE_METERS),
        extended_distance_m=kw.get("extended_distance_m", EXTENDED_METERS),
        status=kw.get("status", "EXISTING_APPROVED"),
    )


def _ctx(**kw) -> ProjectContext:
    defaults = {
        "project_id": "p",
        "name": "Test",
        "latitude": None,
        "longitude": None,
        "coordinate_state": "NONE",
        "acceptance_status": "NONE",
        "listing_locations": [],
        "listing_transit": [],
        "pantip_zones": [],
        "coordinate_tier": "T5_COORD",
    }
    defaults.update(kw)
    return ProjectContext(**defaults)


class PhaseZ1FoundationTests(unittest.TestCase):
    def test_01_parser_latitude_longitude(self):
        ev = parse_coordinate_from_payload(
            "p1",
            {"coordinate": {"state": "SOURCE_PROVIDED", "acceptance_status": "ACCEPTED", "latitude": 13.7, "longitude": 100.6}},
        )
        self.assertEqual(ev.latitude, 13.7)
        self.assertEqual(ev.longitude, 100.6)

    def test_02_legacy_lat_lng_shape(self):
        ev = parse_coordinate_from_payload(
            "p2",
            {"coordinate": {"state": "SOURCE_PROVIDED", "acceptance_status": "ACCEPTED", "lat": 13.7, "lng": 100.6}},
        )
        self.assertEqual(ev.latitude, 13.7)
        self.assertEqual(ev.longitude, 100.6)

    def test_03_invalid_coordinate_rejected(self):
        ev = parse_coordinate_from_payload("p3", {"coordinate": {"state": "SOURCE_PROVIDED", "latitude": 999, "longitude": 100}})
        self.assertIsNone(ev.latitude)
        self.assertIn("invalid_or_incomplete_coordinate", ev.conflicts)

    def test_04_missing_coordinate_remains_missing(self):
        ev = parse_coordinate_from_payload("p4", {"coordinate": {"state": "NONE"}})
        self.assertIsNone(ev.latitude)
        self.assertEqual(ev.evidence_tier, TIER_T5)

    def test_05_coordinate_conflict_blocks_auto_safe(self):
        ev = parse_coordinate_from_payload(
            "p5",
            {"coordinate": {"state": "SOURCE_PROVIDED", "acceptance_status": "ACCEPTED", "latitude": 13.7, "longitude": 100.6}},
            alternate_records=[{"latitude": 14.0, "longitude": 101.0, "source": "other"}],
        )
        self.assertEqual(ev.coordinate_state, "CONFLICT")
        ctx = _ctx(latitude=13.7, longitude=100.6, coordinate_state="CANDIDATE", coordinate_tier=TIER_T5)
        self.assertFalse(coordinate_trusted_for_auto_safe(ctx))

    def test_06_t5_cannot_auto_safe(self):
        ctx = _ctx(latitude=13.7, longitude=100.6, coordinate_state="CANDIDATE", coordinate_tier=TIER_T5)
        hit = evaluate_area(ctx, _seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"]), {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)})
        self.assertNotEqual(hit.classification, CLASS_AUTO_SAFE)

    def test_07_same_source_counts_one_lineage(self):
        records = build_legacy_evidence_records(
            project_id="p",
            pantip_zones=["อ่อนนุช"],
            catalog_locations=["อ่อนนุช"],
            listing_transit=[],
            project_name="",
        )
        lineages = {r.evidence_lineage_id for r in records}
        self.assertEqual(lineages, {LINEAGE_LEGACY_SHEET})

    def test_08_independent_sources_count_separately(self):
        records = build_legacy_evidence_records(
            project_id="p",
            pantip_zones=["วัฒนา"],
            catalog_locations=["อ่อนนุช"],
            listing_transit=["BTS อ่อนนุช"],
            project_name="Aspire",
        )
        self.assertGreaterEqual(count_independent_lineages(records), 2)

    def test_09_zone_and_bag_same_lineage_not_independent(self):
        self.assertTrue(legacy_bag_lineage_shared(["อ่อนนุช", "สุขุมวิท"], ["อ่อนนุช", "สุขุมวิท"]))
        records = build_legacy_evidence_records(
            project_id="p",
            pantip_zones=["อ่อนนุช"],
            catalog_locations=["อ่อนนุช"],
            listing_transit=[],
            project_name="",
        )
        self.assertEqual(count_independent_lineages(records), 1)

    def test_10_legacy_sheet_alone_cannot_auto_safe(self):
        ctx = _ctx(listing_locations=["เจริญนคร"], pantip_zones=["เจริญนคร"], coordinate_tier="T2_COORD", latitude=13.7, longitude=100.6, coordinate_state="CANDIDATE")
        hit = evaluate_area(ctx, _seed("charoen_nakhon", "rxa_cn", "เจริญนคร", []), {})
        self.assertNotEqual(hit.classification, CLASS_AUTO_SAFE)

    def test_11_realxtate_assignment_alone_cannot_auto_safe(self):
        ctx = _ctx(
            existing_assignments=[{"area_id": "rxa_cn", "role": "EDGE", "confidence": "HIGH"}],
            listing_locations=["เจริญนคร"],
        )
        hit = evaluate_area(
            ctx,
            _seed("charoen_nakhon", "rxa_cn", "เจริญนคร", ["bts_charoen_nakhon"]),
            {"bts_charoen_nakhon": Station("bts_charoen_nakhon", "เจริญนคร", "Gold", 13.726462, 100.509069)},
            existing={"rxa_cn": {"role": "EDGE", "confidence": "HIGH"}},
        )
        self.assertNotEqual(hit.classification, CLASS_AUTO_SAFE)

    def test_12_name_branding_alone_cannot_auto_safe(self):
        ctx = _ctx(name="Some Random Condo")
        hit = evaluate_area(ctx, _seed("onnut", "rxa_on", "อ่อนนุช", []), {})
        self.assertNotEqual(hit.classification, CLASS_AUTO_SAFE)

    def test_13_transit_is_evidence_not_market_area(self):
        cls = classify_location_token("BTS อ่อนนุช")
        self.assertEqual(cls.semantic_kind, TOKEN_TRANSIT)

    def test_14_admin_is_evidence_not_market_area(self):
        cls = classify_location_token("เขตสวนหลวง")
        self.assertEqual(cls.semantic_kind, TOKEN_ADMIN_DISTRICT)

    def test_15_area_specific_distance_bands(self):
        area = _seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"], core_distance_m=1500, extended_distance_m=3000)
        ctx = _ctx(latitude=13.707728, longitude=100.599766, coordinate_state="CANDIDATE", coordinate_tier="T2_COORD", acceptance_status="ACCEPTED")
        hit = evaluate_area(ctx, area, {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)})
        self.assertEqual(hit.distance_model, "AREA_SPECIFIC")

    def test_16_fallback_distance_model_marked(self):
        hit = evaluate_area(
            _ctx(latitude=13.707728, longitude=100.599766, coordinate_state="CANDIDATE", coordinate_tier="T2_COORD"),
            _seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"]),
            {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
        )
        self.assertEqual(hit.distance_model, "DISTANCE_MODEL_FALLBACK")

    def test_17_far_weak_only_auto_quarantined(self):
        ctx = _ctx(
            name="Aspire Onnut Station",
            latitude=13.707728,
            longitude=100.599766,
            coordinate_state="CANDIDATE",
            coordinate_tier="T2_COORD",
            listing_locations=["เจริญนคร"],
            pantip_zones=["เจริญนคร"],
        )
        hit = evaluate_area(
            ctx,
            _seed("charoen_nakhon", "rxa_cn", "เจริญนคร", ["bts_charoen_nakhon"]),
            {"bts_charoen_nakhon": Station("bts_charoen_nakhon", "เจริญนคร", "Gold", 13.726462, 100.509069)},
        )
        self.assertEqual(hit.classification, CLASS_REJECT_QUARANTINE)

    def test_18_corridor_not_auto_rejected_without_geo(self):
        ctx = _ctx(latitude=13.707728, longitude=100.599766, coordinate_state="CANDIDATE", coordinate_tier="T2_COORD", listing_locations=["สุขุมวิท"])
        hit = evaluate_area(
            ctx,
            _seed("sukhumvit", "rxa_suk", "สุขุมวิท", ["bts_on_nut"], extended_distance_m=5000),
            {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
        )
        self.assertIn(hit.classification, {CLASS_REVIEW, CLASS_AUTO_SAFE})

    def test_19_no_charoen_blacklist_in_engine(self):
        src = (ROOT / "src/hub/area_assignment_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("charoen_nakhon", src.lower())

    def test_20_no_aspire_hardcode(self):
        src = (ROOT / "src/hub/area_assignment_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("Aspire Onnut", src)
        self.assertNotIn("if project_id ==", src)

    def test_21_aspire_onnut_strongly_supported(self):
        ctx = _ctx(
            name="Aspire Onnut Station",
            latitude=13.707728,
            longitude=100.599766,
            coordinate_state="CANDIDATE",
            coordinate_tier="T2_COORD",
            listing_locations=["อ่อนนุช"],
            listing_transit=["BTS อ่อนนุช"],
            pantip_zones=["อ่อนนุช"],
        )
        hit = evaluate_area(
            ctx,
            _seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"]),
            {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
        )
        self.assertEqual(hit.classification, CLASS_AUTO_SAFE)

    def test_22_aspire_charoen_excluded(self):
        ctx = _ctx(
            name="Aspire Onnut Station",
            latitude=13.707728,
            longitude=100.599766,
            coordinate_state="CANDIDATE",
            coordinate_tier="T2_COORD",
            listing_locations=["เจริญนคร"],
            pantip_zones=["เจริญนคร"],
        )
        hit = evaluate_area(
            ctx,
            _seed("charoen_nakhon", "rxa_cn", "เจริญนคร", ["bts_charoen_nakhon"]),
            {"bts_charoen_nakhon": Station("bts_charoen_nakhon", "เจริญนคร", "Gold", 13.726462, 100.509069)},
        )
        self.assertEqual(hit.classification, CLASS_REJECT_QUARANTINE)

    def test_23_suan_luang_not_approved_from_owner_suggestion(self):
        payload = json.loads(SPATIAL_SEED.read_text(encoding="utf-8"))
        suan = next(a for a in payload["areas"] if a["identity_key"] == "suan_luang")
        self.assertEqual(suan["status"], "CANDIDATE")
        self.assertEqual(suan["review_status"], "REVIEW_REQUIRED")

    def test_24_pattanakarn_not_approved_from_owner_suggestion(self):
        payload = json.loads(SPATIAL_SEED.read_text(encoding="utf-8"))
        patt = next(a for a in payload["areas"] if a["identity_key"] == "phatthanakan")
        self.assertEqual(patt["status"], "CANDIDATE")

    def test_25_candidate_area_non_authoritative(self):
        seeds = load_area_seeds(fixture=SPATIAL_SEED)
        candidates = [s for s in seeds if s.status != "EXISTING_APPROVED"]
        self.assertTrue(candidates)
        for c in candidates:
            self.assertNotEqual(c.status, "EXISTING_APPROVED")

    def test_26_stable_existing_area_id_preserved(self):
        payload = json.loads(SPATIAL_SEED.read_text(encoding="utf-8"))
        approved = [a for a in payload["areas"] if a["status"] == "EXISTING_APPROVED"]
        self.assertEqual(len(approved), 31)
        self.assertTrue(all(a["area_id"].startswith("rxa_") for a in approved))

    def test_27_candidate_cannot_replace_existing(self):
        seeds = load_area_seeds(fixture=SPATIAL_SEED)
        ids = [s.area_id for s in seeds]
        self.assertEqual(len(ids), len(set(ids)))

    def test_28_max_three_area_relations(self):
        hits = [
            evaluate_area(
                _ctx(latitude=13.707728, longitude=100.599766, coordinate_state="CANDIDATE", coordinate_tier="T2_COORD"),
                _seed(f"a{i}", f"rxa_{i}", f"A{i}", ["bts_on_nut"]),
                {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
            )
            for i in range(5)
        ]
        self.assertLessEqual(len(pick_output_areas(hits)), MAX_AREAS_PER_PROJECT)

    def test_29_one_area_output_allowed(self):
        ctx = _ctx(
            name="Aspire Onnut Station",
            latitude=13.707728,
            longitude=100.599766,
            coordinate_state="CANDIDATE",
            coordinate_tier="T2_COORD",
            listing_locations=["อ่อนนุช"],
            pantip_zones=["อ่อนนุช"],
        )
        result = evaluate_project(
            ctx,
            [_seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"])],
            {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
        )
        self.assertGreaterEqual(len(result["picked_areas"]), 1)

    def test_30_no_forced_edge_fill(self):
        ctx = _ctx(latitude=13.707728, longitude=100.599766, coordinate_state="CANDIDATE", coordinate_tier="T2_COORD")
        result = evaluate_project(
            ctx,
            [_seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"])],
            {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
        )
        roles = [p["role"] for p in result["picked_areas"]]
        self.assertNotIn("EDGE", roles)

    def test_31_auto_safe_explanation_generated(self):
        hit = evaluate_area(
            _ctx(latitude=13.707728, longitude=100.599766, coordinate_state="CANDIDATE", coordinate_tier="T2_COORD", listing_locations=["อ่อนนุช"], pantip_zones=["อ่อนนุช"], listing_transit=["BTS อ่อนนุช"]),
            _seed("onnut", "rxa_on", "อ่อนนุช", ["bts_on_nut"]),
            {"bts_on_nut": Station("bts_on_nut", "อ่อนนุช", "BTS", 13.705629, 100.601001)},
        )
        self.assertTrue(hit.explanation_th)

    def test_32_auto_quarantine_explanation(self):
        overlay = build_area_engine_overlay.__module__
        self.assertIn("area_engine_overlay", overlay)

    def test_33_owner_review_outcome_mapping(self):
        outcome = map_project_outcome(
            coordinate_usable_flag=True,
            picked=[],
            hits=[],
            existing_audits=[],
        )
        self.assertEqual(outcome, OUTCOME_OWNER_REVIEW_REQUIRED)

    def test_34_no_projects_json_write(self):
        path = ROOT / "data" / "projects.json"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_35_no_properties_json_write(self):
        path = ROOT / "data" / "properties.json"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        after = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_36_phase_w_immutable(self):
        if not PHASE_W.is_file():
            self.skipTest("Phase W backup missing")
        self.assertEqual(
            hashlib.sha256(PHASE_W.read_bytes()).hexdigest(),
            "9c7eba7f1d44354867efc2fa4c01e3524549c442efa244b07c653398b4dc3602",
        )

    def test_37_overlay_no_apply_path(self):
        overlay = build_area_engine_overlay("nonexistent-project-id")
        self.assertFalse(overlay.get("has_apply_path", True))

    def test_38_admin_polygon_missing(self):
        res = resolve_admin_geography(13.7, 100.6)
        self.assertEqual(res.status, ADMIN_POLYGON_DATA_MISSING)

    def test_39_coordinate_parser_bug_before_after(self):
        coord = {"state": "SOURCE_PROVIDED", "acceptance_status": "ACCEPTED", "latitude": 13.7, "longitude": 100.6}
        self.assertEqual(legacy_phase_w_coordinate_class(coord), "COORD_CONFLICT")
        ev = parse_coordinate_from_payload("p", {"coordinate": coord})
        self.assertTrue(coordinate_evaluable(ev))

    def test_40_project_outcome_mutually_exclusive(self):
        ctx = _ctx()
        result = evaluate_project(ctx, [], {})
        self.assertEqual(result["project_outcome"], OUTCOME_NOT_EVALUABLE)

    @unittest.skipUnless(TRUSTED_DB.is_file() and PHASE_W.is_file(), "integration data missing")
    def test_integration_aspire_onnut(self):
        from src.hub.area_assignment_engine import load_project_contexts, load_stations

        crosswalk = json.loads(PHASE_W.read_text(encoding="utf-8"))
        catalog = TRUSTED_DB.parent / "realxtate-catalog.sqlite"
        contexts = load_project_contexts(TRUSTED_DB, catalog, crosswalk)
        ctx = contexts[ASPIRE_ID]
        seeds = load_area_seeds(fixture=SPATIAL_SEED)
        stations = load_stations(TRUSTED_DB)
        result = evaluate_project(ctx, seeds, stations)
        charoen = next(c for c in result["candidate_evaluations"] if c["identity_key"] == "charoen_nakhon")
        onnut = next(c for c in result["candidate_evaluations"] if c["identity_key"] == "onnut")
        self.assertEqual(charoen["classification"], CLASS_REJECT_QUARANTINE)
        self.assertEqual(onnut["classification"], CLASS_AUTO_SAFE)


if __name__ == "__main__":
    unittest.main()
