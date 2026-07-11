#!/usr/bin/env python3
"""Study LINE OA chats via Chrome CDP and write local notes for FAQ research."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("logs/line_study")
OUT.mkdir(parents=True, exist_ok=True)

LIST_JS = """
() => {
  const candidates = [...document.querySelectorAll('button, [role=button], div')];
  const rows = [];
  for (const el of candidates) {
    const t = (el.innerText || '').trim();
    if (!t || t.length < 8 || t.length > 400) continue;
    if (!/(น\\.|เมื่อวาน|จันทร์|อังคาร|พุธ|พฤหัส|ศุกร์|เสาร์|อาทิตย์)/.test(t)) continue;
    const lines = t.split('\\n').map(s => s.trim()).filter(Boolean);
    if (lines.length < 2) continue;
    const name = lines[0].slice(0, 60);
    if (/PantipProperty|ช่วยเหลือ|ทั้งหมด|อัปเกรด|ฟิลเตอร์|พื้นฐาน|แท็ก|ข้อความตอบกลับ|การโทร|^ปิด$/.test(name)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 80 || rect.height < 30 || rect.left > 520) continue;
    rows.push({
      name,
      preview: lines.slice(1, 4).join(' | ').slice(0, 200),
      y: Math.round(rect.top),
    });
  }
  const seen = new Set();
  const uniq = [];
  for (const r of rows.sort((a, b) => a.y - b.y)) {
    if (seen.has(r.name)) continue;
    seen.add(r.name);
    uniq.push(r);
  }
  return uniq.slice(0, 50);
}
"""

CLICK_JS = """
(name) => {
  const els = [...document.querySelectorAll('button, [role=button], div')];
  for (const el of els) {
    const t = (el.innerText || '').trim();
    if (!t.startsWith(name)) continue;
    const rect = el.getBoundingClientRect();
    if (rect.left > 520 || rect.width < 80 || rect.height < 28) continue;
    el.click();
    return true;
  }
  return false;
}
"""

THREAD_JS = """
() => {
  const body = document.body.innerText;
  const nodes = [...document.querySelectorAll('div')];
  const msgs = [];
  for (const el of nodes) {
    const t = (el.innerText || '').trim();
    if (!t || t.length < 2 || t.length > 700) continue;
    const rect = el.getBoundingClientRect();
    if (rect.left < 450 || rect.width < 50 || rect.height < 18 || rect.height > 420) continue;
    if (rect.top < 90 || rect.bottom > innerHeight - 50) continue;
    if (el.children.length > 6) continue;
    const lines = t.split('\\n').filter(Boolean);
    if (lines.length > 12) continue;
    msgs.push({ t: t.slice(0, 600), x: Math.round(rect.left), y: Math.round(rect.top) });
  }
  msgs.sort((a, b) => a.y - b.y || a.x - b.x);
  const out = [];
  const seen = new Set();
  for (const m of msgs) {
    const key = m.t.replace(/\\s+/g, ' ').slice(0, 100);
    let dup = false;
    for (const s of seen) {
      if (key === s || key.includes(s) || s.includes(key)) {
        dup = true;
        break;
      }
    }
    if (dup) continue;
    seen.add(key);
    out.push({ x: m.x, y: m.y, text: m.t });
  }
  return { url: location.href, body: body.slice(0, 9000), msgs: out.slice(0, 160) };
}
"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0]
        page = next(pg for pg in ctx.pages if "chat.line.biz" in pg.url)
        page.bring_to_front()
        time.sleep(1)

        all_names: list[dict] = []
        for _ in range(7):
            rows = page.evaluate(LIST_JS)
            for r in rows:
                if r["name"] not in {x["name"] for x in all_names}:
                    all_names.append(r)
            page.mouse.move(220, 400)
            page.mouse.wheel(0, 950)
            time.sleep(1.0)

        (OUT / "chat_list.json").write_text(
            json.dumps(all_names, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"found_chats={len(all_names)}", flush=True)
        for r in all_names[:30]:
            print(f"- {r['name']}: {r['preview'][:90]}", flush=True)

        for _ in range(10):
            page.mouse.move(220, 400)
            page.mouse.wheel(0, -1400)
            time.sleep(0.2)
        time.sleep(1)

        transcripts = []
        for i, chat in enumerate(all_names[:20]):
            name = chat["name"]
            print(f"=== open [{i}] {name} ===", flush=True)
            ok = page.evaluate(CLICK_JS, name)
            if not ok:
                print("  click_failed", flush=True)
                continue
            time.sleep(1.8)
            for _ in range(5):
                page.mouse.move(920, 320)
                page.mouse.wheel(0, -800)
                time.sleep(0.35)
            time.sleep(0.7)
            data = page.evaluate(THREAD_JS)
            transcripts.append(
                {
                    "chat_name": name,
                    "preview": chat.get("preview"),
                    "msgs": data.get("msgs", [])[:100],
                    "body_excerpt": data.get("body", "")[:5000],
                }
            )
            print(f"  msgs={len(data.get('msgs', []))}", flush=True)

        (OUT / "transcripts.json").write_text(
            json.dumps(transcripts, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved transcripts={len(transcripts)}", flush=True)


if __name__ == "__main__":
    main()
