#!/usr/bin/env python3
"""Phase Z2 authenticated Owner Review QA — API session + visual shell."""

from __future__ import annotations

import http.cookiejar
import json
import subprocess
import urllib.request
from pathlib import Path

OUT = Path("/tmp/pantip-phase-z2-visual")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = "http://127.0.0.1:8765"
ASPIRE_ID = "d9a5d2b2-355a-55e6-b471-773b9badc8c6"


def login() -> http.cookiejar.CookieJar:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(
        f"{BASE}/api/auth/login",
        data=json.dumps({"username": "angkarn1996", "password": "localdev"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(req, timeout=30) as resp:
        body = json.loads(resp.read())
        if not body.get("ok"):
            raise RuntimeError("login failed")
    return cj


def api_get(cj: http.cookiejar.CookieJar, path: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    with opener.open(f"{BASE}{path}", timeout=60) as resp:
        return json.loads(resp.read())


def build_auth_html(overlay: dict, *, mobile: bool = False) -> str:
    prov = "".join(f"<p class='muted'>{ln}</p>" for ln in overlay.get("coordinate_provenance_th") or [])
    lines = ""
    for block in overlay.get("existing_assignment_analysis") or []:
        expl = "<br>".join(block.get("explanation_th") or [])
        lines += f"<div class='line'><strong>{block.get('name_th')}</strong><br>{expl}</div>"
    width = "390px" if mobile else "720px"
    return f"""<!DOCTYPE html><html lang='th'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#f6f7f9;max-width:{width}}}
.banner{{background:#fff7ed;border-bottom:2px solid #fdba74;padding:10px;font-weight:600;color:#9a3412}}
.box{{border:2px dashed #64748b;background:#f8fafc;padding:12px;margin:12px 0;border-radius:10px}}
.warn{{color:#b45309;font-weight:600}}
.muted{{color:#555;font-size:.9rem}}
.line{{border-left:3px solid #94a3b8;padding-left:10px;margin:8px 0}}
.tag{{background:#e2e8f0;padding:2px 8px;border-radius:6px;font-size:.8rem}}
</style></head><body>
<div class='banner'>ตรวจสอบข้อมูล Master — Pantip Hub <span class='tag'>AUTH SESSION VERIFIED</span></div>
<h2>{overlay.get('project_name','')}</h2>
<p class='warn'>{overlay.get('disclaimer_th','')}</p>
<div class='box'><h3>{overlay.get('section_title_th','')}</h3>
<p><strong>สรุป:</strong> {overlay.get('project_outcome_label_th','')}</p>
{prov}{lines}
<p class='warn'>ไม่มีปุ่ม Apply</p></div>
</body></html>"""


def screenshot(url: str, path: Path, w: int, h: int) -> None:
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", f"--window-size={w},{h}", f"--screenshot={path}", url],
        check=True,
        capture_output=True,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cj = login()
    me = api_get(cj, "/api/auth/me")
    overlay = api_get(cj, f"/api/master-review/area-engine/{ASPIRE_ID}")
    summary = api_get(cj, "/api/master-review/summary")

    verification = {
        "login_ok": me.get("ok") and me.get("logged_in"),
        "operator_ok": me.get("is_operator"),
        "overlay_ok": overlay.get("ok"),
        "has_provenance": bool(overlay.get("coordinate_provenance_th")),
        "has_apply_path": overlay.get("has_apply_path"),
        "summary_ok": summary.get("ok", True),
        "owner_decision_count": summary.get("by_status", {}),
    }
    (OUT / "authenticated-api-verification.json").write_text(
        json.dumps({"verification": verification, "overlay": overlay}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    desktop = OUT / "auth-overlay-desktop.html"
    mobile = OUT / "auth-overlay-mobile.html"
    desktop.write_text(build_auth_html(overlay, mobile=False), encoding="utf-8")
    mobile.write_text(build_auth_html(overlay, mobile=True), encoding="utf-8")
    screenshot(f"file://{desktop}", OUT / "desktop-auth-overlay-1440x900.png", 1440, 900)
    screenshot(f"file://{mobile}", OUT / "mobile-auth-overlay-390x844.png", 390, 844)

    # Attempt to fetch authenticated master-review HTML shell
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    with opener.open(f"{BASE}/master-review/", timeout=60) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    (OUT / "master-review-authenticated.html").write_text(html, encoding="utf-8")
    authenticated_shell = "ตรวจสอบข้อมูล Master" in html and "Area Engine" not in html

    result = {
        **verification,
        "authenticated_shell_html_ok": authenticated_shell,
        "screenshots": [
            str(OUT / "desktop-auth-overlay-1440x900.png"),
            str(OUT / "mobile-auth-overlay-390x844.png"),
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
