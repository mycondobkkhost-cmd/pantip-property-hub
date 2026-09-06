#!/usr/bin/env python3
"""Phase Z14.2 — last_posted_at annual rule + notes + stamp boundary."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 6)


def _prop(**kwargs):
    base = {
        "id": "x",
        "code": "X",
        "project_name": "P",
        "rent_price": "15000",
        "sale_price": "",
        "last_listed_at": "",
        "last_posted_at": "",
        "owner_confirmed_available_from": "",
        "notes": "",
        "source_url": "",
        "post_pages_url": "",
    }
    base.update(kwargs)
    return base


def _build(props, *, state=None):
    from src.hub.upcoming_availability import build_upcoming_items

    tmp = Path(tempfile.mkdtemp(prefix="z142_"))
    st = state if state is not None else {"items": {}}
    (tmp / "upcoming_followup_state.json").write_text(json.dumps(st), encoding="utf-8")
    with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
        return build_upcoming_items(props, today=TODAY)


class PhaseZ142WindowMatrix(unittest.TestCase):
    def _ids(self, data):
        return {x["property_id"] for x in data["upcoming"] + data["overdue"]}

    def test_A_posted_30_days(self) -> None:
        data = _build([_prop(id="A", last_posted_at="2025-10-06")])
        self.assertIn("A", self._ids(data))
        row = data["upcoming"][0]
        self.assertEqual(row["days_until"], 30)
        self.assertEqual(row["countdown"], "เหลืออีก 30 วัน")
        self.assertEqual(row["target_phrase"], "ถึงรอบเช็กวันที่ 6/10/26")
        self.assertEqual(row["label"], "ถึงรอบเช็ก")

    def test_B_posted_31_exclude(self) -> None:
        data = _build([_prop(id="B", last_posted_at="2025-10-07")])
        self.assertNotIn("B", self._ids(data))

    def test_C_posted_today(self) -> None:
        data = _build([_prop(id="C", last_posted_at="2025-09-06")])
        row = next(x for x in data["upcoming"] if x["property_id"] == "C")
        self.assertEqual(row["days_until"], 0)
        self.assertEqual(row["countdown"], "วันนี้")

    def test_D_posted_overdue(self) -> None:
        data = _build([_prop(id="D", last_posted_at="2025-08-20")])
        row = next(x for x in data["overdue"] if x["property_id"] == "D")
        self.assertEqual(row["days_until"], -17)
        self.assertEqual(row["countdown"], "เลยรอบเช็กมา 17 วัน")

    def test_E_posted_beyond_minus_30(self) -> None:
        data = _build([_prop(id="E", last_posted_at="2025-08-06")])
        self.assertNotIn("E", self._ids(data))

    def test_F_legacy_listed_only_excluded(self) -> None:
        data = _build(
            [_prop(id="F", last_listed_at="01/10/2025", last_posted_at="")]
        )
        self.assertNotIn("F", self._ids(data))

    def test_G_old_confirmed(self) -> None:
        data = _build(
            [
                _prop(
                    id="G",
                    last_listed_at="06/09/2023",
                    last_posted_at="",
                    owner_confirmed_available_from="2026-09-20",
                )
            ]
        )
        row = next(x for x in data["upcoming"] if x["property_id"] == "G")
        self.assertEqual(row["evidence"], "confirmed")
        self.assertEqual(row["target_phrase"], "กำลังจะว่างวันที่ 20/9/26")
        self.assertEqual(row["countdown"], "เหลืออีก 14 วัน")

    def test_H_legacy_vacancy(self) -> None:
        data = _build(
            [
                _prop(
                    id="H",
                    last_posted_at="",
                    available_raw="20/09/2026",
                    **{"วันที่ว่าง": "20/09/2026"},
                )
            ]
        )
        self.assertNotIn("H", self._ids(data))

    def test_I_confirmed_plus_31(self) -> None:
        data = _build(
            [_prop(id="I", owner_confirmed_available_from="2026-10-07")]
        )
        self.assertNotIn("I", self._ids(data))

    def test_J_confirmed_minus_30(self) -> None:
        data = _build(
            [_prop(id="J", owner_confirmed_available_from="2026-08-07")]
        )
        self.assertIn("J", self._ids(data))

    def test_K_confirmed_minus_31(self) -> None:
        data = _build(
            [_prop(id="K", owner_confirmed_available_from="2026-08-06")]
        )
        self.assertNotIn("K", self._ids(data))

    def test_L_sale_only(self) -> None:
        data = _build(
            [
                _prop(
                    id="L",
                    rent_price="",
                    sale_price="5000000",
                    last_posted_at="2025-09-20",
                )
            ]
        )
        self.assertNotIn("L", self._ids(data))

    def test_M_rent_only(self) -> None:
        data = _build([_prop(id="M", last_posted_at="2025-09-20")])
        self.assertIn("M", self._ids(data))

    def test_N_rent_sale(self) -> None:
        data = _build(
            [
                _prop(
                    id="N",
                    rent_price="20000",
                    sale_price="5000000",
                    last_posted_at="2025-09-20",
                )
            ]
        )
        self.assertIn("N", self._ids(data))

    def test_O_dedupe_confirmed_wins(self) -> None:
        data = _build(
            [
                _prop(
                    id="O",
                    last_posted_at="2025-09-20",
                    owner_confirmed_available_from="2026-09-20",
                )
            ]
        )
        rows = [x for x in data["upcoming"] + data["overdue"] if x["property_id"] == "O"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence"], "confirmed")

    def test_never_uses_last_listed_at_field(self) -> None:
        from src.hub import upcoming_availability as ua

        self.assertEqual(ua.ANNUAL_RECHECK_BASE_FIELD, "last_posted_at")
        self.assertNotEqual(ua.ANNUAL_RECHECK_BASE_FIELD, "last_listed_at")


class PhaseZ142StampBoundary(unittest.TestCase):
    def test_stamp_on_pages_url_change_not_ordinary_edit(self) -> None:
        from src.hub.project_store import stamp_last_posted_at_on_publish_url_change

        prop = {"id": "1", "last_posted_at": ""}
        self.assertFalse(
            stamp_last_posted_at_on_publish_url_change(
                prop,
                old_pages_url="https://fb.com/a",
                old_post_url="",
                new_pages_url="https://fb.com/a",
                new_post_url="",
            )
        )
        self.assertEqual(prop.get("last_posted_at"), "")
        self.assertTrue(
            stamp_last_posted_at_on_publish_url_change(
                prop,
                old_pages_url="",
                old_post_url="",
                new_pages_url="https://fb.com/posted/1",
                new_post_url="",
            )
        )
        first = prop["last_posted_at"]
        self.assertTrue(first)
        self.assertTrue(
            stamp_last_posted_at_on_publish_url_change(
                prop,
                old_pages_url="https://fb.com/posted/1",
                old_post_url="",
                new_pages_url="https://fb.com/posted/2",
                new_post_url="",
            )
        )
        self.assertTrue(prop["last_posted_at"])
        # clearing URL must not stamp
        before = prop["last_posted_at"]
        self.assertFalse(
            stamp_last_posted_at_on_publish_url_change(
                prop,
                old_pages_url="https://fb.com/posted/2",
                old_post_url="",
                new_pages_url="",
                new_post_url="",
            )
        )
        self.assertEqual(prop["last_posted_at"], before)

    def test_update_property_edit_without_url_change_preserves_stamp(self) -> None:
        from src.hub.project_store import update_property

        tmp = Path(tempfile.mkdtemp(prefix="z142s_"))
        prop = {
            "id": "pid-1",
            "code": "RXT9",
            "code_prefix": "RXT",
            "project_id": "proj-1",
            "project_name": "Tower",
            "rent_price": "10000",
            "sale_price": "",
            "post_pages_url": "https://fb.com/page/1",
            "post_url": "",
            "source_url": "https://fb.com/src/1",
            "notes": "keep",
            "last_posted_at": "2025-09-01T10:00:00",
            "last_listed_at": "01/09/2025",
            "owner_phones": [],
            "owner_lines": [],
            "owner_facebook": [],
            "property_type": "Condo",
            "bedrooms": "1",
            "size_sqm": "30",
            "floor": "5",
            "import_status": "active",
            "media_status": "has_link",
            "data_source": "hub",
            "listing_kind": "direct",
            "transit_from_sheet": "",
            "location_ref": "",
            "duplicate_flags": [],
            "sheet_row": "",
        }
        proj = {
            "id": "proj-1",
            "canonical_name": "Tower",
            "bucket_key": "tower",
            "aliases": [],
            "listing_count": 1,
            "transit_verified": [],
            "transit_unverified": [],
            "zone_verified": [],
            "location_status": "verified",
            "is_thru_thonglor": False,
        }
        (tmp / "properties.json").write_text(json.dumps([prop]), encoding="utf-8")
        (tmp / "projects.json").write_text(json.dumps([proj]), encoding="utf-8")
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            updated = update_property(
                "pid-1",
                {
                    "project_id": "proj-1",
                    "notes": "edited note only",
                    "rent_price": "11000",
                    "post_pages_url": "https://fb.com/page/1",
                    "post_url": "",
                    "source_url": "https://fb.com/src/1",
                    "code_prefix": "RXT",
                    "code": "RXT9",
                    "property_type": "Condo",
                    "bedrooms": "1",
                    "size_sqm": "30",
                    "floor": "5",
                    "sale_price": "",
                    "owner_phones": [],
                    "owner_lines": [],
                    "owner_facebook": [],
                },
            )
        self.assertEqual(updated["last_posted_at"], "2025-09-01T10:00:00")
        self.assertEqual(updated["notes"], "edited note only")


class PhaseZ142UiNotes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")

    def test_P_notes_main_and_upcoming(self) -> None:
        self.assertIn("หมายเหตุ:", self.html)
        self.assertIn("upcoming-row-notes", self.html)
        self.assertIn("prop-sheet-notes", self.css)
        self.assertIn("background: #f4f0fa !important", self.css)

    def test_Q_notes_escaped(self) -> None:
        chunk = self.html.split("function propCardHtml")[1].split("function scheduleThumbLoadsIn")[0]
        self.assertIn("esc(notesText)", chunk)
        up = self.html.split("function renderUpcomingList")[1].split("function openUpcomingPanel")[0]
        self.assertIn("esc(notesText)", up)

    def test_upcoming_has_thumb_and_direct_links(self) -> None:
        up = self.html.split("function renderUpcomingList")[1].split("function openUpcomingPanel")[0]
        self.assertIn("thumbCellHtml", up)
        self.assertIn("propQuickActionsHtml", up)
        self.assertIn("target_phrase", up)
        self.assertIn("scheduleThumbLoadsIn(\"#upcoming-list\")", up)

    def test_assets_z142(self) -> None:
        self.assertIn("mobile-operations.css?v=z14.2", self.html)

    def test_co_agent_privacy(self) -> None:
        from src.hub.public_projection import build_public_catalog_payload

        payload = build_public_catalog_payload(
            [],
            [
                {
                    "id": "1",
                    "code": "C",
                    "notes": "SECRET_NOTE_Z142",
                    "last_posted_at": "2025-09-06T10:00:00",
                    "owner_phones": ["0811111111"],
                    "source_url": "https://example.com/x",
                    "rent_price": "10000",
                }
            ],
        )
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("SECRET_NOTE_Z142", blob)
        self.assertNotIn("0811111111", blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
