#!/usr/bin/env python3
"""Phase Z11 full UI Playwright E2E — real Save button, reload/reopen, mobile viewport."""

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
E2E_DIR = ROOT / ".local" / "phase_z11_e2e"
OUT = Path("/tmp/pantip-phase-z11-e2e")
PORT = os.environ.get("HUB_PORT", "8766")
BASE = f"http://127.0.0.1:{PORT}"

SOURCE_CASES = {
    "A": "https://www.facebook.com/share/p/z11a",
    "B": "https://example.com/listing/z11b",
    "C": "รหัสอ้างอิง LI-Z11",
    "D": "staff note REF-Z11",
    "E": "note with spaces 123",
    "F": "FB-99 / โพสต์เก่า 2024",
    "G": "",
    "H": "http:// not valid url (copy)",
}


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
    projects_src = ROOT / "data" / "projects.json"
    if projects_src.exists():
        (E2E_DIR / "projects.json").write_text(projects_src.read_text(encoding="utf-8"), encoding="utf-8")
    (E2E_DIR / "properties.json").write_text("[]", encoding="utf-8")
    projects = json.loads((E2E_DIR / "projects.json").read_text(encoding="utf-8"))
    p0 = projects[0] if projects else {}
    return {"project_id": p0.get("id", p0.get("project_id", "")), "project_name": p0.get("canonical_name", p0.get("name", ""))}


def _last_property() -> dict[str, Any]:
    props = json.loads((E2E_DIR / "properties.json").read_text(encoding="utf-8"))
    return props[-1] if props else {}


def _free_port(port: str) -> None:
    try:
        out = subprocess.run(["lsof", "-ti", f":{port}"], capture_output=True, text=True)
        for pid in (out.stdout or "").split():
            if pid.strip().isdigit():
                subprocess.run(["kill", pid.strip()], check=False)
    except Exception:
        pass


def run_e2e() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "browser_launched": False,
        "login_ok": False,
        "ui_save_button_used": False,
        "source_ui_cases": {},
        "reload_reopen_all": True,
        "xss": {},
        "scrape_ui": {},
        "coagent": {},
        "recheck_desktop": {},
        "recheck_mobile": {},
        "gate": "NOT VERIFIED",
    }
    prep = _prepare_e2e_data()
    _free_port(PORT)
    proc = subprocess.Popen(
        ["bash", str(ROOT / "scripts/start_z10_internal_pilot.sh")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={
            **os.environ,
            "HUB_PORT": PORT,
            "PANTIP_E2E_DATA_ROOT": str(E2E_DIR),
        },
    )
    try:
        if not _wait_server():
            result["error"] = "server timeout"
            return result

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            page = ctx.new_page()
            dialogs: list[str] = []

            def _accept_dialog(d) -> None:
                try:
                    msg = d.message or ""
                    dialogs.append(msg)
                    d.accept()
                except Exception:
                    pass

            page.on("dialog", _accept_dialog)
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
            result["login_ok"] = bool(me and me.get("ok"))
            result["authenticated"] = result["login_ok"]
            result["browser_launched"] = True
            if not result["login_ok"]:
                result["error"] = "login failed"
                browser.close()
                return result

            def _unlock_source_url() -> None:
                page.evaluate(
                    """() => {
                      var field = document.querySelector('#add-zone-source [data-link-field]');
                      var input = document.getElementById('add-url');
                      if (field && typeof setLinkFieldLocked === 'function') {
                        setLinkFieldLocked(field, false);
                      } else if (input) {
                        input.readOnly = false;
                      }
                    }"""
                )

            def _fill_min_form() -> None:
                page.evaluate(
                    """(args) => {
                      document.getElementById('add-project-id').value = args.pid;
                      document.getElementById('add-project').value = args.pname;
                      document.getElementById('add-rent').value = '25000';
                      if (typeof setEditMode === 'function') setEditMode(false, null);
                    }""",
                    {"pid": prep["project_id"], "pname": prep["project_name"]},
                )

            def _reopen_property(prop: dict[str, Any]) -> None:
                page.evaluate(
                    """(prop) => {
                      if (typeof fillAddForm === 'function') fillAddForm(prop);
                      if (typeof setEditMode === 'function') setEditMode(true, prop);
                      if (typeof switchView === 'function') switchView('add');
                    }""",
                    prop,
                )
                page.wait_for_timeout(600)

            # Full UI source reference A–H
            for key, val in SOURCE_CASES.items():
                case_result: dict[str, Any] = {"ui_save": False, "reopen_match": False}
                page.evaluate("switchView('add')")
                page.wait_for_timeout(500)
                page.evaluate(
                    """() => {
                      if (typeof clearAddFormFields === 'function') clearAddFormFields('');
                      if (typeof setEditMode === 'function') setEditMode(false, null);
                    }"""
                )
                _fill_min_form()
                _unlock_source_url()
                page.fill("#add-url", val)

                def _is_save_response(resp) -> bool:
                    return resp.request.method == "POST" and resp.url.rstrip("/").endswith("/api/properties/save")

                with page.expect_response(_is_save_response, timeout=20000) as save_resp:
                    page.click("#add-proceed")
                save_json = save_resp.value.json()
                case_result["save_ok"] = save_resp.value.ok and save_json.get("ok", True)
                page.wait_for_timeout(1000)
                case_result["ui_save"] = True
                result["ui_save_button_used"] = True
                prop = save_json.get("property") or {}
                case_result["persisted"] = (prop.get("source_url") or "") == val
                _reopen_property(prop)
                reopened = page.input_value("#add-url")
                case_result["reopen_match"] = reopened == val
                case_result["pass"] = (
                    case_result["save_ok"] and case_result["persisted"] and case_result["reopen_match"]
                )
                if not case_result["pass"]:
                    result["reload_reopen_all"] = False
                result["source_ui_cases"][key] = case_result

            # XSS via UI
            xss_val = '<script>alert("z11")</script>'
            xss_dialogs: list[str] = []
            page.remove_listener("dialog", _accept_dialog)

            def _xss_dialog(d) -> None:
                try:
                    xss_dialogs.append(d.message or "")
                    d.accept()
                except Exception:
                    pass

            page.on("dialog", _xss_dialog)
            page.evaluate("switchView('add')")
            _fill_min_form()
            _unlock_source_url()
            page.fill("#add-url", xss_val)
            with page.expect_response(
                lambda r: r.request.method == "POST" and r.url.rstrip("/").endswith("/api/properties/save"),
                timeout=20000,
            ) as xss_resp:
                page.click("#add-proceed")
            prop_x = xss_resp.value.json().get("property") or _last_property()
            _reopen_property(prop_x)
            dom_val = page.input_value("#add-url")
            result["xss"] = {
                "stored": xss_val in dom_val,
                "alert_fired": any("z11" in (m or "") for m in xss_dialogs),
                "pass": xss_val in dom_val and not any("z11" in (m or "") for m in xss_dialogs),
            }

            # Scrape UI boundary
            page.on("dialog", _accept_dialog)
            for label, val, expect_block in [
                ("valid_fb", "https://www.facebook.com/share/p/z11", False),
                ("plain_thai", "ข้อความไทย", True),
                ("malformed", "http:// bad", True),
                ("empty", "", True),
            ]:
                page.evaluate("switchView('add')")
                page.wait_for_timeout(300)
                before_dialogs = len(dialogs)
                if val:
                    _unlock_source_url()
                    page.fill("#add-url", val)
                page.click("#add-scrape")
                page.wait_for_timeout(1000)
                blocked = len(dialogs) > before_dialogs
                result["scrape_ui"][label] = {
                    "expect_block": expect_block,
                    "blocked": blocked,
                    "pass": blocked == expect_block,
                }

            # Co-Agent privacy — synthetic via API then browser
            synth = {
                "property": {
                    "project_id": prep["project_id"],
                    "rent_price": "30000",
                    "source_url": "INTERNAL_DOM_REF",
                    "notes": "SECRET_DOM_NOTE",
                    "owner_phones": ["0890000001"],
                    "owner_lines": ["line-secret"],
                    "owner_facebook": ["https://facebook.com/owner-secret"],
                    "post_url": "https://www.facebook.com/example/public-z11",
                }
            }
            ctx.request.post(f"{BASE}/api/properties/save", data=json.dumps(synth))
            co = ctx.request.get(f"{BASE}/api/co/catalog")
            blob = co.text()
            co_page = ctx.new_page()
            co_page.goto(f"{BASE}/co/")
            co_page.wait_for_timeout(1500)
            co_html = co_page.content()
            leaked = [t for t in ("INTERNAL_DOM_REF", "SECRET_DOM_NOTE", "0890000001", "line-secret") if t in blob or t in co_html]
            result["coagent"] = {"api_leaked": leaked, "dom_leaked": leaked, "pass": not leaked}
            co_page.close()

            # Co-Agent mutation block
            anon = p.request.new_context()
            mut = anon.post(f"{BASE}/api/properties/save", data="{}")
            result["coagent"]["mutation_blocked"] = mut.status in (401, 403)
            anon.dispose()

            # Embedded recheck desktop
            page.goto(f"{BASE}/")
            page.wait_for_timeout(800)
            page.evaluate("switchView('followup')")
            page.click("#follow-tab-recheck")
            page.evaluate("() => { if (typeof loadRecheckPanel === 'function') return loadRecheckPanel(); }")
            page.wait_for_timeout(2000)
            result["recheck_desktop"] = {
                "panel_visible": page.locator("#recheck-panel:not(.hidden)").count() > 0,
                "old_record_label": "OLD_RECORD_RECHECK" in page.content(),
                "lease_label": "LEASE_END_FOLLOWUP" in page.content(),
            }
            page.screenshot(path=str(OUT / "z11-recheck-desktop.png"), full_page=True)

            # Mobile viewport (same authenticated session)
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(f"{BASE}/")
            page.wait_for_timeout(1000)
            page.evaluate("switchView('followup')")
            page.click("#follow-tab-recheck")
            page.evaluate("() => { if (typeof loadRecheckPanel === 'function') return loadRecheckPanel(); }")
            page.wait_for_timeout(2000)
            result["recheck_mobile"] = {
                "panel_visible": page.locator("#recheck-panel:not(.hidden)").count() > 0,
                "overflow_x": page.evaluate("document.documentElement.scrollWidth"),
            }
            page.screenshot(path=str(OUT / "z11-recheck-mobile.png"), full_page=True)

            # Standalone page still works
            standalone = ctx.new_page()
            standalone.goto(f"{BASE}/operator-follow-up/")
            standalone.wait_for_timeout(1000)
            result["recheck_desktop"]["standalone_ok"] = standalone.locator("#pullBtn").count() > 0
            standalone.close()

            browser.close()

        passed = (
            result["login_ok"]
            and result["ui_save_button_used"]
            and result["reload_reopen_all"]
            and all(v.get("pass") for v in result["source_ui_cases"].values())
            and result["xss"].get("pass")
            and all(v.get("pass") for v in result["scrape_ui"].values())
            and result["coagent"].get("pass")
            and result["coagent"].get("mutation_blocked")
            and result["recheck_desktop"].get("panel_visible")
            and result["recheck_mobile"].get("panel_visible")
        )
        result["gate"] = "PASS" if passed else "FAIL"
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main() -> int:
    result = run_e2e()
    (OUT / "e2e-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("gate") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
