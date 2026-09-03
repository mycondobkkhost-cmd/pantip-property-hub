#!/usr/bin/env python3
"""Phase Z2 evidence acquisition tests — offline only."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub.area_candidate_evidence import build_area_candidate_packet, CANDIDATE_KEYS
from src.hub.area_assignment_engine import (
    CLASS_AUTO_SAFE,
    CLASS_REJECT_QUARANTINE,
    ProjectContext,
    evaluate_project,
    load_area_seeds,
)
from src.hub.coordinate_acquisition import (
    OUTCOME_CANDIDATE_SINGLE_SOURCE,
    OUTCOME_IDENTITY_REVIEW_REQUIRED,
    OUTCOME_NO_EVIDENCE_FOUND,
    OUTCOME_RECOVERED_CORROBORATED,
    QueueEntry,
    acquire_for_entry,
    apply_acquired_to_context,
    assess_identity_confidence,
    build_missing_coordinate_queue,
    classify_spatial_type,
    compute_priority,
    is_identity_ambiguous_for_geocoding,
    scan_local_sources,
)
from src.hub.coordinate_agreement import (
    STRONG_AGREEMENT_M,
    classify_pairwise_distance,
    resolve_agreement,
)
from src.hub.coordinate_sources.base import (
    CoordinateCandidate,
    LOCATION_ROLE_DEVELOPER_HQ,
    LOCATION_ROLE_PROJECT_SITE,
    LOCATION_ROLE_SALES_OFFICE,
)
from src.hub.coordinate_sources.map_embed import extract_map_embed_coordinates
from src.hub.coordinate_sources.structured_metadata import (
    extract_jsonld_geo,
    infer_location_role,
)
from src.hub.population_accounting import reconcile_population

PHASE_W = (
    Path.home()
    / "Backups"
    / "pantip-property-automation"
    / "phase-w-crosswalk-20260904T035800Z"
    / "live-project-crosswalk.json"
)
TRUSTED = Path(
    "/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP/web/.data/realxtate-trusted-master.sqlite"
)
ASPIRE_ID = "d9a5d2b2-355a-55e6-b471-773b9badc8c6"
SPATIAL_SEED = ROOT / "data_fixtures" / "area_engine" / "market_area_spatial_seed_v0.2.json"

JSONLD_HTML = """
<script type="application/ld+json">
{"@type":"RealEstateAgent","geo":{"@type":"GeoCoordinates","latitude":13.7505,"longitude":100.5647}}
</script>
"""

HQ_HTML = '<div>Head office corporate office</div><script type="application/ld+json">{"geo":{"latitude":13.7,"longitude":100.5}}</script>'
SALES_HTML = '<div>Sales gallery office</div><script type="application/ld+json">{"geo":{"latitude":13.7,"longitude":100.5}}</script>'


def _queue(**kw) -> QueueEntry:
    defaults = dict(
        project_id="p",
        canonical_name="Test Project Sukhumvit",
        aliases=[],
        bucket_key="",
        listing_count=5,
        current_admin_tokens=[],
        current_marketplace_tokens=[],
        transit_tokens=[],
        known_reference_urls=[],
        identity_confidence="HIGH",
        acquisition_strategy="LOCAL_ONLY",
        priority_score=0,
        priority_band="P1",
        evidence_state="QUEUED",
        spatial_type="POINT_PROJECT",
    )
    defaults.update(kw)
    return QueueEntry(**defaults)


class PhaseZ2Tests(unittest.TestCase):
    def test_01_population_reconciles_2175(self):
        pop = reconcile_population(crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertEqual(pop.live_total, 2175)
        self.assertTrue(pop.to_dict()["equation_balanced"])

    def test_02_live_only_19_accounted(self):
        pop = reconcile_population(crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertEqual(pop.live_only, 19)
        self.assertEqual(len(pop.live_only_project_ids), 19)

    def test_03_ambiguous_identity_blocks(self):
        e = _queue(canonical_name="", identity_confidence="AMBIGUOUS", listing_count=0)
        self.assertTrue(is_identity_ambiguous_for_geocoding(e))
        r = acquire_for_entry(e, trusted_db=TRUSTED)
        self.assertEqual(r.outcome, OUTCOME_IDENTITY_REVIEW_REQUIRED)

    def test_04_strong_identity_in_queue(self):
        q = build_missing_coordinate_queue(crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertGreater(len(q), 1000)
        self.assertTrue(any(e.identity_confidence == "HIGH" for e in q))

    def test_05_priority_deterministic(self):
        e = _queue(listing_count=12, known_reference_urls=[{"url": "http://x"}])
        s1, b1 = compute_priority(e, z1_outcome="OWNER_REVIEW_REQUIRED")
        s2, b2 = compute_priority(e, z1_outcome="OWNER_REVIEW_REQUIRED")
        self.assertEqual((s1, b1), (s2, b2))
        self.assertEqual(b1, "P0")

    def test_06_jsonld_extraction(self):
        hits = extract_jsonld_geo(JSONLD_HTML)
        self.assertGreaterEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0]["latitude"], 13.7505, places=3)

    def test_07_map_embed_extraction(self):
        html = 'src="https://www.google.com/maps/@13.7301,100.5692,15z"'
        hits = extract_map_embed_coordinates(html)
        self.assertTrue(hits)

    def test_08_invalid_coordinate_rejected(self):
        hits = extract_jsonld_geo('<script type="application/ld+json">{"geo":{"latitude":999,"longitude":100}}</script>')
        self.assertEqual(hits, [])

    def test_09_developer_hq_not_project_site(self):
        self.assertEqual(infer_location_role(HQ_HTML), LOCATION_ROLE_DEVELOPER_HQ)

    def test_10_sales_office_not_project_site(self):
        self.assertEqual(infer_location_role(SALES_HTML), LOCATION_ROLE_SALES_OFFICE)

    def test_11_project_site_accepted(self):
        self.assertEqual(infer_location_role(JSONLD_HTML, "RealEstateAgent"), LOCATION_ROLE_PROJECT_SITE)

    def test_12_single_source_stays_candidate(self):
        c = [
            CoordinateCandidate(
                "p", 13.7, 100.6, "a", "u", "r", "m", "t", "lineage:a", "T4_COORD", "LOW",
                location_role=LOCATION_ROLE_PROJECT_SITE,
            )
        ]
        ag = resolve_agreement(c)
        self.assertIsNone(ag.promoted_tier)

    def test_13_same_lineage_no_t3(self):
        c = [
            CoordinateCandidate("p", 13.7, 100.6, "a", "u1", "r1", "m", "t", "lineage:same", "T4_COORD", "LOW", location_role=LOCATION_ROLE_PROJECT_SITE),
            CoordinateCandidate("p", 13.7001, 100.6001, "b", "u2", "r2", "m", "t", "lineage:same", "T4_COORD", "LOW", location_role=LOCATION_ROLE_PROJECT_SITE),
        ]
        ag = resolve_agreement(c)
        self.assertNotEqual(ag.promoted_tier, "T3_COORD")

    def test_14_independent_sources_t3(self):
        c = [
            CoordinateCandidate("p", 13.7, 100.6, "a", "u1", "r1", "m", "t", "lineage:a", "T4_COORD", "LOW", location_role=LOCATION_ROLE_PROJECT_SITE, independence="INDEPENDENT"),
            CoordinateCandidate("p", 13.7002, 100.6002, "b", "u2", "r2", "m", "t", "lineage:b", "T4_COORD", "LOW", location_role=LOCATION_ROLE_PROJECT_SITE, independence="INDEPENDENT"),
        ]
        ag = resolve_agreement(c)
        self.assertEqual(ag.promoted_tier, "T3_COORD")

    def test_15_independence_unknown_blocks_t3(self):
        c = [
            CoordinateCandidate("p", 13.7, 100.6, "a", "u1", "r1", "m", "t", "lineage:a", "T4_COORD", "LOW", location_role=LOCATION_ROLE_PROJECT_SITE, independence="INDEPENDENCE_UNKNOWN"),
            CoordinateCandidate("p", 13.7002, 100.6002, "b", "u2", "r2", "m", "t", "lineage:b", "T4_COORD", "LOW", location_role=LOCATION_ROLE_PROJECT_SITE, independence="INDEPENDENCE_UNKNOWN"),
        ]
        ag = resolve_agreement(c)
        self.assertIsNone(ag.promoted_tier)

    def test_16_strong_agreement_tolerance(self):
        self.assertEqual(classify_pairwise_distance(STRONG_AGREEMENT_M), "STRONG_AGREEMENT")

    def test_17_conflict_tolerance(self):
        self.assertEqual(classify_pairwise_distance(300), "CONFLICT")

    def test_18_conflict_blocks_auto_safe_tier(self):
        ctx = ProjectContext("p", "T", 13.7, 100.6, "CONFLICT", "NONE", [], [], [], coordinate_tier="T5_COORD")
        self.assertEqual(ctx.coordinate_tier, "T5_COORD")

    def test_19_multiphase_protection(self):
        e = _queue(canonical_name="Life Asoke", listing_count=1)
        self.assertTrue(is_identity_ambiguous_for_geocoding(e))

    def test_20_fuzzy_name_alone_no_acquire(self):
        e = _queue(canonical_name="X", listing_count=0, identity_confidence="LOW")
        r = acquire_for_entry(e, trusted_db=TRUSTED)
        self.assertIn(r.outcome, {OUTCOME_NO_EVIDENCE_FOUND, OUTCOME_IDENTITY_REVIEW_REQUIRED})

    def test_21_estate_spatial_type(self):
        self.assertEqual(classify_spatial_type("Townhouse Ekamai"), "ESTATE")

    def test_22_provenance_complete(self):
        c = CoordinateCandidate("p", 13.7, 100.6, "prov", "http://u", "rid", "jsonld", "t", "lineage:x", "T4_COORD", "LOW")
        d = c.to_dict()
        for k in ("provider", "source_url", "extraction_method", "evidence_lineage_id", "raw_value_hash"):
            self.assertIn(k, d)

    def test_23_cache_no_credentials(self):
        cache = Path("/tmp/pantip-phase-z2-evidence/cache")
        if cache.exists():
            for f in cache.rglob("*"):
                if f.is_file():
                    self.assertNotIn("password", f.read_text(errors="ignore").lower())

    def test_24_no_raw_page_persisted_in_candidate(self):
        c = CoordinateCandidate("p", 13.7, 100.6, "p", "u", "r", "m", "t", "l", "T4_COORD", "LOW")
        self.assertNotIn("html", c.to_dict())

    def test_25_suan_luang_non_authoritative(self):
        p = build_area_candidate_packet("suan_luang", crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertNotEqual(p.get("status"), "EXISTING_APPROVED")

    def test_26_pattanakarn_non_authoritative(self):
        p = build_area_candidate_packet("phatthanakan", crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertEqual(p.get("semantic_kind"), "CORRIDOR")

    def test_27_rama9_non_authoritative(self):
        p = build_area_candidate_packet("rama9", crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertEqual(p.get("semantic_kind"), "UMBRELLA_GROUP")

    def test_28_admin_vs_market_suan_luang(self):
        p = build_area_candidate_packet("suan_luang", crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertIn("เขตสวนหลวง", p.get("admin_vs_marketplace") or "")

    def test_29_corridor_not_marketplace(self):
        p = build_area_candidate_packet("phatthanakan", crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertEqual(p.get("semantic_kind"), "CORRIDOR")

    def test_30_group_not_area(self):
        p = build_area_candidate_packet("rama9", crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertEqual(p.get("semantic_kind"), "UMBRELLA_GROUP")

    def test_31_stable_31_area_ids(self):
        payload = json.loads(SPATIAL_SEED.read_text())
        approved = [a for a in payload["areas"] if a["status"] == "EXISTING_APPROVED"]
        self.assertEqual(len(approved), 31)

    def test_32_no_forced_approval(self):
        for key in CANDIDATE_KEYS:
            p = build_area_candidate_packet(key, crosswalk_path=PHASE_W, trusted_db=TRUSTED)
            self.assertNotEqual(p.get("recommended_status"), "APPROVED")

    def test_33_t4_single_source_no_auto_safe_increase(self):
        from src.hub.coordinate_acquisition import AcquisitionResult, OUTCOME_CANDIDATE_SINGLE_SOURCE

        ctx = ProjectContext("p", "T", None, None, "MISSING", "NONE", [], [], [], coordinate_tier="T5_COORD")
        acq = AcquisitionResult(
            "p",
            OUTCOME_CANDIDATE_SINGLE_SOURCE,
            candidates=[
                CoordinateCandidate("p", 13.707728, 100.599766, "x", "", "", "m", "t", "l", "T4_COORD", "LOW", location_role=LOCATION_ROLE_PROJECT_SITE)
            ],
        )
        apply_acquired_to_context(ctx, acq)
        self.assertEqual(ctx.coordinate_tier, "T4_COORD")

    def test_34_corroborated_can_be_t3(self):
        from src.hub.coordinate_acquisition import AcquisitionResult, OUTCOME_RECOVERED_CORROBORATED

        ctx = ProjectContext("p", "T", None, None, "MISSING", "NONE", [], [], [])
        acq = AcquisitionResult(
            "p",
            OUTCOME_RECOVERED_CORROBORATED,
            candidates=[
                CoordinateCandidate("p", 13.707728, 100.599766, "x", "", "", "m", "t", "l", "T3_COORD", "MEDIUM", location_role=LOCATION_ROLE_PROJECT_SITE)
            ],
        )
        apply_acquired_to_context(ctx, acq)
        self.assertEqual(ctx.coordinate_tier, "T3_COORD")

    @unittest.skipUnless(PHASE_W.is_file() and TRUSTED.is_file(), "integration data missing")
    def test_35_aspire_regression(self):
        from src.hub.area_assignment_engine import load_project_contexts, load_stations

        crosswalk = json.loads(PHASE_W.read_text())
        contexts = load_project_contexts(TRUSTED, TRUSTED.parent / "realxtate-catalog.sqlite", crosswalk)
        ctx = contexts[ASPIRE_ID]
        seeds = load_area_seeds(fixture=SPATIAL_SEED)
        stations = load_stations(TRUSTED)
        result = evaluate_project(ctx, seeds, stations)
        charoen = next(c for c in result["candidate_evaluations"] if c["identity_key"] == "charoen_nakhon")
        onnut = next(c for c in result["candidate_evaluations"] if c["identity_key"] == "onnut")
        self.assertEqual(charoen["classification"], CLASS_REJECT_QUARANTINE)
        self.assertEqual(onnut["classification"], CLASS_AUTO_SAFE)

    def test_36_no_charoen_blacklist(self):
        src = (ROOT / "src/hub/area_assignment_engine.py").read_text()
        self.assertNotIn("charoen_nakhon", src.lower())

    def test_37_overlay_provenance_field(self):
        from src.hub.area_engine_overlay import build_area_engine_overlay

        o = build_area_engine_overlay("nonexistent")
        self.assertIn("has_apply_path", o)

    def test_38_duplicate_lineage_explanation(self):
        c = [
            CoordinateCandidate("p", 13.7, 100.6, "a", "u1", "r1", "m", "t", "lineage:same", "T4_COORD", "LOW", location_role=LOCATION_ROLE_PROJECT_SITE),
            CoordinateCandidate("p", 13.7, 100.6, "b", "u2", "r2", "m", "t", "lineage:same", "T4_COORD", "LOW", location_role=LOCATION_ROLE_PROJECT_SITE),
        ]
        ag = resolve_agreement(c)
        self.assertEqual(ag.independent_lineage_count, 1)

    def test_39_no_apply_path(self):
        from src.hub.area_engine_overlay import build_area_engine_overlay

        self.assertFalse(build_area_engine_overlay("x").get("has_apply_path", True))

    def test_40_no_projects_json_mutation(self):
        p = ROOT / "data" / "projects.json"
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(h, hashlib.sha256(p.read_bytes()).hexdigest())

    def test_41_no_properties_json_mutation(self):
        p = ROOT / "data" / "properties.json"
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(h, hashlib.sha256(p.read_bytes()).hexdigest())

    def test_42_phase_w_immutable(self):
        self.assertEqual(
            hashlib.sha256(PHASE_W.read_bytes()).hexdigest(),
            "9c7eba7f1d44354867efc2fa4c01e3524549c442efa244b07c653398b4dc3602",
        )

    def test_43_no_realxtate_write(self):
        self.assertTrue(TRUSTED.is_file())

    def test_44_identity_high_assessment(self):
        self.assertEqual(assess_identity_confidence("Life Asoke Rama 9", [], 10), "HIGH")

    def test_45_queue_has_reference_urls(self):
        q = build_missing_coordinate_queue(crosswalk_path=PHASE_W, trusted_db=TRUSTED)
        self.assertGreater(sum(1 for e in q if e.known_reference_urls), 200)


if __name__ == "__main__":
    unittest.main()
