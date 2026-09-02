#!/usr/bin/env python3
"""Phase B property identity safety tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def ptp4734_fixture() -> list[dict]:
    """Synthetic duplicate-code shape modeled after PTP4734 — no production PII."""
    return [
        {
            "id": f"pid-4734-{i}",
            "code": "PTP4734",
            "project_id": f"proj-{i}",
            "project_name": f"Project {i}",
            "rent_price": f"{15000 + i * 1000}",
            "import_status": "active",
        }
        for i in range(1, 4)
    ]


class PhaseBIdentityTests(unittest.TestCase):
    def test_resolve_by_id_unique(self) -> None:
        from src.hub.property_resolve import resolve_by_id

        props = ptp4734_fixture()
        res = resolve_by_id(props, "pid-4734-2")
        self.assertTrue(res.ok)
        assert res.record is not None
        self.assertEqual(res.record["id"], "pid-4734-2")

    def test_missing_id_not_found(self) -> None:
        from src.hub.property_resolve import resolve_by_id

        res = resolve_by_id(ptp4734_fixture(), "missing")
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "PROPERTY_NOT_FOUND")

    def test_unique_code_ok(self) -> None:
        from src.hub.property_resolve import resolve_for_action

        props = [{"id": "only", "code": "RXT0001"}]
        res = resolve_for_action(props, property_code="RXT0001")
        self.assertTrue(res.ok)

    def test_duplicate_code_ambiguous(self) -> None:
        from src.hub.property_resolve import resolve_for_action

        res = resolve_for_action(ptp4734_fixture(), property_code="PTP4734")
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "PROPERTY_CODE_AMBIGUOUS")
        self.assertEqual(res.match_count, 3)
        self.assertEqual(len(res.candidates or []), 3)

    def test_duplicate_code_never_first_match_helper(self) -> None:
        from src.hub.publish_caption import find_property_by_code

        with mock.patch(
            "src.hub.publish_caption.load_properties_cached",
            return_value=ptp4734_fixture(),
        ):
            self.assertIsNone(find_property_by_code("PTP4734"))

    def test_write_by_duplicate_code_blocked(self) -> None:
        from src.hub.project_store import set_property_page_post_text

        with mock.patch("src.hub.project_store.load_properties", return_value=ptp4734_fixture()), mock.patch(
            "src.hub.project_store.load_projects", return_value=[]
        ), mock.patch("src.hub.project_store.persist") as persist:
            out = set_property_page_post_text("caption", code="PTP4734")
            self.assertIsNone(out)
            persist.assert_not_called()

    def test_caption_duplicate_code_blocked(self) -> None:
        from src.hub.publish_caption import build_no_link_captions

        with mock.patch(
            "src.hub.publish_caption.load_properties_cached",
            return_value=ptp4734_fixture(),
        ), mock.patch(
            "src.hub.publish_caption.generate_caption_variants_no_links",
            return_value=[],
        ):
            result = build_no_link_captions("PTP4734")
        self.assertFalse(result.get("ok"))
        self.assertEqual(result.get("error_code"), "PROPERTY_CODE_AMBIGUOUS")

    def test_fb_job_with_property_id_resolves(self) -> None:
        from src.hub.group_post_publish_store import list_due_for_publish
        from src.hub.property_resolve import resolve_job_property

        props = ptp4734_fixture()
        job = {"id": "j1", "property_id": "pid-4734-2", "property_code": "PTP4734"}
        res = resolve_job_property(props, job)
        self.assertTrue(res.ok)
        assert res.record is not None
        self.assertEqual(res.record["id"], "pid-4734-2")

    def test_legacy_fb_job_duplicate_code_blocked(self) -> None:
        from src.hub.property_resolve import resolve_job_property

        job = {"id": "j1", "property_code": "PTP4734"}
        res = resolve_job_property(ptp4734_fixture(), job)
        self.assertFalse(res.ok)
        self.assertEqual(res.error_code, "PROPERTY_CODE_AMBIGUOUS")

    def test_list_due_for_publish_filters_ambiguous(self) -> None:
        from src.hub.group_post_publish_store import list_due_for_publish

        jobs = [
            {
                "id": "good",
                "status": "pending",
                "property_id": "pid-4734-1",
                "property_code": "PTP4734",
                "next_post_at": "",
            },
            {
                "id": "bad",
                "status": "pending",
                "property_code": "PTP4734",
                "next_post_at": "",
            },
        ]
        with mock.patch(
            "src.hub.group_post_publish_store.list_due",
            return_value=jobs,
        ), mock.patch(
            "src.hub.project_store.load_properties",
            return_value=ptp4734_fixture(),
        ):
            safe, blocked = list_due_for_publish(limit=5)
        self.assertEqual(len(safe), 1)
        self.assertEqual(blocked, 1)
        self.assertEqual(safe[0]["identity_status"], "ok")

    def test_co_catalog_rows_have_property_id(self) -> None:
        from src.hub.co_catalog import slim_property

        prop = ptp4734_fixture()[0]
        prop["post_url"] = "https://www.facebook.com/example/post"
        row = slim_property(prop, {"id": "proj-1", "canonical_name": "P1"})
        assert row is not None
        self.assertEqual(row["property_id"], "pid-4734-1")

    def test_focus_add_duplicate_code_errors(self) -> None:
        from src.hub.focus_store import add_focus_codes

        with self.assertRaises(ValueError):
            add_focus_codes(["PTP4734"], ptp4734_fixture())


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PhaseBIdentityTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
