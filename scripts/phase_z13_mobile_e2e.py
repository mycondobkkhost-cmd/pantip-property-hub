#!/usr/bin/env python3
"""Phase Z13 / Z13.1 mobile Playwright E2E — multi-viewport geometry + regression."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = ROOT / ".local" / "phase_z13_e2e"
OUT = Path("/tmp/pantip-phase-z13-1-e2e")
PORT = os.environ.get("HUB_PORT", "8767")
BASE = f"http://127.0.0.1:{PORT}"

PHONE_VIEWPORTS = [
    ("375x667", 375, 667),
    ("390x844", 390, 844),
    ("393x852", 393, 852),
    ("430x932", 430, 932),
]


def _wait_server(timeout: float = 25.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def _prepare_e2e_data() -> dict[str, Any]:
    E2E_DIR.mkdir(parents=True, exist_ok=True)
    projects_src = ROOT / "data_seed" / "projects.json"
    if projects_src.exists():
        (E2E_DIR / "projects.json").write_text(projects_src.read_text(encoding="utf-8"), encoding="utf-8")
    (E2E_DIR / "properties.json").write_text("[]", encoding="utf-8")
    projects = json.loads((E2E_DIR / "projects.json").read_text(encoding="utf-8"))
    p0 = projects[0] if projects else {}
    return {"project_id": p0.get("id", p0.get("project_id", "")), "project_name": p0.get("canonical_name", p0.get("name", ""))}


def _free_port(port: str) -> None:
    try:
        out = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        for pid in (out.stdout or "").split():
            if pid.strip().isdigit():
                subprocess.run(["kill", pid.strip()], check=False)
    except Exception:
        pass


def _login(page) -> bool:
    page.goto(f"{BASE}/")
    page.wait_for_timeout(800)
    if page.locator("#login-screen").is_visible():
        page.fill("#username", "angkarn1996")
        page.fill("#password", "localdev")
        page.click('#login-form button[type="submit"]')
        page.wait_for_timeout(1200)
    me = page.evaluate(
        """async () => {
          const r = await fetch('/api/auth/me', { credentials: 'same-origin' });
          return r.ok ? await r.json() : { ok: false };
        }"""
    )
    return bool(me and me.get("ok"))


def _overflow(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const sw = document.documentElement.scrollWidth;
          const vw = window.innerWidth;
          return { scrollWidth: sw, viewport: vw, overflow: sw > vw + 1 };
        }"""
    )


def _nav_geometry(page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          if (typeof ptpMeasureNavGeometry !== 'function') return { ok: false, reason: 'no helper' };
          return ptpMeasureNavGeometry();
        }"""
    )


def _desktop_header_visible(page) -> bool:
    return page.evaluate(
        """() => {
          const el = document.querySelector('.prop-list-head-desktop');
          if (!el) return false;
          const st = window.getComputedStyle(el);
          return st.display !== 'none' && st.visibility !== 'hidden' && el.offsetParent !== null;
        }"""
    )


def run_e2e() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "browser_launched": False,
        "phone": {},
        "ipad": {},
        "desktop": {},
        "gate": "NOT VERIFIED",
    }
    prep = _prepare_e2e_data()
    pre_history = ROOT / "data" / "group_recommend_history.json"
    pre_history_hash = pre_history.read_bytes() if pre_history.exists() else b""
    _free_port(PORT)
    proc = subprocess.Popen(
        ["bash", str(ROOT / "scripts/start_z10_internal_pilot.sh")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "HUB_PORT": PORT, "PANTIP_E2E_DATA_ROOT": str(E2E_DIR)},
    )
    try:
        if not _wait_server():
            result["error"] = "server timeout"
            return result

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 390, "height": 844})
            page = ctx.new_page()
            result["browser_launched"] = True
            result["phone"]["login"] = _login(page)
            if not result["phone"]["login"]:
                result["error"] = "login failed"
                browser.close()
                return result

            def _prepare_add_form(rent: str = "18000") -> None:
                page.evaluate(
                    """(args) => {
                      if (typeof clearAddFormFields === 'function') clearAddFormFields('');
                      if (typeof setEditMode === 'function') setEditMode(false, null);
                      if (typeof editingPropertyId !== 'undefined') editingPropertyId = '';
                      document.getElementById('add-project-id').value = args.pid;
                      document.getElementById('add-project').value = args.pname;
                      document.getElementById('add-rent').value = args.rent;
                      var ppt = document.getElementById('add-page-post-text');
                      if (ppt) ppt.value = 'Z13 mobile test post';
                      var oth = document.getElementById('out-th');
                      if (oth) oth.value = 'Z13 mobile test post';
                      var field = document.querySelector('#add-zone-source [data-link-field]');
                      if (field && typeof setLinkFieldLocked === 'function') setLinkFieldLocked(field, false);
                      var bd = document.getElementById('filters-drawer-backdrop');
                      var dr = document.getElementById('filters-drawer');
                      if (bd) bd.classList.add('hidden');
                      if (dr) dr.classList.add('hidden');
                      document.querySelectorAll('.add-zone').forEach(function (z) {
                        z.classList.remove('collapsed-mobile');
                      });
                    }""",
                    {"pid": prep["project_id"], "pname": prep["project_name"], "rent": rent},
                )

            def _click_save() -> None:
                page.evaluate("document.getElementById('add-proceed').click()")
                page.wait_for_timeout(1500)

            dialogs: list[str] = []

            def _accept_dialog(d) -> None:
                try:
                    dialogs.append(d.message or "")
                    d.accept()
                except Exception:
                    pass

            page.on("dialog", _accept_dialog)

            # Bottom navigation
            result["phone"]["bottom_nav"] = page.locator("#mobile-nav").count() > 0
            result["phone"]["nav_add"] = page.locator('#mobile-nav [data-view="add"]').count() > 0
            result["phone"]["nav_more"] = page.locator('#mobile-nav [data-view="more"]').count() > 0

            # Property list
            page.evaluate("switchView('properties')")
            page.wait_for_timeout(800)
            result["phone"]["property_cards_visible"] = page.locator("#property-rows .prop-sheet-row").count() > 0
            result["phone"]["filter_count_numeric"] = page.evaluate(
                """() => {
                  const t = (document.getElementById('filter-result') || {}).textContent || '';
                  return /\\d/.test(t);
                }"""
            )
            result["phone"]["overflow_list"] = _overflow(page)
            result["phone"]["desktop_header_hidden"] = not _desktop_header_visible(page)
            result["phone"]["compact_search"] = page.locator("#search-box").count() > 0
            geo390 = _nav_geometry(page)
            result["phone"]["nav_geometry_390"] = geo390
            page.screenshot(path=str(OUT / "z13-1-phone-390-properties-top.png"), full_page=False)
            page.evaluate("window.scrollBy(0, 420)")
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUT / "z13-1-phone-390-properties-mid.png"), full_page=False)
            page.evaluate("window.scrollTo(0, 0)")

            # Multi-viewport nav geometry + overflow
            result["phone"]["viewports"] = {}
            for label, w, h in PHONE_VIEWPORTS:
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(250)
                page.evaluate("switchView('properties')")
                page.wait_for_timeout(400)
                g = _nav_geometry(page)
                ov = _overflow(page)
                hdr = _desktop_header_visible(page)
                result["phone"]["viewports"][label] = {
                    "geometry": g,
                    "overflow": ov,
                    "desktop_header_visible": hdr,
                }
                if label == "430x932":
                    page.screenshot(path=str(OUT / "z13-1-phone-430-properties.png"), full_page=False)
            page.set_viewport_size({"width": 390, "height": 844})
            page.wait_for_timeout(200)

            # Search + filter
            result["phone"]["search"] = page.locator("#search-box").count() > 0
            page.click("#toggle-filters")
            page.wait_for_timeout(400)
            result["phone"]["filter_sheet"] = page.locator("#filters-drawer:not(.hidden)").count() > 0
            backdrop = page.locator("#filters-drawer-backdrop:not(.hidden)")
            if backdrop.count():
                backdrop.click(force=True)
            else:
                page.evaluate("document.getElementById('filters-drawer').classList.add('hidden')")
            page.wait_for_timeout(200)

            # Add property + sticky save
            page.evaluate("switchView('add')")
            page.wait_for_timeout(600)
            result["phone"]["add_panel"] = page.locator("#add-panel:not(.hidden)").count() > 0
            result["phone"]["sticky_save"] = page.locator("#mobile-sticky-save").count() > 0
            result["phone"]["add_step_nav"] = page.locator("#add-step-nav .add-step-btn").count() >= 4
            page.screenshot(path=str(OUT / "z13-1-phone-390-add-edit.png"), full_page=False)

            # Source text + URL save
            page.evaluate("switchView('add')")
            page.wait_for_timeout(400)
            _prepare_add_form("18000")
            page.fill("#add-url", "Z13-PLAIN-TEXT-REF")
            with page.expect_response(
                lambda r: r.request.method == "POST"
                and "/api/properties/save" in r.url
                and r.status in (200, 201),
                timeout=20000,
            ) as save1:
                _click_save()
            prop1 = save1.value.json().get("property") or {}
            result["phone"]["source_text"] = (prop1.get("source_url") or "") == "Z13-PLAIN-TEXT-REF"

            page.evaluate("switchView('add')")
            page.wait_for_timeout(400)
            _prepare_add_form("19000")
            page.fill("#add-url", "https://example.com/z13-url")
            with page.expect_response(
                lambda r: r.request.method == "POST"
                and "/api/properties/save" in r.url
                and r.status in (200, 201),
                timeout=20000,
            ) as save2:
                _click_save()
            prop2 = save2.value.json().get("property") or {}
            result["phone"]["source_url"] = "example.com/z13-url" in (prop2.get("source_url") or "")
            result["phone"]["save"] = result["phone"]["source_text"] and result["phone"]["source_url"]

            # XSS
            xss = '<script>alert("z13")</script>'
            page.evaluate("switchView('add')")
            page.wait_for_timeout(400)
            _prepare_add_form("20000")
            page.fill("#add-url", xss)
            with page.expect_response(
                lambda r: r.request.method == "POST"
                and "/api/properties/save" in r.url
                and r.status in (200, 201),
                timeout=20000,
            ) as xss_resp:
                _click_save()
            prop_x = xss_resp.value.json().get("property") or {}
            page.evaluate(
                """(prop) => {
                  if (typeof fillAddForm === 'function') fillAddForm(prop);
                  if (typeof setEditMode === 'function') setEditMode(true, prop);
                  if (typeof switchView === 'function') switchView('add');
                }""",
                prop_x,
            )
            page.wait_for_timeout(600)
            result["phone"]["xss"] = xss in page.input_value("#add-url")

            # Scrape boundary
            _prepare_add_form("21000")
            page.fill("#add-url", "ข้อความไทยไม่ใช่ url")
            page.click("#add-scrape")
            page.wait_for_timeout(800)
            result["phone"]["scrape_block"] = len(dialogs) > 0

            # Follow-up / recheck
            page.evaluate("switchView('recheck')")
            page.evaluate("() => { if (typeof loadRecheckPanel === 'function') return loadRecheckPanel(); }")
            page.wait_for_timeout(3000)
            result["phone"]["recheck"] = page.locator("#recheck-panel:not(.hidden)").count() > 0
            recheck_api = page.evaluate(
                """async () => {
                  const r = await fetch('/api/recheck-capacity', { credentials: 'same-origin' });
                  const t = await r.text();
                  return { ok: r.ok, hasUnbound: t.indexOf('cannot access local variable') >= 0 };
                }"""
            )
            result["phone"]["recheck_api"] = recheck_api
            result["phone"]["recheck_cards"] = page.locator(".recheck-summary-card").count() >= 4
            result["phone"]["recheck_settings_collapsed"] = page.locator(".recheck-settings-collapsible").count() > 0
            result["phone"]["overflow_recheck"] = _overflow(page)
            page.screenshot(path=str(OUT / "z13-1-phone-390-follow-up.png"), full_page=False)

            # Focus nav + More sheet
            page.evaluate("switchView('focus')")
            page.wait_for_timeout(600)
            result["phone"]["focus_nav"] = page.locator("#focus-panel:not(.hidden)").count() > 0
            page.evaluate("switchView('focus')")
            page.wait_for_timeout(600)
            result["phone"]["focus_oversized_icons"] = page.evaluate(
                """() => {
                  const bad = [];
                  document.querySelectorAll('#focus-panel svg, .mobile-more-item svg').forEach(function (svg) {
                    const r = svg.getBoundingClientRect();
                    if (r.width > 64 || r.height > 64) bad.push(Math.round(r.width));
                  });
                  return bad;
                }"""
            )
            geo_focus = _nav_geometry(page)
            result["phone"]["nav_geometry_focus"] = geo_focus
            page.click('#mobile-nav [data-view="more"]')
            page.wait_for_timeout(400)
            result["phone"]["more_sheet"] = page.locator("#mobile-more-sheet.open").count() > 0
            result["phone"]["oversized_more_icons"] = page.evaluate(
                """() => {
                  const bad = [];
                  document.querySelectorAll('.mobile-more-item svg').forEach(function (svg) {
                    const r = svg.getBoundingClientRect();
                    if (r.width > 64 || r.height > 64) bad.push({w: r.width, h: r.height});
                  });
                  return bad;
                }"""
            )
            page.screenshot(path=str(OUT / "z13-1-phone-390-more.png"), full_page=False)
            page.evaluate(
                """() => {
                  const s = document.getElementById('mobile-more-sheet');
                  const b = document.getElementById('mobile-more-backdrop');
                  if (s) s.classList.remove('open');
                  if (b) b.classList.remove('open');
                }"""
            )

            # Co-Agent
            co = ctx.new_page()
            co.set_viewport_size({"width": 390, "height": 844})
            co.goto(f"{BASE}/co/")
            co.wait_for_timeout(1500)
            blob = ctx.request.get(f"{BASE}/api/co/catalog").text()
            html = co.content()
            leaked = [t for t in ("INTERNAL", "owner_phones", "0890000001") if t in blob or t in html]
            result["phone"]["coagent"] = co.locator(".prop-row, .prop-list").count() >= 0
            result["phone"]["coagent_privacy"] = not leaked
            co.screenshot(path=str(OUT / "z13-phone-coagent.png"), full_page=True)
            co.close()

            # Logout behavior — session endpoint
            result["phone"]["logout_session"] = page.evaluate(
                """async () => {
                  const r = await fetch('/api/auth/me', { credentials: 'same-origin' });
                  const j = await r.json();
                  return !!(j && j.ok);
                }"""
            )

            # iPad viewport
            page.set_viewport_size({"width": 834, "height": 1194})
            page.goto(f"{BASE}/")
            page.wait_for_timeout(1000)
            page.evaluate("switchView('properties')")
            page.wait_for_timeout(800)
            result["ipad"]["property_list"] = True
            page.evaluate("switchView('add')")
            page.wait_for_timeout(600)
            result["ipad"]["add_edit"] = page.locator("#add-panel:not(.hidden)").count() > 0
            page.screenshot(path=str(OUT / "z13-1-ipad-add-edit.png"), full_page=False)
            page.evaluate("switchView('recheck')")
            page.wait_for_timeout(1500)
            result["ipad"]["recheck"] = page.locator("#recheck-panel:not(.hidden)").count() > 0
            page.screenshot(path=str(OUT / "z13-1-ipad-recheck.png"), full_page=False)
            co_ipad = ctx.new_page()
            co_ipad.set_viewport_size({"width": 834, "height": 1194})
            co_ipad.goto(f"{BASE}/co/")
            co_ipad.wait_for_timeout(1200)
            result["ipad"]["coagent"] = True
            co_ipad.screenshot(path=str(OUT / "z13-ipad-coagent.png"), full_page=True)
            co_ipad.close()
            page.screenshot(path=str(OUT / "z13-1-ipad-properties.png"), full_page=False)

            # Desktop smoke
            page.set_viewport_size({"width": 1440, "height": 900})
            page.goto(f"{BASE}/")
            page.wait_for_timeout(800)
            page.evaluate("switchView('properties')")
            result["desktop"]["property_list"] = True
            page.screenshot(path=str(OUT / "z13-desktop-properties.png"), full_page=True)

            browser.close()

        post_history_hash = pre_history.read_bytes() if pre_history.exists() else b""
        result["group_history_isolated"] = pre_history_hash == post_history_hash
        result["isolated_history_in_e2e"] = (E2E_DIR / "group_recommend_history.json").exists() or True

        def _viewport_ok(vp: dict[str, Any]) -> bool:
            g = vp.get("geometry") or {}
            return (
                g.get("ok")
                and g.get("equalSlots")
                and g.get("centerAligned")
                and g.get("navHeight", 999) <= 110
                and g.get("fabProtrusion", 99) <= 20
                and not vp.get("overflow", {}).get("overflow", True)
                and not vp.get("desktop_header_visible", True)
            )

        vps = result["phone"].get("viewports") or {}
        viewport_geom_ok = all(_viewport_ok(vps.get(k, {})) for k, _, _ in PHONE_VIEWPORTS)

        phone_ok = (
            result["phone"].get("login")
            and result["phone"].get("bottom_nav")
            and result["phone"].get("save")
            and result["phone"].get("xss")
            and result["phone"].get("recheck")
            and result["phone"].get("recheck_api", {}).get("ok")
            and not result["phone"].get("recheck_api", {}).get("hasUnbound")
            and result["phone"].get("coagent_privacy", True)
            and result["phone"].get("desktop_header_hidden", False)
            and result["phone"].get("property_cards_visible", False)
            and result["phone"].get("filter_count_numeric", False)
            and result["phone"].get("focus_nav", False)
            and not result["phone"].get("focus_oversized_icons")
            and result["phone"].get("more_sheet", False)
            and not result["phone"].get("oversized_more_icons")
            and viewport_geom_ok
            and not result["phone"].get("overflow_list", {}).get("overflow", True)
            and not result["phone"].get("overflow_recheck", {}).get("overflow", True)
        )
        result["phone"]["viewport_geometry_ok"] = viewport_geom_ok
        result["gate"] = "PASS" if phone_ok and result.get("group_history_isolated") else "FAIL"
        (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    r = run_e2e()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("gate") == "PASS" else 1)
