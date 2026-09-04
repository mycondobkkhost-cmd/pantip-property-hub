#!/usr/bin/env python3
"""Authenticated local QA for Phase Z7 unified operator dashboard."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path("/tmp/pantip-phase-z7-visual")
BASE = "http://127.0.0.1:8765"


def wait_server(timeout: float = 20.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/operator-follow-up/", timeout=2) as r:
                return r.status == 200
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"server_started": False, "login_ok": False, "screenshots": {}, "gate": "NOT VERIFIED"}

    proc = subprocess.Popen(
        ["bash", str(ROOT / "scripts/start_z7_operational_pilot.sh")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        if not wait_server():
            result["error"] = "server timeout"
            (OUT / "qa-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            return 1
        result["server_started"] = True

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context()
            login = ctx.request.post(
                f"{BASE}/api/auth/login",
                data=json.dumps({"username": "angkarn1996", "password": "localdev"}),
                headers={"Content-Type": "application/json"},
            )
            result["login_ok"] = login.ok and login.json().get("ok")

            pages = [
                ("dashboard-desktop", "/operator-follow-up/", 1440, 900),
                ("dashboard-mobile", "/operator-follow-up/", 390, 844),
                ("freshness-desktop", "/listing-freshness/", 1440, 900),
            ]
            for name, url, w, h in pages:
                page = ctx.new_page()
                page.set_viewport_size({"width": w, "height": h})
                page.goto(f"{BASE}{url}")
                page.wait_for_timeout(1200)
                if "dashboard" in name:
                    try:
                        page.click("#seedBtn")
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass
                shot = OUT / f"{name}.png"
                page.screenshot(path=str(shot), full_page=True)
                result["screenshots"][name] = str(shot)
                page.close()
            browser.close()

        if result["login_ok"] and len(result["screenshots"]) >= 3:
            result["gate"] = "PASS"
        elif result["server_started"]:
            result["gate"] = "PARTIAL"

        (OUT / "qa-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
        return 0 if result["gate"] == "PASS" else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
