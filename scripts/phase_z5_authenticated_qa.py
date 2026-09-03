#!/usr/bin/env python3
"""Phase Z5 authenticated lease opportunity QA with Playwright."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path("/tmp/pantip-phase-z5-visual")
BASE = "http://127.0.0.1:8765"
ROOT = Path(__file__).resolve().parent.parent


def wait_server(timeout: float = 20.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/lease-opportunities/", timeout=2) as r:
                return r.status == 200
        except Exception:
            time.sleep(0.3)
    return False


def run_playwright_qa() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    result = {
        "server_started": False,
        "login_ok": False,
        "api_ok": False,
        "desktop_screenshot": None,
        "mobile_screenshot": None,
        "gate": "NOT VERIFIED",
    }

    proc = subprocess.Popen(
        ["bash", str(ROOT / "scripts/start_lease_opportunity_pilot.sh")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        if not wait_server():
            result["error"] = "server did not start"
            return result
        result["server_started"] = True

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()

            # Authenticate via API (real session cookie)
            login_resp = context.request.post(
                f"{BASE}/api/auth/login",
                data=json.dumps({"username": "angkarn1996", "password": "localdev"}),
                headers={"Content-Type": "application/json"},
            )
            result["login_ok"] = login_resp.ok and login_resp.json().get("ok")

            page = context.new_page()
            page.goto(f"{BASE}/lease-opportunities/")
            page.wait_for_timeout(1000)

            if result["login_ok"]:
                # Seed fixtures via API with authenticated session
                seed = context.request.post(
                    f"{BASE}/api/lease-opportunities/seed-fixtures",
                    data="{}",
                    headers={"Content-Type": "application/json"},
                )
                sync = context.request.post(
                    f"{BASE}/api/notifications/sync",
                    data="{}",
                    headers={"Content-Type": "application/json"},
                )
                page.reload()
                page.wait_for_timeout(1500)
                rows = page.locator("#rows tr").count()
                result["api_ok"] = seed.ok and sync.ok and rows > 0

            desk = OUT / "lease-opportunity-desktop.png"
            page.set_viewport_size({"width": 1440, "height": 900})
            page.screenshot(path=str(desk), full_page=True)
            result["desktop_screenshot"] = str(desk) if desk.is_file() else None

            mob = OUT / "lease-opportunity-mobile.png"
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(mob), full_page=True)
            result["mobile_screenshot"] = str(mob) if mob.is_file() else None

            browser.close()

        if result["login_ok"] and result["api_ok"] and result["desktop_screenshot"] and result["mobile_screenshot"]:
            result["gate"] = "PASS"
        elif result["server_started"] and result["login_ok"]:
            result["gate"] = "PARTIAL"

        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def main() -> int:
    result = run_playwright_qa()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "qa-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result.get("gate") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
