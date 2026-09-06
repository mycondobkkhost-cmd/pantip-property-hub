#!/usr/bin/env python3
"""Phase Z14 — main property UX correction + upcoming rental availability."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class PhaseZ14MainUxAndUpcoming(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
        cls.css = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")

    def _actions(self) -> str:
        return self.html.split("function propQuickActionsHtml")[1].split(
            "function openPropertyPagePostFromCard"
        )[0]

    # --- JOB 1 ---
    def test_01_edit_compact_not_primary(self) -> None:
        chunk = self._actions()
        self.assertIn('class="prop-qa-btn edit"', chunk)
        self.assertNotIn("edit primary", chunk)
        self.assertIn("flex: 0 0 auto", self.css)

    def test_02_source_page_visible(self) -> None:
        chunk = self._actions()
        self.assertIn('ลิงก์ต้นโพส', chunk)
        self.assertIn('ลิงก์โพสเพจ', chunk)
        self.assertIn("p.source_url", chunk)
        self.assertIn("p.post_pages_url", chunk)
        self.assertNotIn("prop-more-menu", chunk)
        self.assertNotIn("data-prop-more", chunk)

    def test_03_missing_link_disabled_not_hidden(self) -> None:
        link_fn = self.html.split("function propQuickLinkBtn")[1].split(
            "function propQuickActionsHtml"
        )[0]
        self.assertIn("is-disabled", link_fn)
        self.assertIn("disabled", link_fn)

    def test_04_card_body_opens_page_post_not_edit(self) -> None:
        self.assertIn("function openPropertyPagePostFromCard", self.html)
        self.assertIn("post_pages_url", self.html.split("function openPropertyPagePostFromCard")[1][:800])
        # property-rows click end
        chunk = self.html.split('document.getElementById("property-rows").addEventListener("click"')[1].split(
            'var focusRowsEl'
        )[0]
        self.assertIn("openPropertyPagePostFromCard", chunk)
        self.assertNotIn("openPropertyEdit(row.getAttribute", chunk)

    def test_05_no_per_card_waiting(self) -> None:
        chunk = self._actions()
        self.assertNotIn("data-prop-queue", chunk)
        self.assertNotIn(">รอโพสต์</button>", chunk)

    def test_06_bottom_nav_queue_preserved(self) -> None:
        nav = self.html.split('id="mobile-nav"')[1].split("</nav>")[0]
        self.assertIn('data-view="queue"', nav)
        self.assertIn("รอโพสต์", nav)

    def test_07_compact_timestamp_no_fake_time(self) -> None:
        self.assertIn("formatListedDateShort(p.last_listed_at)", self.html)
        self.assertIn("function formatCompactDateTime", self.html)

    def test_08_assets_z14(self) -> None:
        self.assertIn("mobile-operations.css?v=z14", self.html)
        self.assertIn("mobile-operations.js?v=z14", self.html)

    # --- JOB 2 rules ---
    def test_09_upcoming_module_and_api(self) -> None:
        self.assertIn('id="upcoming-strip"', self.html)
        self.assertIn('id="upcoming-panel"', self.html)
        self.assertIn("/api/upcoming-availability", self.html)
        server = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")
        self.assertIn('path == "/api/upcoming-availability"', server)
        self.assertIn("/api/upcoming-availability/suppress", server)
        self.assertIn("/api/upcoming-availability/recheck-later", server)
        self.assertIn("/api/upcoming-availability/confirm-date", server)

    def test_10_confirmed_field_in_editor(self) -> None:
        self.assertIn('id="add-owner-confirmed-available"', self.html)
        self.assertIn("เจ้าของยืนยันว่าจะว่างวันที่", self.html)
        self.assertIn("owner_confirmed_available_from", self.html)

    def test_11_sale_only_excluded_rental_rules(self) -> None:
        from src.hub.upcoming_availability import build_upcoming_items

        today = date(2026, 9, 6)
        props = [
            {
                "id": "sale1",
                "code": "S1",
                "sale_price": "5000000",
                "rent_price": "",
                "last_posted_at": "2025-09-20",
                "owner_confirmed_available_from": (today + timedelta(days=14)).isoformat(),
                "project_name": "Sale Only",
            },
            {
                "id": "rent-far",
                "code": "R1",
                "rent_price": "20000",
                "last_posted_at": "2026-01-01",
                "owner_confirmed_available_from": (today + timedelta(days=45)).isoformat(),
                "project_name": "Far",
            },
            {
                "id": "rent-conf",
                "code": "R2",
                "rent_price": "20000",
                "last_posted_at": "2026-01-01",
                "owner_confirmed_available_from": (today + timedelta(days=14)).isoformat(),
                "project_name": "Confirmed",
            },
            {
                "id": "rent-ann",
                "code": "R3",
                "rent_price": "18000",
                "last_posted_at": "2025-09-26",  # +1y = 2026-09-26 → 20 days
                "project_name": "Annual",
            },
            {
                "id": "rent-over",
                "code": "R4",
                "rent_price": "15000",
                "last_posted_at": "2025-09-01",  # +1y = 2026-09-01 → overdue 5 days
                "project_name": "Overdue Annual",
            },
            {
                "id": "both",
                "code": "R5",
                "rent_price": "22000",
                "last_posted_at": "2025-09-20",
                "owner_confirmed_available_from": (today + timedelta(days=10)).isoformat(),
                "project_name": "Both",
            },
            {
                "id": "legacy-wang",
                "code": "R6",
                "rent_price": "10000",
                "last_listed_at": "01/01/2026",
                "last_posted_at": "",
                "available_raw": "20/09/2026",
                "วันที่ว่าง": "20/09/2026",
                "project_name": "Legacy",
            },
        ]
        tmp = Path(tempfile.mkdtemp(prefix="z14_"))
        (tmp / "upcoming_followup_state.json").write_text(
            json.dumps({"items": {}}), encoding="utf-8"
        )
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            data = build_upcoming_items(props, today=today)
        ids = {x["property_id"] for x in data["upcoming"] + data["overdue"]}
        self.assertNotIn("sale1", ids)
        self.assertNotIn("rent-far", ids)
        self.assertNotIn("legacy-wang", ids)
        self.assertIn("rent-conf", ids)
        self.assertIn("rent-ann", ids)
        self.assertIn("rent-over", ids)
        self.assertIn("both", ids)
        both = next(x for x in data["upcoming"] if x["property_id"] == "both")
        self.assertEqual(both["evidence"], "confirmed")
        self.assertEqual(both["label"], "ยืนยันวันว่าง")
        ann = next(x for x in data["upcoming"] if x["property_id"] == "rent-ann")
        self.assertEqual(ann["evidence"], "annual_recheck")
        self.assertEqual(ann["label"], "ถึงรอบเช็ก")
        conf = next(x for x in data["upcoming"] if x["property_id"] == "rent-conf")
        self.assertEqual(conf["days_until"], 14)
        self.assertEqual(conf["countdown"], "เหลืออีก 14 วัน")
        over = next(x for x in data["overdue"] if x["property_id"] == "rent-over")
        self.assertEqual(over["days_until"], -5)
        self.assertEqual(over["countdown"], "เลยรอบเช็กมา 5 วัน")
        # no duplicates
        self.assertEqual(len(ids), len(data["upcoming"]) + len(data["overdue"]))

    def test_12_suppress_and_recheck_later(self) -> None:
        from src.hub.upcoming_availability import (
            build_upcoming_items,
            set_recheck_after,
            suppress_property,
        )

        today = date(2026, 9, 6)
        props = [
            {
                "id": "p1",
                "code": "P1",
                "rent_price": "10000",
                "owner_confirmed_available_from": (today + timedelta(days=5)).isoformat(),
                "last_listed_at": "01/01/2026",
                "project_name": "X",
                "notes": "keep me",
            }
        ]
        tmp = Path(tempfile.mkdtemp(prefix="z14s_"))
        (tmp / "upcoming_followup_state.json").write_text(
            json.dumps({"items": {}}), encoding="utf-8"
        )
        (tmp / "properties.json").write_text(json.dumps(props), encoding="utf-8")
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            before = build_upcoming_items(props, today=today)
            self.assertEqual(before["counts"]["total"], 1)
            suppress_property("p1", reason="ติดต่อเจ้าของไม่ได้")
            after = build_upcoming_items(props, today=today)
            self.assertEqual(after["counts"]["total"], 0)
            # property file untouched
            self.assertEqual(
                json.loads((tmp / "properties.json").read_text(encoding="utf-8"))[0]["notes"],
                "keep me",
            )
            # recheck-later does not write confirmed date
            set_recheck_after("p2", (today + timedelta(days=40)).isoformat())
            st = json.loads((tmp / "upcoming_followup_state.json").read_text(encoding="utf-8"))
            self.assertTrue(st["items"]["p2"].get("recheck_after"))
            self.assertNotIn("owner_confirmed_available_from", st["items"]["p2"])

    def test_13_timezone_countdown_today(self) -> None:
        from src.hub.upcoming_availability import countdown_label, days_until

        today = date(2026, 9, 6)
        self.assertEqual(days_until(today, today=today), 0)
        self.assertEqual(countdown_label(0), "วันนี้")
        self.assertEqual(countdown_label(14), "เหลืออีก 14 วัน")
        self.assertEqual(countdown_label(1), "เหลืออีก 1 วัน")
        self.assertEqual(countdown_label(-5), "เลยรอบเช็กมา 5 วัน")
        self.assertEqual(countdown_label(-5, evidence="confirmed"), "เลยวันว่างมา 5 วัน")

    def test_14_co_agent_privacy(self) -> None:
        from src.hub.public_projection import build_public_catalog_payload

        payload = build_public_catalog_payload(
            [{"id": "p1"}],
            [
                {
                    "id": "x",
                    "code": "C1",
                    "notes": "secret",
                    "owner_confirmed_available_from": "2026-10-20",
                    "source_url": "https://facebook.com/x",
                    "owner_phones": ["0812345678"],
                    "rent_price": "10000",
                }
            ],
        )
        blob = str(payload)
        self.assertNotIn("secret", blob)
        self.assertNotIn("0812345678", blob)
        self.assertNotIn("2026-10-20", blob)

    def test_15_waiting_ux_preserved(self) -> None:
        chunk = self.html.split("function renderQueue()")[1].split("async function loadQueue")[0]
        self.assertIn('data-qact="edit"', chunk)
        self.assertIn(">เพิ่มโพส</button>", chunk)
        self.assertIn(">เสร็จ</button>", chunk)
        self.assertIn(">ลบ</button>", chunk)
        self.assertIn("openQueueFormForEdit", self.html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
