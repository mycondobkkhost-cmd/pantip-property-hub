#!/usr/bin/env python3
"""Phase Z10 authenticated Playwright E2E — real browser, isolated test data."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
E2E_DIR = ROOT / ".local" / "phase_z10_e2e"
OUT = Path("/tmp/pantip-phase-z10-e2e")
PORT = os.environ.get("HUB_PORT", "8765")
BASE = f"http://127.0.0.1:{PORT}"

SOURCE_CASES = {
    "A_facebook_url": "https://www.facebook.com/share/p/z10test",
    "B_https_url": "https://example.com/listing/z10",
    "C_thai_text": "รหัสอ้างอิง LI-ทดสอบ",
    "D_english_text": "staff note REF-Z10",
    "E_spaces": "note with spaces 123",
    "F_mixed": "FB-99 / โพสต์เก่า 2024",
    "G_empty": "",
    "H_malformed": "http:// not valid url (copy)",
    "X_xss": '<script>alert("xss")</script>',
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


def _http_json(method: str, path: str, body: dict | None = None, cookie: str = "") -> tuple[int, dict]:
    data = None
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": raw}


def _prepare_e2e_data() -> dict[str, Any]:
    E2E_DIR.mkdir(parents=True, exist_ok=True)
    projects_src = ROOT / "data" / "projects.json"
    if not (E2E_DIR / "projects.json").exists() and projects_src.exists():
        (E2E_DIR / "projects.json").write_text(projects_src.read_text(encoding="utf-8"), encoding="utf-8")
    if not (E2E_DIR / "properties.json").exists():
        (E2E_DIR / "properties.json").write_text("[]", encoding="utf-8")
    projects = json.loads((E2E_DIR / "projects.json").read_text(encoding="utf-8"))
    pid = projects[0]["id"] if projects else ""
    return {"project_id": pid, "projects": projects}


def run_e2e() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "browser_launched": False,
        "login_ok": False,
        "dom_interaction": False,
        "source_cases": {},
        "scrape_boundary": {},
        "coagent_privacy": {},
        "operator_auth": {},
        "recheck_panel": {},
        "xss_escaped": None,
        "gate": "NOT VERIFIED",
    }
    prep = _prepare_e2e_data()
    proc = subprocess.Popen(
        ["bash", str(ROOT / "scripts/start_z10_internal_pilot.sh")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "HUB_PORT": PORT, "PANTIP_E2E_DATA_ROOT": str(E2E_DIR)},
    )
    cookie = ""
    try:
        if not _wait_server():
            result["error"] = "server timeout"
            return result

        # Login via API
        status, login = _http_json(
            "POST",
            "/api/auth/login",
            {"username": "angkarn1996", "password": "localdev"},
        )
        result["login_ok"] = status == 200 and login.get("ok")
        if not result["login_ok"]:
            result["error"] = "login failed"
            return result

        # Re-login with cookie jar via urllib for subsequent calls — use Playwright context for cookie
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            result["error"] = "playwright not installed"
            result["gate"] = "BLOCKED"
            return result

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            login_resp = ctx.request.post(
                f"{BASE}/api/auth/login",
                data=json.dumps({"username": "angkarn1996", "password": "localdev"}),
                headers={"Content-Type": "application/json"},
            )
            result["login_ok"] = login_resp.ok and login_resp.json().get("ok")
            result["browser_launched"] = True
            page = ctx.new_page()

            # Source reference API CRUD (isolated data)
            project_id = prep["project_id"]
            prop_id = ""
            for name, val in SOURCE_CASES.items():
                if name == "G_empty" and not prop_id:
                    continue
                payload = {
                    "property": {
                        "project_id": project_id,
                        "code_prefix": "RXT",
                        "property_type": "Condo",
                        "rent_price": "25000",
                        "source_url": val,
                        "notes": "PRIVATE_Z10_NOTE",
                        "owner_phones": ["0899999999"],
                        "post_url": "https://www.facebook.com/example/public-post",
                    }
                }
                if prop_id:
                    payload = {"id": prop_id, "property": payload["property"]}
                    r = ctx.request.post(f"{BASE}/api/properties/update", data=json.dumps(payload))
                else:
                    r = ctx.request.post(f"{BASE}/api/properties/save", data=json.dumps(payload))
                ok = r.ok
                body = r.json() if r.ok else {}
                if r.ok:
                    prop = body.get("property") or {}
                    prop_id = prop.get("id") or prop_id
                    got = (prop.get("source_url") or "")
                    result["source_cases"][name] = {
                        "save_ok": True,
                        "value_match": got == val,
                        "stored": got,
                    }
                else:
                    result["source_cases"][name] = {"save_ok": False, "status": r.status}

            # Reload via GET properties from isolated file
            if prop_id:
                props = json.loads((E2E_DIR / "properties.json").read_text(encoding="utf-8"))
                row = next((x for x in props if x.get("id") == prop_id), {})
                result["source_reload"] = row.get("source_url")

            # Scrape boundary (mocked in E2E mode)
            for label, url, expect_ok in [
                ("valid_fb", "https://www.facebook.com/share/p/x", True),
                ("plain_text", "plain text note", False),
                ("empty", "", False),
                ("malformed", "http:// bad", False),
            ]:
                r = ctx.request.post(
                    f"{BASE}/api/scrape",
                    data=json.dumps({"url": url}),
                    headers={"Content-Type": "application/json"},
                )
                result["scrape_boundary"][label] = {
                    "status": r.status,
                    "ok": r.ok,
                    "expect_ok": expect_ok,
                    "pass": r.ok == expect_ok,
                }

            # Co-Agent privacy
            r = ctx.request.get(f"{BASE}/api/co/catalog")
            cat = r.json() if r.ok else {}
            blob = json.dumps(cat, ensure_ascii=False)
            forbidden = [
                "PRIVATE_Z10_NOTE",
                "0899999999",
                "staff note REF-Z10",
                "source_url",
                "owner_phones",
            ]
            leaked = [f for f in forbidden if f in blob]
            result["coagent_privacy"] = {
                "ok": r.ok,
                "leaked": leaked,
                "pass": r.ok and not leaked,
            }

            # Operator auth
            anon = p.request.new_context()
            r_denied = anon.post(f"{BASE}/api/operational-settings", data="{}")
            r_get = ctx.request.get(f"{BASE}/api/operational-settings")
            result["operator_auth"] = {
                "unauth_post_blocked": r_denied.status in (401, 403),
                "auth_get_ok": r_get.ok,
            }
            anon.dispose()

            # Browser DOM — source reference field + recheck panel
            page.goto(f"{BASE}/")
            page.wait_for_timeout(1500)
            # Open recheck via follow menu
            page.click('button[data-view="followup"]')
            page.wait_for_timeout(400)
            page.click("#follow-tab-recheck")
            page.wait_for_timeout(1200)
            result["recheck_panel"]["visible"] = page.locator("#recheck-panel:not(.hidden)").count() > 0
            result["recheck_panel"]["stats_strip"] = page.locator("#recheck-stats-strip").inner_text()[:200]

            # Add property panel — type in source field (DOM)
            page.click('button[data-view="properties"]')
            page.wait_for_timeout(300)
            page.evaluate("switchView('add')")
            page.wait_for_timeout(500)
            page.click('[data-link-edit]')
            page.fill("#add-url", SOURCE_CASES["C_thai_text"])
            dom_val = page.input_value("#add-url")
            result["dom_interaction"] = dom_val == SOURCE_CASES["C_thai_text"]
            # XSS in list cell rendering — inject via API then check properties view doesn't execute
            page.goto(f"{BASE}/")
            page.wait_for_timeout(800)
            html = page.content()
            result["xss_escaped"] = "<script>alert" not in html or "xss" not in html.lower()

            shot = OUT / "z10-recheck-desktop.png"
            page.screenshot(path=str(shot), full_page=True)
            result["screenshot"] = str(shot)
            browser.close()

        passed = (
            result["login_ok"]
            and result["browser_launched"]
            and result["dom_interaction"]
            and result["coagent_privacy"].get("pass")
            and result["operator_auth"].get("unauth_post_blocked")
            and result["recheck_panel"].get("visible")
            and all(v.get("pass", v.get("value_match", v.get("save_ok"))) for v in result["source_cases"].values() if isinstance(v, dict))
            and all(v.get("pass") for v in result["scrape_boundary"].values())
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
