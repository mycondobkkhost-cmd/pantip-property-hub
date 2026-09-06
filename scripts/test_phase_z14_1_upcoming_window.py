#!/usr/bin/env python3
"""Phase Z14.1 — fixed TODAY=2026-09-06 upcoming window matrix + notes card checks."""

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
    }
    base.update(kwargs)
    return base


def _build(props, *, state=None):
    from src.hub.upcoming_availability import build_upcoming_items

    tmp = Path(tempfile.mkdtemp(prefix="z141_"))
    st = state if state is not None else {"items": {}}
    (tmp / "upcoming_followup_state.json").write_text(
        json.dumps(st), encoding="utf-8"
    )
    with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
        return build_upcoming_items(props, today=TODAY)


class PhaseZ141WindowMatrix(unittest.TestCase):
    def _ids(self, data):
        return {x["property_id"] for x in data["upcoming"] + data["overdue"]}

    def test_A_annual_30_days_upcoming(self) -> None:
        # posting 2025-10-06 → anniversary 2026-10-06 → +30
        data = _build([_prop(id="A", code="A", last_posted_at="06/10/2025")])
        self.assertIn("A", self._ids(data))
        row = data["upcoming"][0]
        self.assertEqual(row["days_until"], 30)
        self.assertEqual(row["countdown"], "เหลืออีก 30 วัน")
        self.assertEqual(row["label"], "ถึงรอบเช็ก")

    def test_B_annual_31_days_exclude(self) -> None:
        data = _build([_prop(id="B", last_posted_at="07/10/2025")])
        self.assertNotIn("B", self._ids(data))

    def test_C_annual_today(self) -> None:
        data = _build([_prop(id="C", last_posted_at="06/09/2025")])
        self.assertIn("C", self._ids(data))
        row = next(x for x in data["upcoming"] if x["property_id"] == "C")
        self.assertEqual(row["days_until"], 0)
        self.assertEqual(row["countdown"], "วันนี้")

    def test_D_annual_overdue_within_30(self) -> None:
        data = _build([_prop(id="D", last_posted_at="20/08/2025")])
        self.assertIn("D", self._ids(data))
        row = next(x for x in data["overdue"] if x["property_id"] == "D")
        self.assertEqual(row["days_until"], -17)
        self.assertEqual(row["countdown"], "เลยรอบเช็กมา 17 วัน")

    def test_E_annual_overdue_beyond_30(self) -> None:
        # anniversary 2026-08-06 → 31 days overdue on 2026-09-06
        data = _build([_prop(id="E", last_posted_at="06/08/2025")])
        self.assertNotIn("E", self._ids(data))
        # boundary include at -30: anniversary 2026-08-07
        data2 = _build([_prop(id="E2", last_posted_at="07/08/2025")])
        self.assertIn("E2", self._ids(data2))
        row = next(x for x in data2["overdue"] if x["property_id"] == "E2")
        self.assertEqual(row["days_until"], -30)

    def test_F_second_anniversary_trap_2024(self) -> None:
        # Must NOT roll 2024-09-06 → 2026-09-06
        data = _build([_prop(id="F", last_posted_at="06/09/2024")])
        self.assertNotIn("F", self._ids(data))

    def test_G_third_anniversary_trap_2023(self) -> None:
        data = _build([_prop(id="G", last_posted_at="06/09/2023")])
        self.assertNotIn("G", self._ids(data))

    def test_H_sale_only_excluded(self) -> None:
        data = _build(
            [
                _prop(
                    id="H",
                    rent_price="",
                    sale_price="5000000",
                    last_posted_at="20/09/2025",
                )
            ]
        )
        self.assertNotIn("H", self._ids(data))

    def test_I_rent_plus_sale_included(self) -> None:
        data = _build(
            [
                _prop(
                    id="I",
                    rent_price="20000",
                    sale_price="5000000",
                    last_posted_at="20/09/2025",
                )
            ]
        )
        self.assertIn("I", self._ids(data))

    def test_J_old_with_confirmed_included(self) -> None:
        data = _build(
            [
                _prop(
                    id="J",
                    last_posted_at="06/09/2023",
                    owner_confirmed_available_from="2026-09-20",
                )
            ]
        )
        self.assertIn("J", self._ids(data))
        row = next(x for x in data["upcoming"] if x["property_id"] == "J")
        self.assertEqual(row["evidence"], "confirmed")
        self.assertEqual(row["label"], "ยืนยันวันว่าง")
        self.assertEqual(row["days_until"], 14)

    def test_K_legacy_vacancy_ignored(self) -> None:
        data = _build(
            [
                _prop(
                    id="K",
                    last_posted_at="06/09/2023",
                    available_raw="20/09/2026",
                    **{"วันที่ว่าง": "20/09/2026"},
                )
            ]
        )
        self.assertNotIn("K", self._ids(data))

    def test_L_confirmed_plus_31_excluded(self) -> None:
        data = _build(
            [
                _prop(
                    id="L",
                    last_posted_at="01/01/2026",
                    owner_confirmed_available_from="2026-10-07",
                )
            ]
        )
        self.assertNotIn("L", self._ids(data))

    def test_M_confirmed_minus_30_boundary(self) -> None:
        data = _build(
            [
                _prop(
                    id="M",
                    last_posted_at="01/01/2026",
                    owner_confirmed_available_from="2026-08-07",
                )
            ]
        )
        self.assertIn("M", self._ids(data))
        row = next(x for x in data["overdue"] if x["property_id"] == "M")
        self.assertEqual(row["days_until"], -30)

    def test_N_confirmed_beyond_minus_30(self) -> None:
        data = _build(
            [
                _prop(
                    id="N",
                    last_posted_at="01/01/2026",
                    owner_confirmed_available_from="2026-08-06",
                )
            ]
        )
        self.assertNotIn("N", self._ids(data))

    def test_O_confirmed_wins_dedupe(self) -> None:
        data = _build(
            [
                _prop(
                    id="O",
                    last_posted_at="20/09/2025",  # annual also in window
                    owner_confirmed_available_from="2026-09-20",
                )
            ]
        )
        rows = [x for x in data["upcoming"] + data["overdue"] if x["property_id"] == "O"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evidence"], "confirmed")
        self.assertEqual(rows[0]["label"], "ยืนยันวันว่าง")

    def test_P_suppressed_excluded(self) -> None:
        data = _build(
            [_prop(id="P", last_posted_at="06/09/2025")],
            state={"items": {"P": {"suppressed": True, "reason": "test"}}},
        )
        self.assertNotIn("P", self._ids(data))

    def test_countdown_tomorrow(self) -> None:
        from src.hub.upcoming_availability import countdown_label

        self.assertEqual(countdown_label(1), "เหลืออีก 1 วัน")
        self.assertEqual(countdown_label(14), "เหลืออีก 14 วัน")


class PhaseZ141MainCardNotes(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")

    def test_notes_render_uses_property_notes_escaped(self) -> None:
        chunk = self.html.split("function propCardHtml")[1].split("function scheduleThumbLoadsIn")[0]
        self.assertIn("var notesText = String(p.notes || \"\").trim();", chunk)
        self.assertIn("หมายเหตุ:", chunk)
        self.assertIn("esc(notesText)", chunk)
        self.assertIn("prop-sheet-notes", chunk)

    def test_notes_mobile_visible(self) -> None:
        self.assertIn(".prop-sheet-notes", self.css)
        self.assertIn("display: block !important", self.css)

    def test_co_agent_notes_absent(self) -> None:
        from src.hub.public_projection import build_public_catalog_payload

        payload = build_public_catalog_payload(
            [],
            [
                {
                    "id": "1",
                    "code": "C",
                    "notes": "SECRET_NOTE_Z141",
                    "owner_phones": ["0811111111"],
                    "source_url": "https://example.com/x",
                    "rent_price": "10000",
                }
            ],
        )
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("SECRET_NOTE_Z141", blob)
        self.assertNotIn("0811111111", blob)

    def test_assets_z141(self) -> None:
        self.assertIn("mobile-operations.css?v=z14", self.html)
        self.assertIn("mobile-operations.js?v=z14", self.html)

    def test_main_ux_preserved(self) -> None:
        chunk = self.html.split("function propQuickActionsHtml")[1].split(
            "function openPropertyPagePostFromCard"
        )[0]
        self.assertIn("ลิงก์ต้นโพส", chunk)
        self.assertIn("ลิงก์โพสเพจ", chunk)
        self.assertIn('class="prop-qa-btn edit"', chunk)
        self.assertNotIn("data-prop-queue", chunk)
        self.assertIn("openPropertyPagePostFromCard", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
