#!/usr/bin/env python3
"""Phase Z13.3 local browser E2E — boot network counts against isolated Hub."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = ROOT / ".local" / "phase_z13_3_e2e"
OUT = Path("/tmp/pantip-phase-z13-3-e2e")
PORT = os.environ.get("PORT") or os.environ.get("HUB_PORT") or "8777"
BASE = f"http://127.0.0.1:{PORT}"


def _wait_server(timeout: float = 45.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def _prepare() -> None:
    E2E_DIR.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    projects = [
        {"id": "p1", "canonical_name": "Demo One", "aliases": []},
        {"id": "p2", "canonical_name": "Demo Two", "aliases": []},
    ]
    properties = [
        {
            "id": "a1",
            "code": "PTP9001",
            "project_id": "p1",
            "project_name": "Demo One",
            "rent_price": "20000",
            "sale_price": "",
            "import_status": "active",
            "last_listed_at": "01/01/2024",
        },
        {
            "id": "a2",
            "code": "PTP9002",
            "project_id": "p1",
            "project_name": "Demo One",
            "rent_price": "",
            "sale_price": "5000000",
            "import_status": "active",
            "last_listed_at": "01/01/2024",
        },
        {
            "id": "a3",
            "code": "PTP9003",
            "project_id": "p2",
            "project_name": "Demo Two",
            "rent_price": "15000",
            "sale_price": "",
            "import_status": "active",
            "last_listed_at": "01/01/2024",
        },
    ]
    (E2E_DIR / "projects.json").write_text(json.dumps(projects, ensure_ascii=False), encoding="utf-8")
    (E2E_DIR / "properties.json").write_text(json.dumps(properties, ensure_ascii=False), encoding="utf-8")
    for name in ("queue.json", "customers.json", "tenants.json"):
        (E2E_DIR / name).write_text(json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8")
    (E2E_DIR / "focus.json").write_text(
        json.dumps({"items": [], "ids": [], "stats": {"total": 0}}, ensure_ascii=False),
        encoding="utf-8",
    )


def _attach_counters(page) -> dict:
    counts = {"catalog": 0, "queue": 0, "focus": 0, "preview": 0, "auth_me": 0}

    def on_req(req):
        url = req.url
        if "/api/hub/catalog" in url:
            counts["catalog"] += 1
        elif "/api/queue" in url:
            counts["queue"] += 1
        elif "/api/focus" in url:
            counts["focus"] += 1
        elif "preview-data.js" in url:
            counts["preview"] += 1
        elif "/api/auth/me" in url:
            counts["auth_me"] += 1

    page.on("request", on_req)
    return counts


def _metrics(page) -> dict:
    return page.evaluate(
        """() => ({
      props: (window.PTP_DATA && window.PTP_DATA.properties || []).length,
      pmap: Object.keys((window.PTP_DATA && window.PTP_DATA.project_map) || {}).length,
      cards: document.querySelectorAll('.prop-sheet-row,.prop-card').length,
      boot: !!window.__ptpHubBootDone,
      initCount: window.__ptpInitDataCount || 0,
      scope: window.PTP_DATA && window.PTP_DATA.catalog_scope,
      row: (document.querySelector('#row-count')||{}).textContent || null,
      page: (document.querySelector('#prop-page-compact')||{}).textContent || null,
    })"""
    )


def run() -> dict:
    from playwright.sync_api import sync_playwright

    _prepare()
    result: dict = {"ok": False, "cases": {}, "problems": []}
    env = {
        **os.environ,
        "PORT": str(PORT),
        "HUB_PORT": str(PORT),
        "PANTIP_E2E_DATA_ROOT": str(E2E_DIR),
        "HUB_LOCAL_DEV": "1",
        "HUB_SKIP_PREVIEW_BOOT": "1",
        "HUB_STARTUP_SHEET_SYNC": "0",
        "HUB_USERS_JSON": json.dumps(
            {"angkarn1996": {"password": "localdev", "name": "E2E", "role": "admin"}}
        ),
        "HUB_SESSION_SECRET": "z13-3-e2e-secret",
    }
    log_path = OUT / "server.log"
    logf = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "hub_server.py")],
        cwd=str(ROOT),
        env=env,
        stdout=logf,
        stderr=logf,
    )
    try:
        if not _wait_server():
            result["error"] = "server_start_failed"
            try:
                result["server_log_tail"] = log_path.read_text(encoding="utf-8")[-2000:]
            except Exception:
                pass
            return result

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, channel="chrome")
            for width in (375, 390, 430, 834):
                ctx = browser.new_context(viewport={"width": width, "height": 844})
                page = ctx.new_page()
                case: dict = {"width": width}

                counts = _attach_counters(page)
                page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
                page.fill("#username", "angkarn1996")
                page.fill("#password", "localdev")
                page.click('#login-form button[type="submit"]')
                page.wait_for_timeout(2500)
                try:
                    page.wait_for_function(
                        "() => !!window.__ptpHubBootDone && Array.isArray((window.PTP_DATA||{}).properties)",
                        timeout=30000,
                    )
                except Exception as e:
                    case["login_wait_err"] = str(e)[:160]
                page.wait_for_timeout(800)
                case["fresh_login"] = {**counts, **_metrics(page)}

                counts2 = _attach_counters(page)
                # zero previous by replacing dict contents after attach — attach creates new dict
                page.reload(wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2500)
                case["hard_reload"] = {**counts2, **_metrics(page)}

                page3_counts = {"catalog": 0, "queue": 0, "focus": 0, "preview": 0}
                page3 = ctx.new_page()

                def on_req3(req, c=page3_counts):
                    url = req.url
                    if "/api/hub/catalog" in url:
                        c["catalog"] += 1
                    elif "/api/queue" in url:
                        c["queue"] += 1
                    elif "/api/focus" in url:
                        c["focus"] += 1
                    elif "preview-data.js" in url:
                        c["preview"] += 1

                page3.on("request", on_req3)
                page3.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000)
                page3.wait_for_timeout(2500)
                case["new_tab"] = {**page3_counts, **_metrics(page3)}
                page3.close()
                ctx.close()
                result["cases"][str(width)] = case

            # zero-property API acceptance via isolated server
            zero_ok = False
            try:
                # Direct unit already covers payload; here verify client helper text exists
                html = (ROOT / "hub" / "preview.html").read_text(encoding="utf-8")
                zero_ok = "Array.isArray(data.properties)" in html and "__ptpHubCatalogPromise" in html
            except Exception:
                zero_ok = False
            result["zero_property_helpers"] = zero_ok
            browser.close()

        ok = True
        problems = []
        for w, case in result["cases"].items():
            for key in ("fresh_login", "hard_reload", "new_tab"):
                c = case[key]
                if c.get("catalog", 0) != 1:
                    ok = False
                    problems.append(f"{w}/{key} catalog={c.get('catalog')}")
                if c.get("preview", 0) != 0:
                    ok = False
                    problems.append(f"{w}/{key} preview={c.get('preview')}")
                if c.get("queue", 0) != 1:
                    ok = False
                    problems.append(f"{w}/{key} queue={c.get('queue')}")
                if c.get("focus", 0) != 1:
                    ok = False
                    problems.append(f"{w}/{key} focus={c.get('focus')}")
                if int(c.get("initCount") or 0) > 1:
                    ok = False
                    problems.append(f"{w}/{key} initCount={c.get('initCount')}")
                if key == "fresh_login" and int(c.get("props") or 0) < 1:
                    ok = False
                    problems.append(f"{w}/{key} props={c.get('props')}")
                if key == "fresh_login" and int(c.get("pmap") or 0) < 1:
                    ok = False
                    problems.append(f"{w}/{key} pmap={c.get('pmap')}")
        if not zero_ok:
            ok = False
            problems.append("zero_property_helpers_missing")
        result["ok"] = ok
        result["problems"] = problems
        return result
    finally:
        try:
            logf.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    out = run()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    raise SystemExit(0 if out.get("ok") else 1)
