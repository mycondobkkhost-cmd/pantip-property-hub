#!/usr/bin/env python3
"""Phase Z14.3 — operational Follow-up date priority + Main Follow-up restoration."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))
TODAY = date(2026, 9, 6)
HTML = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
CSS = (ROOT / "hub" / "mobile-operations.css").read_text(encoding="utf-8")
MOBILE_JS = (ROOT / "hub" / "mobile-operations.js").read_text(encoding="utf-8")
SERVER = (ROOT / "scripts" / "hub_server.py").read_text(encoding="utf-8")


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
        "source_url": "https://example.com/src",
        "post_pages_url": "https://example.com/page",
    }
    base.update(kwargs)
    return base


def _with_state(state=None):
    tmp = Path(tempfile.mkdtemp(prefix="z143_"))
    st = state if state is not None else {"items": {}}
    (tmp / "upcoming_followup_state.json").write_text(json.dumps(st), encoding="utf-8")
    return tmp


class PhaseZ143DateMatrix(unittest.TestCase):
    def test_A_derived_post_followup(self) -> None:
        from src.hub.upcoming_availability import get_property_followup, build_upcoming_items

        props = [_prop(id="A", code="A1", last_posted_at="2025-09-20")]
        tmp = _with_state()
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            fu = get_property_followup("A", today=TODAY, properties=props)
            data = build_upcoming_items(props, today=TODAY)
        self.assertEqual(fu["active_date"], "2026-09-20")
        self.assertEqual(fu["reason"], "POST_FIRST_YEAR")
        row = next(x for x in data["upcoming"] if x["property_id"] == "A")
        self.assertEqual(row["target_date"], "2026-09-20")
        self.assertEqual(row["evidence"], "annual_recheck")

    def test_B_manual_reschedule_wins(self) -> None:
        from src.hub.upcoming_availability import get_property_followup, build_upcoming_items

        props = [_prop(id="B", code="B1", last_posted_at="2025-09-20")]
        tmp = _with_state(
            {"items": {"B": {"suppressed": False, "recheck_after": "2026-10-15"}}}
        )
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            fu = get_property_followup("B", today=TODAY, properties=props)
            data = build_upcoming_items(props, today=TODAY)
        self.assertEqual(fu["active_date"], "2026-10-15")
        self.assertEqual(fu["reason"], "OPERATIONAL_RECHECK")
        self.assertTrue(fu["deferred"])
        # Future recheck hides from Upcoming (no revert to 20/9/26 in list)
        ids = {x["property_id"] for x in data["upcoming"] + data["overdue"]}
        self.assertNotIn("B", ids)

    def test_C_persist_reload(self) -> None:
        from src.hub.upcoming_availability import get_property_followup, set_recheck_after

        props = [_prop(id="C", code="C1", last_posted_at="2025-09-20")]
        tmp = _with_state()
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            set_recheck_after("C", "2026-10-15", by="test")
            fu1 = get_property_followup("C", today=TODAY, properties=props)
            fu2 = get_property_followup("C", today=TODAY, properties=props)
        self.assertEqual(fu1["active_date"], "2026-10-15")
        self.assertEqual(fu2["active_date"], "2026-10-15")
        st = json.loads((tmp / "upcoming_followup_state.json").read_text(encoding="utf-8"))
        self.assertEqual(st["items"]["C"]["recheck_after"], "2026-10-15")

    def test_D_ordinary_edit_does_not_touch_followup_or_posted(self) -> None:
        from src.hub.project_store import stamp_last_posted_at_on_publish_url_change

        after = _prop(
            id="D",
            last_posted_at="2025-09-20T10:00:00",
            post_pages_url="https://x/p",
            notes="ใหม่",
            rent_price="16000",
        )
        changed = stamp_last_posted_at_on_publish_url_change(
            after,
            old_pages_url="https://x/p",
            old_post_url="",
            new_pages_url="https://x/p",
            new_post_url="",
        )
        self.assertFalse(changed)
        self.assertEqual(after.get("last_posted_at"), "2025-09-20T10:00:00")

    def test_E_confirmed_vacancy(self) -> None:
        from src.hub.upcoming_availability import get_property_followup, build_upcoming_items

        props = [
            _prop(
                id="E",
                code="E1",
                last_posted_at="2025-09-20",
                owner_confirmed_available_from="2026-09-25",
            )
        ]
        tmp = _with_state()
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            fu = get_property_followup("E", today=TODAY, properties=props)
            data = build_upcoming_items(props, today=TODAY)
        self.assertEqual(fu["active_date"], "2026-09-25")
        self.assertEqual(fu["reason"], "CONFIRMED_AVAILABILITY")
        row = next(x for x in data["upcoming"] if x["property_id"] == "E")
        self.assertEqual(row["evidence"], "confirmed")
        self.assertEqual(row["target_date"], "2026-09-25")

    def test_F_check_later_does_not_overwrite_confirmed(self) -> None:
        from src.hub.upcoming_availability import get_property_followup, set_recheck_after

        props = [
            _prop(
                id="F",
                code="F1",
                last_posted_at="2025-01-01",
                owner_confirmed_available_from="2026-09-25",
            )
        ]
        tmp = _with_state()
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            set_recheck_after("F", "2026-10-20", by="test")
            fu = get_property_followup("F", today=TODAY, properties=props)
        self.assertEqual(fu["active_date"], "2026-10-20")
        self.assertEqual(fu["owner_confirmed_available_from"][:10], "2026-09-25")
        self.assertEqual(props[0]["owner_confirmed_available_from"], "2026-09-25")

    def test_G_confirm_date_separate(self) -> None:
        # confirm-date API path uses update_property field — not recheck_after
        self.assertIn("/api/upcoming-availability/confirm-date", SERVER)
        self.assertIn("owner_confirmed_available_from", SERVER)
        self.assertIn("/api/upcoming-availability/recheck-later", SERVER)

    def test_H_complete_suppress_preserves_property(self) -> None:
        from src.hub.upcoming_availability import get_property_followup, suppress_property

        props = [_prop(id="H", code="H1", last_posted_at="2025-09-20")]
        tmp = _with_state()
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            suppress_property("H", reason="ติดตามแล้ว", by="test")
            fu = get_property_followup("H", today=TODAY, properties=props)
        self.assertTrue(fu["suppressed"])
        self.assertIsNone(fu["active_date"])
        # property object untouched
        self.assertEqual(props[0]["last_posted_at"], "2025-09-20")
        self.assertEqual(props[0]["id"], "H")

    def test_operational_due_face_date(self) -> None:
        """When recheck_after is due, Upcoming face uses it (not anniversary)."""
        from src.hub.upcoming_availability import build_upcoming_items

        props = [_prop(id="O", code="O1", last_posted_at="2025-09-20")]
        tmp = _with_state(
            {"items": {"O": {"suppressed": False, "recheck_after": "2026-09-01"}}}
        )
        with mock.patch.dict(os.environ, {"PANTIP_E2E_DATA_ROOT": str(tmp)}):
            data = build_upcoming_items(props, today=TODAY)
        row = next(x for x in data["overdue"] if x["property_id"] == "O")
        self.assertEqual(row["target_date"], "2026-09-01")
        self.assertEqual(row["evidence"], "operational_recheck")
        self.assertIn("ติดตามวันที่", row["target_phrase"])


class PhaseZ143MainRestoration(unittest.TestCase):
    def test_I_mobile_followup_nav(self) -> None:
        self.assertIn('data-view="followup"', HTML)
        self.assertIn("mobile-followup-badge", HTML)
        nav = HTML[HTML.find('id="mobile-nav"') : HTML.find('id="mobile-nav"') + 2000]
        self.assertIn('data-view="followup"', nav)
        self.assertIn("ฟอโล่ว", nav)
        self.assertNotIn('data-view="more"', nav)

    def test_J_property_id_follow_action(self) -> None:
        # Z14.4: per-card follow removed; property Follow-up Center uses property_id APIs.
        self.assertIn("openPropFollowSheet", HTML)
        self.assertIn("/api/upcoming-availability/followup", HTML)
        self.assertIn("/api/upcoming-availability/followup", SERVER)
        self.assertNotIn('data-prop-follow="', HTML[HTML.find("function propQuickActionsHtml"): HTML.find("function propQuickActionsHtml")+700])

    def test_K_duplicate_code_uses_id(self) -> None:
        self.assertIn("data-prop-edit=\"' + esc(p.id)", HTML)
        self.assertIn("data-upcoming-pid", HTML)

    def test_L_M_N_O_links_edit_card(self) -> None:
        self.assertIn("ลิงก์ต้นโพส", HTML)
        self.assertIn("ลิงก์โพสเพจ", HTML)
        self.assertIn('data-prop-edit="', HTML)
        self.assertIn("openPropertyPagePostFromCard", HTML)
        self.assertIn("never Edit", HTML)

    def test_P_follow_stop_propagation(self) -> None:
        self.assertIn('closest("[data-prop-follow]")', HTML)
        idx_f = HTML.find('closest("[data-prop-follow]")')
        idx_body = HTML.find("openPropertyPagePostFromCard(row.getAttribute")
        self.assertGreater(idx_f, 0)
        self.assertGreater(idx_body, idx_f)

    def test_Q_R_notes(self) -> None:
        self.assertIn("<strong>หมายเหตุ:</strong>", HTML)
        self.assertIn("prop-sheet-notes", HTML)

    def test_more_menu_topbar(self) -> None:
        self.assertIn('id="mobile-more-open"', HTML)
        self.assertIn("mobile-more-open", MOBILE_JS)
        self.assertIn("fu-next-followup", HTML)
        self.assertIn("next_followup_at:", HTML)

    def test_crm_explicit_date_wins_in_store(self) -> None:
        from src.hub import customer_store as cs

        tmp = Path(tempfile.mkdtemp(prefix="z143_crm_"))
        cases_path = tmp / "customer_cases.json"
        cases_path.write_text("[]", encoding="utf-8")
        with mock.patch.object(cs, "CASES_PATH", cases_path):
            item = cs.add_case(
                chat_name="T",
                channel="LINE OA",
                followup_in_days=3,
            )
            cid = item["id"]
            updated = cs.update_case(
                cid,
                followup_in_days=7,
                next_followup_at="2026-10-15",
            )
            self.assertEqual(str(updated["next_followup_at"])[:10], "2026-10-15")


class PhaseZ143PrivacyPerf(unittest.TestCase):
    def test_no_per_card_followup_fetch_in_render(self) -> None:
        start = HTML.find("function propQuickActionsHtml")
        chunk = HTML[start : start + 800]
        self.assertNotIn("/api/upcoming-availability/followup", chunk)
        # Z14.4: no per-card Follow-up button
        self.assertNotIn("data-prop-follow", chunk)

    def test_co_agent_no_recheck_in_catalog_builder(self) -> None:
        co = (ROOT / "src" / "hub" / "co_catalog.py").read_text(encoding="utf-8")
        self.assertNotIn("recheck_after", co)
        self.assertNotIn("upcoming_followup_state", co)


if __name__ == "__main__":
    unittest.main()
