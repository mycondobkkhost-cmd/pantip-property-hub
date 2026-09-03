#!/usr/bin/env python3
"""Phase Z1 browser QA — headless Chrome screenshots (overlay from engine directly)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.hub.area_engine_overlay import build_area_engine_overlay

OUT = Path("/tmp/pantip-phase-z1-visual")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
ASPIRE_ID = "d9a5d2b2-355a-55e6-b471-773b9badc8c6"


def build_demo_html(overlay: dict, *, mobile: bool = False) -> str:
    lines = []
    for block in overlay.get("existing_assignment_analysis") or []:
        cls = "safe" if block.get("classification") == "AUTO_SAFE" else (
            "bad" if block.get("classification") == "REJECT_QUARANTINE" else ""
        )
        expl = "<br>".join(block.get("explanation_th") or [])
        lines.append(f"<div class='line {cls}'><strong>{block.get('name_th')}</strong><br>{expl}</div>")
    body = "\n".join(lines) or f"<p>{overlay.get('project_outcome_label_th', '')}</p>"
    width = "390px" if mobile else "720px"
    return f"""<!DOCTYPE html><html lang='th'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<style>
body{{font-family:'Noto Sans Thai',system-ui,sans-serif;margin:16px;background:#f6f7f9;max-width:{width}}}
.banner{{background:#fff7ed;border-bottom:2px solid #fdba74;padding:10px;font-weight:600;color:#9a3412;text-align:center}}
.box{{border:2px dashed #64748b;background:#f8fafc;padding:12px;border-radius:10px;margin:12px 0}}
.warn{{color:#b45309;font-weight:600;font-size:.9rem}}
.line{{border-left:3px solid #94a3b8;padding-left:10px;margin:8px 0}}
.safe{{border-color:#0b6e4f}} .bad{{border-color:#b91c1c}}
</style></head><body>
<div class='banner'>ตรวจสอบข้อมูล Master — Pantip Hub</div>
<h2>Aspire Onnut Station</h2>
<p class='warn'>ผลวิเคราะห์นี้ยังไม่ได้แก้ข้อมูลจริง — อ้างอิงเท่านั้น</p>
<div class='box'><h3>ผลตรวจสอบจาก Area Engine</h3>
<p><strong>สรุป:</strong> {overlay.get('project_outcome_label_th', '')}</p>
{body}
<p class='warn'>ไม่มีปุ่ม Apply — ไม่ใช่ข้อมูล Pantip/RealXtate ที่ใช้งานจริง</p></div>
</body></html>"""


def screenshot(url: str, path: Path, width: int, height: int) -> None:
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", f"--window-size={width},{height}", f"--screenshot={path}", url],
        check=True,
        capture_output=True,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    overlay = build_area_engine_overlay(ASPIRE_ID)
    desktop_html = OUT / "aspire-overlay-desktop.html"
    mobile_html = OUT / "aspire-overlay-mobile.html"
    desktop_html.write_text(build_demo_html(overlay, mobile=False), encoding="utf-8")
    mobile_html.write_text(build_demo_html(overlay, mobile=True), encoding="utf-8")
    (OUT / "overlay-api-response.json").write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding="utf-8")
    screenshot(f"file://{desktop_html}", OUT / "desktop-aspire-overlay-1440x900.png", 1440, 900)
    screenshot(f"file://{mobile_html}", OUT / "mobile-aspire-overlay-390x844.png", 390, 844)
    print(json.dumps({"ok": True, "overlay_ok": overlay.get("ok"), "files": sorted(str(p) for p in OUT.iterdir())}, indent=2))


if __name__ == "__main__":
    main()
