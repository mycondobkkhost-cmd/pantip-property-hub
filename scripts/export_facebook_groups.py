#!/usr/bin/env python3
"""Export / enrich Facebook groups for the logged-in account (Playwright).

Usage:
  # เฟสหลัก
  python3 scripts/export_facebook_groups.py

  # เฟสอีกบัญชี — คัดเฉพาะอสังหา แล้วรวมเข้าสมุดกลุ่ม
  python3 scripts/export_facebook_groups.py --account alt

  # เติมชื่อที่ขาด
  python3 scripts/export_facebook_groups.py --enrich-names
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
COOKIES_DIR = BASE_DIR / "cookies"
OUT_JSON = BASE_DIR / "data" / "facebook_groups.json"
OUT_CSV = BASE_DIR / "data" / "facebook_groups.csv"
OUT_ALT_JSON = BASE_DIR / "data" / "facebook_groups_alt.json"

GROUPS_URL = "https://www.facebook.com/groups/joins/?nav_source=tab"

JUNK_NAMES = {
    "groups",
    "กลุ่ม",
    "เรียงลำดับ",
    "sort",
    "see all",
    "ดูทั้งหมด",
    "joined",
    "เข้าร่วมแล้ว",
    "แชท",
    "chat",
    "chats",
    "messenger",
    "facebook",
    "home",
    "ข่าวสาร",
    "notifications",
    "menu",
    "search",
    "ค้นหา",
    "log in",
    "เข้าสู่ระบบ",
}


def clean_group_url(href: str) -> str | None:
    if not href or ("facebook.com/groups/" not in href and "/groups/" not in href):
        return None
    href = href.split("?")[0].rstrip("/")
    if href.startswith("/"):
        href = "https://www.facebook.com" + href
    bad = ("/groups/joins", "/groups/feed", "/groups/create", "/groups/discover")
    if any(b in href for b in bad):
        return None
    parsed = urlparse(href)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2 or parts[0] != "groups":
        return None
    slug = parts[1]
    if slug in {"joins", "feed", "create", "discover"}:
        return None
    return urlunparse(("https", "www.facebook.com", f"/groups/{slug}", "", "", ""))


def is_placeholder_name(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return True
    if re.fullmatch(r"Group\s+\d+", n, re.I):
        return True
    if re.fullmatch(r"\d{6,}", n):
        return True
    if n.lower() in JUNK_NAMES:
        return True
    if len(n) < 3:
        return True
    return False


def clean_display_name(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip())
    n = re.split(r"\s*[|·•]\s*Facebook\s*$", n, flags=re.I)[0].strip()
    n = re.split(r"\s*\|\s*", n)[0].strip()
    n = re.split(r"\s*ใช้งานล่าสุด\s*", n)[0].strip()
    n = re.split(r"\s*Last active\s*", n, flags=re.I)[0].strip()
    # drop trailing member counts like "1.2K members"
    n = re.sub(r"\s+[\d,.]+\s*(?:k|m)?\s*(?:members?|สมาชิก).*$", "", n, flags=re.I).strip()
    return n[:160]


def guess_name(text: str) -> str:
    skip_sub = (
        "เข้าร่วมแล้ว",
        "joined",
        "ดูกลุ่ม",
        "visit group",
        "สมาชิก",
        "members",
        "โพสต์ล่าสุด",
        "last post",
        "ใช้งานล่าสุด",
        "last active",
        "เรียงลำดับ",
        "sort",
        "see all",
        "ดูทั้งหมด",
    )
    for ln in (text or "").splitlines():
        ln = clean_display_name(ln)
        if not ln or len(ln) < 2:
            continue
        low = ln.lower()
        if any(s in low for s in skip_sub):
            continue
        if ln.startswith("http"):
            continue
        if re.fullmatch(r"[\d,.\s]+", ln):
            continue
        if is_placeholder_name(ln):
            continue
        return ln
    return ""


def extract_link_name(a) -> str:
    """Prefer visible text, then aria-label / title / nested image alt."""
    try:
        name = clean_display_name(a.inner_text() or "")
        if name and not is_placeholder_name(name) and name.lower() not in JUNK_NAMES:
            return name
    except Exception:
        pass

    for attr in ("aria-label", "title"):
        try:
            val = clean_display_name(a.get_attribute(attr) or "")
            if val and not is_placeholder_name(val) and val.lower() not in JUNK_NAMES:
                return val
        except Exception:
            pass

    try:
        nested = a.evaluate(
            """el => {
              const img = el.querySelector('img[alt]');
              if (img && img.alt) return img.alt;
              const labeled = el.querySelector('[aria-label]');
              if (labeled) return labeled.getAttribute('aria-label') || '';
              return '';
            }"""
        )
        nested = clean_display_name(nested or "")
        if nested and not is_placeholder_name(nested) and nested.lower() not in JUNK_NAMES:
            return nested
    except Exception:
        pass

    try:
        parent = a.evaluate(
            """el => {
              let n = el;
              for (let i=0;i<8 && n;i++) n = n.parentElement;
              return n ? (n.innerText || '') : '';
            }"""
        )
        return guess_name(parent)
    except Exception:
        return ""


def fetch_group_name_from_page(page, url: str) -> str:
    """Open group page and read og:title / <title> / heading — reject UI junk."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2.0)
        candidates = page.evaluate(
            """() => {
              const out = [];
              const push = (v) => { if (v && String(v).trim()) out.push(String(v).trim()); };
              const og = document.querySelector('meta[property="og:title"]');
              if (og) push(og.content);
              const tw = document.querySelector('meta[name="twitter:title"]');
              if (tw) push(tw.content);
              push(document.title);
              document.querySelectorAll('h1').forEach(h => push(h.innerText));
              document.querySelectorAll('[role="main"] [role="heading"]').forEach(h => push(h.innerText));
              return out;
            }"""
        )
        for raw in candidates or []:
            name = clean_display_name(raw)
            if not name or is_placeholder_name(name):
                continue
            if len(name) >= 4:
                return name
        best = ""
        for raw in candidates or []:
            name = clean_display_name(raw)
            if name and not is_placeholder_name(name) and len(name) > len(best):
                best = name
        return best
    except Exception as exc:
        print(f"    ! อ่านชื่อไม่ได้ {url}: {exc}", flush=True)
    return ""


def is_logged_in(page) -> bool:
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
    time.sleep(2)
    cookies = page.context.cookies()
    if not any(c.get("name") == "c_user" for c in cookies):
        return False
    if page.locator('input[name="email"]').count() and page.locator('input[name="pass"]').count():
        return False
    return True


def scrape(page, max_scrolls: int = 45) -> list[dict]:
    page.goto(GROUPS_URL, wait_until="domcontentloaded")
    time.sleep(3)
    found: dict[str, dict] = {}
    stable = 0
    last = 0

    for i in range(max_scrolls):
        page.mouse.wheel(0, 2400)
        time.sleep(1.2)
        links = page.locator('a[href*="/groups/"]')
        for idx in range(links.count()):
            try:
                a = links.nth(idx)
                href = a.get_attribute("href") or ""
                url = clean_group_url(href)
                if not url or url in found:
                    continue
                name = extract_link_name(a)
                if not name:
                    slug = url.rstrip("/").rsplit("/", 1)[-1]
                    name = f"Group {slug}" if slug.isdigit() else slug
                found[url] = {
                    "name": name[:160],
                    "url": url,
                    "zone_tags": [],
                    "offer_tags": [],
                    "price_band": "",
                    "notes": "",
                }
            except Exception:
                continue

        print(f"  scroll {i+1}/{max_scrolls} · {len(found)} groups", flush=True)
        if len(found) == last:
            stable += 1
        else:
            stable = 0
            last = len(found)
        if stable >= 6 and found:
            break

    out = [g for g in found.values() if g["name"] not in {"เรียงลำดับ", "Groups", "กลุ่ม"}]
    return sorted(out, key=lambda g: g["name"].lower())


def enrich_names(page, groups: list[dict], *, limit: int = 0) -> list[dict]:
    """Visit group pages to replace Group <id> placeholders with real titles."""
    need = [g for g in groups if is_placeholder_name(g.get("name") or "")]
    if limit > 0:
        need = need[:limit]
    print(f"ต้องดึงชื่อจริง {len(need)} กลุ่ม…", flush=True)
    done = 0
    for g in need:
        url = g.get("url") or ""
        if not url:
            continue
        real = fetch_group_name_from_page(page, url)
        done += 1
        if real:
            g["name"] = real
            print(f"  [{done}/{len(need)}] ✓ {real[:70]}", flush=True)
        else:
            print(f"  [{done}/{len(need)}] ✗ ยังเป็น {g.get('name')}", flush=True)
        time.sleep(0.4)
    return groups


def load_existing() -> list[dict]:
    if not OUT_JSON.exists():
        return []
    raw = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    groups = raw.get("groups") if isinstance(raw, dict) else raw
    return list(groups or [])


def merge_preserve_tags(scraped: list[dict], existing: list[dict]) -> list[dict]:
    by_url = {g.get("url"): g for g in existing if g.get("url")}
    out = []
    for g in scraped:
        old = by_url.get(g["url"]) or {}
        merged = dict(g)
        for key in ("zone_tags", "offer_tags", "price_band", "notes"):
            if old.get(key):
                merged[key] = old[key]
        # keep better name if scrape still placeholder
        if is_placeholder_name(merged.get("name") or "") and old.get("name") and not is_placeholder_name(old["name"]):
            merged["name"] = old["name"]
        out.append(merged)
    return out


def save(groups: list[dict]) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(
            {"count": len(groups), "source": "facebook_groups_joins", "groups": groups},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["name", "url", "zone_tags", "offer_tags", "price_band", "notes"],
        )
        w.writeheader()
        for g in groups:
            w.writerow(
                {
                    "name": g.get("name") or "",
                    "url": g.get("url") or "",
                    "zone_tags": ",".join(g.get("zone_tags") or []),
                    "offer_tags": ",".join(g.get("offer_tags") or []),
                    "price_band": g.get("price_band") or "",
                    "notes": g.get("notes") or "",
                }
            )
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_CSV}")


def wait_until_logged_in(page, timeout_s: int = 300) -> None:
    print(f"รอให้คุณล็อกอินในหน้าต่าง Chromium (สูงสุด {timeout_s // 60} นาที)…")
    page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        cookies = page.context.cookies()
        if any(c.get("name") == "c_user" for c in cookies):
            if page.locator('input[name="email"]').count() == 0 or page.locator('input[name="pass"]').count() == 0:
                print("ตรวจพบ session แล้ว")
                time.sleep(1.5)
                return
            page.goto("https://www.facebook.com/", wait_until="domcontentloaded")
            time.sleep(2)
            if any(c.get("name") == "c_user" for c in page.context.cookies()):
                if page.locator('input[name="pass"]').count() == 0:
                    print("ตรวจพบ session แล้ว")
                    return
        time.sleep(3)
        left = int(deadline - time.time())
        if left % 15 < 3:
            print(f"  …ยังรอ login ({left}s)")
    raise SystemExit("หมดเวลารอ login — รันใหม่แล้ว login ให้ทัน")


def merge_by_url(base: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge incoming into base by URL — keep existing tags/notes, prefer better name."""
    by_url = {g.get("url"): dict(g) for g in base if g.get("url")}
    for g in incoming:
        url = g.get("url")
        if not url:
            continue
        if url not in by_url:
            by_url[url] = dict(g)
            continue
        old = by_url[url]
        merged = dict(old)
        # prefer real name over placeholder
        if is_placeholder_name(old.get("name") or "") and not is_placeholder_name(g.get("name") or ""):
            merged["name"] = g["name"]
        elif not is_placeholder_name(g.get("name") or "") and len(g.get("name") or "") > len(old.get("name") or ""):
            merged["name"] = g["name"]
        for key in ("zone_tags", "offer_tags"):
            if g.get(key) and not old.get(key):
                merged[key] = g[key]
        if g.get("notes") and not old.get("notes"):
            merged["notes"] = g["notes"]
        # mark source account if provided
        if g.get("source_account"):
            merged["source_account"] = g["source_account"]
        by_url[url] = merged
    return sorted(by_url.values(), key=lambda x: (x.get("name") or "").lower())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Facebook groups (optionally from a second account, RE-only)"
    )
    parser.add_argument(
        "--enrich-names",
        action="store_true",
        help="Only resolve placeholder Group <id> names from existing JSON",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max groups to enrich (0=all)")
    parser.add_argument(
        "--account",
        choices=["main", "alt"],
        default="main",
        help="main=cookies/facebook_session · alt=cookies/facebook_session_alt (เฟสอีกบัญชี)",
    )
    parser.add_argument(
        "--real-estate-only",
        action="store_true",
        help="Keep only groups that look like property / condo / rent-sale",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge into existing facebook_groups.json (by URL)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace facebook_groups.json entirely with this scrape",
    )
    args = parser.parse_args()

    session_name = "facebook_session" if args.account == "main" else "facebook_session_alt"
    user_data = COOKIES_DIR / session_name
    user_data.mkdir(parents=True, exist_ok=True)

    # default: alt account → real-estate filter + merge (safe for second FB)
    real_estate_only = args.real_estate_only or args.account == "alt"
    do_merge = args.merge or (args.account == "alt" and not args.replace)
    if args.replace:
        do_merge = False

    print(f"เปิด Chromium… (โปรไฟล์: cookies/{session_name})")
    if args.account == "alt":
        print("→ บัญชีนี้แยกจากเฟสหลัก · ล็อกอินเฟสอีกอันในหน้าต่างที่เปิด")
    if real_estate_only:
        print("→ จะคัดเฉพาะกลุ่มที่เกี่ยวกับอสังหา/คอนโด/เช่า-ขาย")
    if do_merge:
        print("→ รวมเข้าสมุดกลุ่มเดิม (ไม่ซ้ำ URL)")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="th-TH",
            timezone_id="Asia/Bangkok",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            if not is_logged_in(page):
                print("\nยังไม่ล็อกอิน Facebook ในหน้าต่างนี้")
                print("→ Login ให้ครบในหน้าต่าง Chromium ที่เปิดขึ้น (รวม 2FA)")
                wait_until_logged_in(page, timeout_s=480)

            if args.enrich_names:
                groups = load_existing()
                if not groups:
                    raise SystemExit("ไม่พบ data/facebook_groups.json — รัน scrape เต็มก่อน")
                print(f"โหลด {len(groups)} กลุ่ม · เติมชื่อที่ขาด…")
                groups = enrich_names(page, groups, limit=args.limit)
            else:
                print("ล็อกอินแล้ว · กำลังดึงกลุ่มจากหน้า joins…")
                groups = scrape(page)
                if len(groups) < 3:
                    print("เจอน้อย — เลื่อนต่อ…")
                    page.goto(GROUPS_URL, wait_until="domcontentloaded")
                    time.sleep(5)
                    for _ in range(20):
                        page.mouse.wheel(0, 2000)
                        time.sleep(1)
                    groups = scrape(page, max_scrolls=60)

                for g in groups:
                    g["source_account"] = args.account

                missing = sum(1 for g in groups if is_placeholder_name(g.get("name") or ""))
                if missing:
                    print(f"\nยังไม่มีชื่อจริง {missing} กลุ่ม — เปิดหน้ากลุ่มทีละอันเพื่อดึงชื่อ…")
                    groups = enrich_names(page, groups, limit=args.limit)

            # tag
            try:
                sys.path.insert(0, str(BASE_DIR))
                from src.hub.group_store import auto_tag_group, filter_real_estate_groups

                groups = [auto_tag_group(g, force=True) for g in groups]
                if real_estate_only:
                    kept, dropped = filter_real_estate_groups(groups)
                    print(f"\nคัดอสังหา: เหลือ {len(kept)} · ตัดทิ้ง {len(dropped)}")
                    if dropped[:15]:
                        print("ตัวอย่างที่ตัด (ไม่ใช่อสังหา):")
                        for g in dropped[:15]:
                            print(f"  × {g.get('name')}")
                    groups = kept
            except Exception as exc:
                print(f"(ข้าม filter/retag: {exc})")

            # snapshot of this account scrape
            if args.account == "alt":
                OUT_ALT_JSON.write_text(
                    json.dumps(
                        {
                            "count": len(groups),
                            "source": "facebook_groups_joins_alt",
                            "account": "alt",
                            "real_estate_only": real_estate_only,
                            "groups": groups,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                print(f"Wrote snapshot {OUT_ALT_JSON}")

            if do_merge:
                existing = load_existing()
                before = len(existing)
                groups = merge_by_url(existing, groups)
                print(f"รวมสมุดกลุ่ม: เดิม {before} → ตอนนี้ {len(groups)}")
            elif not args.replace and args.account == "main" and not args.enrich_names:
                groups = merge_preserve_tags(groups, load_existing())

            save(groups)
            named = sum(1 for g in groups if not is_placeholder_name(g.get("name") or ""))
            print(f"\nสำเร็จ · สมุดกลุ่ม {len(groups)} กลุ่ม · มีชื่อจริง {named}")
            for g in groups[:25]:
                print(f"  - {g['name']}")
            if len(groups) > 25:
                print(f"  … อีก {len(groups) - 25} กลุ่ม")
        finally:
            context.close()


if __name__ == "__main__":
    main()
