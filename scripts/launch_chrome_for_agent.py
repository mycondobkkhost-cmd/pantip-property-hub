#!/usr/bin/env python3
"""Launch Google Chrome (real profile) for the comment Agent via CDP."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.facebook.chrome_profiles import (  # noqa: E402
    find_chrome_executable,
    list_chrome_profiles,
)


def _cdp_ready(cdp_url: str) -> bool:
    url = cdp_url.rstrip("/") + "/json/version"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            return int(getattr(resp, "status", 200) or 200) < 500
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False


def _hub_get_selected(hub: str, token: str, agent_id: str) -> tuple[str, str]:
    if not hub or not token:
        return "", ""
    req = urllib.request.Request(
        hub.rstrip("/") + "/api/fb-agent/status?agent=" + urllib.parse.quote(agent_id),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        return (
            str(data.get("chrome_profile_dir") or "").strip(),
            str(data.get("chrome_profile_name") or "").strip(),
        )
    except Exception:  # noqa: BLE001
        return "", ""


def _quit_chrome() -> None:
    if sys.platform == "darwin":
        subprocess.run(
            ["osascript", "-e", 'quit app "Google Chrome"'],
            check=False,
            capture_output=True,
        )
    elif sys.platform.startswith("win"):
        subprocess.run(["taskkill", "/IM", "chrome.exe", "/F"], check=False, capture_output=True)
    for _ in range(20):
        time.sleep(0.25)


def main() -> int:
    import urllib.parse

    parser = argparse.ArgumentParser(description="Open real Chrome for FB Agent")
    parser.add_argument("--port", default=os.getenv("FB_CDP_PORT", "9222"))
    parser.add_argument("--profile-dir", default=os.getenv("FB_CHROME_PROFILE_DIRECTORY", ""))
    parser.add_argument("--hub", default=os.getenv("HUB_URL", "https://hub.realxtateth.com"))
    parser.add_argument("--token", default=os.getenv("COMMENT_AGENT_TOKEN", ""))
    parser.add_argument("--agent", default=os.getenv("COMMENT_AGENT_ID", "owner"))
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args()

    profiles = list_chrome_profiles()
    if args.list_only:
        print(json.dumps(profiles, ensure_ascii=False, indent=2))
        return 0

    chrome = find_chrome_executable()
    if not chrome:
        print("ไม่พบ Google Chrome")
        return 1

    port = str(args.port or "9222").strip()
    cdp = f"http://127.0.0.1:{port}"
    profile_dir = (args.profile_dir or "").strip()
    profile_name = ""

    if not profile_dir:
        profile_dir, profile_name = _hub_get_selected(args.hub, args.token, args.agent)

    if profile_dir and not profile_name:
        for p in profiles:
            if p.get("dir") == profile_dir:
                profile_name = p.get("name") or profile_dir
                break
        profile_name = profile_name or profile_dir

    if _cdp_ready(cdp):
        print(f"✓ Chrome โหมด Agent พร้อมแล้ว ({cdp})")
        if profile_dir:
            print(f"  โปรไฟล์ที่เลือกใน Hub: {profile_name or profile_dir}")
            print("  ถ้าต้องการสลับโปรไฟล์: ปิด Chrome แล้วรันไฟล์นี้อีกครั้ง")
        return 0

    print("กำลังเปิด Google Chrome โหมด Agent…")
    if profile_dir:
        print(f"โปรไฟล์: {profile_name or profile_dir} ({profile_dir})")
    else:
        print("ยังไม่ได้เลือกโปรไฟล์ใน Hub — จะเปิด Chrome รวม (เลือกโปรไฟล์ใน Hub ได้)")

    # Chrome must not already be running without debug port
    _quit_chrome()
    time.sleep(1.0)

    cmd = [
        str(chrome),
        f"--remote-debugging-port={port}",
        "--restore-last-session",
    ]
    if profile_dir:
        cmd.append(f"--profile-directory={profile_dir}")

    log_path = Path("/tmp/ptp-chrome-agent.log") if sys.platform != "win32" else Path(os.environ.get("TEMP", ".")) / "ptp-chrome-agent.log"
    log_f = open(log_path, "w", encoding="utf-8")  # noqa: SIM115
    subprocess.Popen(cmd, stdout=log_f, stderr=subprocess.STDOUT, start_new_session=True)

    ok = False
    for _ in range(40):
        if _cdp_ready(cdp):
            ok = True
            break
        time.sleep(0.25)

    if not ok:
        print("เปิด Chrome แล้วแต่เชื่อมโหมด Agent ไม่ได้")
        print(f"ดู log: {log_path}")
        return 1

    print(f"✓ พร้อมแล้ว · CDP={cdp}")
    if profile_dir:
        print(f"✓ ใช้โปรไฟล์: {profile_name or profile_dir}")
    print("ขั้นถัดไป: เปิดระบบคอมเมนต์ → ใน Hub กดล็อกอินเฟส")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
