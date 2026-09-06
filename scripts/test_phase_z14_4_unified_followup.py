#!/usr/bin/env python3
"""Phase Z14.4 — unified Property Follow-up Center."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TODAY = date(2026, 9, 6)
HTML = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")


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
        "source_url": "https://example.com/s",
        "post_pages_url": "https://example.com/p",
    }
    base.update(kwargs)
    return base


def _build(props, *, state=None):
    from src.hub.upcoming_availability import build_upcoming_items

    tmp = Path(tempfile.mkdtemp(prefix="z144_"))
    st = state if state is not None else {"items": {}}
    (tmp / "upcoming_followup_state.json").write_text(json.dumps(st), encoding="utf-8")
    with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
        return build_upcoming_items(props, today=TODAY)


def _rows(data):
    return data["upcoming"] + data["overdue"]


class PhaseZ144UnifiedMatrix(unittest.TestCase):
    def test_A_annual(self) -> None:
        data = _build([_prop(id="A", last_posted_at="2025-09-20")])
        rows = _rows(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "ถึงรอบเช็ก")
        self.assertEqual(rows[0]["target_date"], "2026-09-20")
        self.assertEqual(rows[0]["days_until"], 14)
        self.assertIn("ถึงรอบเช็กวันที่", rows[0]["target_phrase"])
        self.assertNotIn("กำลังจะว่างวันที่", rows[0]["target_phrase"])

    def test_B_confirmed(self) -> None:
        data = _build([_prop(id="B", owner_confirmed_available_from="2026-09-20")])
        rows = _rows(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "ยืนยันวันว่าง")
        self.assertIn("กำลังจะว่างวันที่", rows[0]["target_phrase"])

    def test_C_confirmed_wins_over_annual(self) -> None:
        data = _build(
            [
                _prop(
                    id="C",
                    last_posted_at="2025-09-20",
                    owner_confirmed_available_from="2026-09-25",
                )
            ]
        )
        rows = _rows(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence"], "confirmed")
        self.assertEqual(rows[0]["target_date"], "2026-09-25")

    def test_D_recheck_within_window(self) -> None:
        data = _build(
            [_prop(id="D", last_posted_at="2025-09-20")],
            state={"items": {"D": {"recheck_after": "2026-09-25"}}},
        )
        rows = _rows(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_date"], "2026-09-25")
        self.assertEqual(rows[0]["evidence"], "operational_recheck")

    def test_E_confirmed_plus_recheck_preserves_vacancy(self) -> None:
        data = _build(
            [_prop(id="E", owner_confirmed_available_from="2026-09-20")],
            state={"items": {"E": {"recheck_after": "2026-09-15"}}},
        )
        rows = _rows(data)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["reason"], "ยืนยันวันว่าง")
        self.assertEqual(row["vacancy_date"], "2026-09-20")
        self.assertIn("กำลังจะว่างวันที่", row["vacancy_phrase"])
        self.assertEqual(row["target_date"], "2026-09-15")
        self.assertIn("เช็กอีกครั้งวันที่", row["recheck_phrase"])

    def test_F_legacy_listed_only_excluded(self) -> None:
        data = _build([_prop(id="F", last_listed_at="2025-09-20", last_posted_at="")])
        self.assertEqual(_rows(data), [])

    def test_G_sale_only_excluded(self) -> None:
        data = _build(
            [
                _prop(
                    id="G",
                    rent_price="",
                    sale_price="5000000",
                    last_posted_at="2025-09-20",
                )
            ]
        )
        self.assertEqual(_rows(data), [])

    def test_H_rent_sale_included(self) -> None:
        data = _build(
            [
                _prop(
                    id="H",
                    rent_price="15000",
                    sale_price="5000000",
                    last_posted_at="2025-09-20",
                )
            ]
        )
        self.assertEqual(len(_rows(data)), 1)

    def test_I_annual_plus_31_excluded(self) -> None:
        data = _build([_prop(id="I", last_posted_at="2025-10-10")])  # +34
        self.assertEqual(_rows(data), [])

    def test_J_annual_minus_31_excluded(self) -> None:
        data = _build([_prop(id="J", last_posted_at="2025-08-01")])  # -36
        self.assertEqual(_rows(data), [])

    def test_K_confirmed_plus_31_excluded(self) -> None:
        data = _build([_prop(id="K", owner_confirmed_available_from="2026-10-15")])
        self.assertEqual(_rows(data), [])

    def test_L_confirmed_minus_31_excluded(self) -> None:
        data = _build([_prop(id="L", owner_confirmed_available_from="2026-08-01")])
        self.assertEqual(_rows(data), [])

    def test_M_suppressed_excluded(self) -> None:
        data = _build(
            [_prop(id="M", last_posted_at="2025-09-20")],
            state={"items": {"M": {"suppressed": True, "reason": "x"}}},
        )
        self.assertEqual(_rows(data), [])

    def test_dedupe_one_row(self) -> None:
        data = _build(
            [
                _prop(
                    id="Z",
                    last_posted_at="2025-09-20",
                    owner_confirmed_available_from="2026-09-22",
                )
            ],
            state={"items": {"Z": {"recheck_after": "2026-09-10"}}},
        )
        self.assertEqual(len(_rows(data)), 1)
        self.assertEqual(data["counts"]["total"], 1)

    def test_center_title(self) -> None:
        data = _build([])
        self.assertEqual(data.get("center_title"), "ฟอโล่วห้องเก่า")


class PhaseZ144NavigationUI(unittest.TestCase):
    def test_N_no_per_card_follow(self) -> None:
        start = HTML.find("function propQuickActionsHtml")
        chunk = HTML[start : start + 700]
        self.assertNotIn("data-prop-follow", chunk)
        self.assertNotIn(">ติดตาม<", chunk)
        self.assertIn("ลิงก์ต้นโพส", chunk)
        self.assertIn("ลิงก์โพสเพจ", chunk)
        self.assertIn("แก้ไข", chunk)

    def test_O_strip_title(self) -> None:
        self.assertIn("ฟอโล่วห้องเก่า", HTML)
        self.assertIn('id="upcoming-strip"', HTML)
        self.assertIn("refreshUpcomingStrip", HTML)

    def test_P_Q_same_center(self) -> None:
        self.assertIn("openUpcomingPanel", HTML)
        self.assertIn('view === "followup"', HTML)
        self.assertIn("unified Property Follow-up Center", HTML)
        self.assertIn('id="upcoming-title">ฟอโล่วห้องเก่า', HTML)

    def test_R_badge_uses_property_counts(self) -> None:
        self.assertIn("function refreshPropertyFollowBadge", HTML)
        self.assertIn("refreshPropertyFollowBadge", HTML)
        # mobile badge driven by upcoming counts, not CRM due
        fn = HTML[HTML.find("function refreshPropertyFollowBadge") : HTML.find("function refreshPropertyFollowBadge") + 500]
        self.assertIn("upcomingCache.data", fn)
        self.assertNotIn("_fuBadgeDue", fn)

    def test_waiting_untouched_markers(self) -> None:
        self.assertIn("queue-panel", HTML)


class PhaseZ144Privacy(unittest.TestCase):
    def test_co_projection(self) -> None:
        from src.hub.public_projection import build_public_catalog_payload

        payload = build_public_catalog_payload(
            [],
            [
                {
                    "id": "1",
                    "code": "C",
                    "notes": "SECRET_NOTE_Z144",
                    "owner_confirmed_available_from": "2026-09-20",
                    "last_posted_at": "2025-09-06T10:00:00",
                    "owner_phones": ["0811111111"],
                    "rent_price": "10000",
                }
            ],
        )
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("SECRET_NOTE_Z144", blob)
        self.assertNotIn("owner_confirmed_available_from", blob)
        self.assertNotIn("0811111111", blob)


if __name__ == "__main__":
    unittest.main(verbosity=2)
