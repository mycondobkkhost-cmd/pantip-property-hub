#!/usr/bin/env python3
"""Phase Z4 authenticated master definition review QA."""

from __future__ import annotations

import http.cookiejar
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path("/tmp/pantip-phase-z4-visual")
BASE = "http://127.0.0.1:8765"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ROOT = Path(__file__).resolve().parent.parent


def wait_server(timeout: float = 15.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE}/master-definition-review/", timeout=2) as r:
                return r.status == 200
        except Exception:
            time.sleep(0.3)
    return False


def login() -> http.cookiejar.CookieJar | None:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=json.dumps({"username": "angkarn1996", "password": "localdev"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(req, timeout=10) as resp:
            body = json.loads(resp.read())
            return cj if body.get("ok") else None
    except Exception:
        return None


def fetch_packets(cj: http.cookiejar.CookieJar) -> dict | None:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(f"{BASE}/api/master-definition-review/packets")
    try:
        with opener.open(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def screenshot(name: str, width: int, height: int) -> Path | None:
    if not Path(CHROME).is_file():
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.png"
    url = f"{BASE}/master-definition-review/"
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        f"--window-size={width},{height}",
        f"--screenshot={out}",
        url,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        return out if out.is_file() else None
    except Exception:
        return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    result = {
        "server_started": False,
        "login_ok": False,
        "packets_ok": False,
        "desktop_screenshot": None,
        "mobile_screenshot": None,
        "gate": "NOT VERIFIED",
    }

    proc = subprocess.Popen(
        ["bash", str(ROOT / "scripts/start_master_definition_review.sh")],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        if not wait_server():
            result["error"] = "server did not start"
            (OUT / "qa-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            return 1

        result["server_started"] = True
        cj = login()
        result["login_ok"] = cj is not None
        pkts = fetch_packets(cj) if cj else None
        result["packets_ok"] = bool(pkts and pkts.get("ok"))
        if pkts:
            result["topics"] = list((pkts.get("packets") or {}).keys())

        desk = screenshot("master-definition-desktop", 1440, 900)
        mob = screenshot("master-definition-mobile", 390, 844)
        result["desktop_screenshot"] = str(desk) if desk else None
        result["mobile_screenshot"] = str(mob) if mob else None

        if result["login_ok"] and result["packets_ok"] and desk and mob:
            result["gate"] = "PASS"
        elif result["server_started"] and result["packets_ok"]:
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
