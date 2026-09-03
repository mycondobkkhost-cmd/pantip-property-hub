#!/usr/bin/env python3
"""Phase W crosswalk safety tests — offline only."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_live_project_crosswalk import (  # noqa: E402
    assert_no_output_overlap,
    build_crosswalk,
    classify_match,
    correction_class,
    load_json,
    norm_area_token,
    soft_norm,
    zone_agreement,
)


def _make_rx_db(path: Path, projects: list[dict]) -> None:
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE property_projects (id TEXT, name TEXT, aliases_json TEXT, bucket_key TEXT, listing_count INT)"
    )
    for p in projects:
        cur.execute(
            "INSERT INTO property_projects VALUES (?,?,?,?,?)",
            (p["id"], p["name"], json.dumps(p.get("aliases", [])), p["bucket_key"], p.get("listing_count", 0)),
        )
    conn.commit()
    conn.close()


def _make_trusted_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE marketplace_area_assignment_8z3 (project_id TEXT, area_id TEXT, role TEXT, confidence TEXT)"
    )
    cur.execute("CREATE TABLE project_master_v01 (project_id TEXT, payload_json TEXT)")
    conn.commit()
    conn.close()


class PhaseWCrosswalkTests(unittest.TestCase):
    def test_exact_id_dominates_fuzzy_name(self):
        pid = str(uuid.uuid4())
        pantip = {"id": pid, "bucket_key": "alpha", "canonical_name": "Alpha Tower"}
        rx_by_id = {pid: {"id": pid, "bucket_key": "alpha", "name": "Different Label"}}
        rx_by_bucket = {"alpha": rx_by_id[pid]}
        rx_by_norm = {"differentlabel": [{"id": "other", "bucket_key": "beta", "name": "Different Label"}]}
        match_class, rx_id, _ = classify_match(pantip, rx_by_id, rx_by_bucket, rx_by_norm)
        self.assertEqual(match_class, "EXACT_ID_MATCH")
        self.assertEqual(rx_id, pid)

    def test_same_name_different_id_not_auto_merge(self):
        pantip = {"id": "id-a", "bucket_key": "alpha", "canonical_name": "Alpha"}
        rx_by_id: dict = {}
        rx_by_bucket: dict = {}
        rx_by_norm = {"alpha": [{"id": "id-b", "bucket_key": "beta", "name": "Alpha"}]}
        match_class, _, _ = classify_match(pantip, rx_by_id, rx_by_bucket, rx_by_norm)
        self.assertEqual(match_class, "CONFLICT")
        self.assertNotEqual(correction_class(match_class, "INSUFFICIENT_EVIDENCE", "NO_REALXTATE_AREA", 1), "AUTO_SAFE")

    def test_fuzzy_only_never_auto_safe(self):
        corr = correction_class("LOW_CONFIDENCE_CANDIDATE", "INSUFFICIENT_EVIDENCE", "NO_REALXTATE_AREA", 10)
        self.assertIn(corr, ("MANUAL_REQUIRED", "DO_NOT_TOUCH"))
        self.assertNotEqual(corr, "AUTO_SAFE")

    def test_duplicate_canonical_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            dup_id = str(uuid.uuid4())
            projects = [
                {"id": dup_id, "bucket_key": "a", "canonical_name": "A"},
                {"id": dup_id, "bucket_key": "b", "canonical_name": "B"},
            ]
            (data / "projects.json").write_text(json.dumps(projects), encoding="utf-8")
            (data / "properties.json").write_text("[]", encoding="utf-8")
            catalog = data / "catalog.sqlite"
            trusted = data / "trusted.sqlite"
            _make_rx_db(catalog, [])
            _make_trusted_db(trusted)
            out = data / "out"
            argv = [
                "build_live_project_crosswalk.py",
                "--pantip-projects",
                str(data / "projects.json"),
                "--pantip-properties",
                str(data / "properties.json"),
                "--realxtate-catalog",
                str(catalog),
                "--realxtate-trusted",
                str(trusted),
                "--output-dir",
                str(out),
            ]
            with self.assertRaises(ValueError):
                import build_live_project_crosswalk as mod

                old = sys.argv
                sys.argv = argv
                try:
                    mod.main()
                finally:
                    sys.argv = old

    def test_input_files_remain_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            projects = [{"id": str(uuid.uuid4()), "bucket_key": "alpha", "canonical_name": "Alpha"}]
            props = [{"id": "p1", "project_id": projects[0]["id"]}]
            proj_path = data / "projects.json"
            prop_path = data / "properties.json"
            proj_path.write_text(json.dumps(projects), encoding="utf-8")
            prop_path.write_text(json.dumps(props), encoding="utf-8")
            before = {
                proj_path: hashlib.sha256(proj_path.read_bytes()).hexdigest(),
                prop_path: hashlib.sha256(prop_path.read_bytes()).hexdigest(),
            }
            catalog = data / "catalog.sqlite"
            trusted = data / "trusted.sqlite"
            _make_rx_db(
                catalog,
                [{"id": projects[0]["id"], "name": "Alpha", "bucket_key": "alpha", "aliases": []}],
            )
            _make_trusted_db(trusted)
            out = data / "output"
            import build_live_project_crosswalk as mod

            sys.argv = [
                "x",
                "--pantip-projects",
                str(proj_path),
                "--pantip-properties",
                str(prop_path),
                "--realxtate-catalog",
                str(catalog),
                "--realxtate-trusted",
                str(trusted),
                "--output-dir",
                str(out),
            ]
            mod.main()
            after = {
                proj_path: hashlib.sha256(proj_path.read_bytes()).hexdigest(),
                prop_path: hashlib.sha256(prop_path.read_bytes()).hexdigest(),
            }
            self.assertEqual(before, after)

    def test_malformed_input_fails_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "projects.json").write_text('{"not": "a list"}', encoding="utf-8")
            (data / "properties.json").write_text("[]", encoding="utf-8")
            catalog = data / "catalog.sqlite"
            trusted = data / "trusted.sqlite"
            _make_rx_db(catalog, [])
            _make_trusted_db(trusted)
            import build_live_project_crosswalk as mod

            sys.argv = [
                "x",
                "--pantip-projects",
                str(data / "projects.json"),
                "--pantip-properties",
                str(data / "properties.json"),
                "--realxtate-catalog",
                str(catalog),
                "--realxtate-trusted",
                str(trusted),
                "--output-dir",
                str(data / "out"),
            ]
            with self.assertRaises(ValueError):
                mod.main()

    def test_no_personal_fields_exported(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            pid = str(uuid.uuid4())
            projects = [{"id": pid, "bucket_key": "alpha", "canonical_name": "Alpha"}]
            props = [
                {
                    "id": "p1",
                    "project_id": pid,
                    "owner_phones": ["0812345678"],
                    "owner_lines": ["line-secret"],
                    "text_th": "tenant info",
                }
            ]
            (data / "projects.json").write_text(json.dumps(projects), encoding="utf-8")
            (data / "properties.json").write_text(json.dumps(props), encoding="utf-8")
            catalog = data / "catalog.sqlite"
            trusted = data / "trusted.sqlite"
            _make_rx_db(catalog, [{"id": pid, "name": "Alpha", "bucket_key": "alpha"}])
            _make_trusted_db(trusted)
            out = data / "out"
            import build_live_project_crosswalk as mod

            sys.argv = [
                "x",
                "--pantip-projects",
                str(data / "projects.json"),
                "--pantip-properties",
                str(data / "properties.json"),
                "--realxtate-catalog",
                str(catalog),
                "--realxtate-trusted",
                str(trusted),
                "--output-dir",
                str(out),
            ]
            mod.main()
            payload = (out / "live-project-crosswalk.json").read_text(encoding="utf-8")
            self.assertNotIn("0812345678", payload)
            self.assertNotIn("line-secret", payload)
            self.assertNotIn("tenant info", payload)

    def test_semantic_area_kinds_prevent_false_conflict(self):
        self.assertEqual(
            zone_agreement(["วัฒนา"], [{"area_id": "thonglor", "confidence": "HIGH"}]),
            "SEMANTICALLY_DIFFERENT_BUT_NOT_CONFLICT",
        )
        self.assertEqual(
            zone_agreement(["ทองหล่อ"], [{"area_id": "thonglor", "confidence": "HIGH"}]),
            "AGREE",
        )

    def test_analysis_deterministic(self):
        projects = [
            {
                "id": str(uuid.uuid4()),
                "bucket_key": "alpha",
                "canonical_name": "Alpha",
                "zone_verified": ["ทองหล่อ"],
                "zone_unverified": ["ทองหล่อ"],
                "transit_verified": ["BTS ทองหล่อ"],
                "transit_unverified": ["BTS ทองหล่อ"],
            }
        ]
        props = [{"id": "p1", "project_id": projects[0]["id"]}]
        rx = [{"id": projects[0]["id"], "name": "Alpha", "bucket_key": "alpha", "aliases": []}]
        areas = {projects[0]["id"]: [{"area_id": "thonglor", "role": "PRIMARY", "confidence": "HIGH"}]}
        coords = {projects[0]["id"]: "COORD_MISSING"}
        a, _ = build_crosswalk(projects, props, rx, areas, coords)
        b, _ = build_crosswalk(projects, props, rx, areas, coords)
        self.assertEqual(a, b)

    def test_output_path_cannot_overlap_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inp = root / "projects.json"
            inp.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                assert_no_output_overlap([inp], root)


class HelperTests(unittest.TestCase):
    def test_soft_norm_thonglor(self):
        self.assertIn("thonglor", soft_norm("Thong Lo"))

    def test_norm_area_token_thai(self):
        self.assertEqual(norm_area_token("ทองหล่อ"), "thonglor")


if __name__ == "__main__":
    unittest.main()
