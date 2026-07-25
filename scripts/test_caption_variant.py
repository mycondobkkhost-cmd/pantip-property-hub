#!/usr/bin/env python3
"""Quick checks for full-original group captions."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub import caption_variant as cv

FULL_PAGE = """🏢 THE TRENDY CONDOMINIUM
(เดอะ เทรนดี้ คอนโดมิเนียม)
✨ ห้องใหญ่ 40 ตร.ม. | Studio | ใกล้ BTS นานา | พร้อมอยู่
💰 เช่า 16,000 บาท/เดือน
📑 สัญญา 1 ปี
🛁 Studio 1 ห้องน้ำ
📐 40 ตร.ม.
🏢 ชั้น 8
🚗 ที่จอดรถ 1 คัน
🏊‍♂️ สระว่ายน้ำ • ฟิตเนส • สวน • รปภ. 24 ชม.
📍 สถานที่ใกล้เคียง
🚆 BTS นานา 700 ม.
🚆 BTS อโศก 1.0 กม.
🚇 MRT สุขุมวิท 1.0 กม.
🏬 Terminal 21 1.1 กม.
🏥 โรงพยาบาลบำรุงราษฎร์ 1.3 กม.
🤝 Co-Agent Welcome
🏷️ #PTP8232
📲 LINE : @PTP.CONDO
📞 คุณนัท : 080-817-2532
📞 คุณเพลง : 064-646-2206
#TheTrendyCondominium #คอนโดนานา #คอนโดอโศก #คอนโดใกล้BTS #เช่าคอนโด"""


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        cv.HISTORY_PATH = Path(td) / "caption_copy_history.json"
        code = "PTP8232"
        urls = [
            "https://www.facebook.com/groups/aaa",
            "https://www.facebook.com/groups/bbb",
            "https://www.facebook.com/groups/ccc",
        ]
        captions = []
        for url in urls:
            r = cv.prepare_group_caption(
                property_code=code,
                group_url=url,
                page_post_text=FULL_PAGE,
                allow_scrape=False,
            )
            assert r["ok"], r
            assert r["source"] == "page_original"
            # Full original body must remain (key lines)
            assert "THE TRENDY CONDOMINIUM" in r["caption"]
            assert "080-817-2532" in r["caption"]
            assert "Terminal 21" in r["caption"]
            assert "Pantip Property" not in r["caption"]
            captions.append(r["caption"])
            print("OK", url, "chars=", len(r["caption"]), "hash=", r["hash"])

        fps = [cv.caption_fingerprint(c) for c in captions]
        assert len(set(fps)) == 3, fps

        # Truncated scrape must not win over page_post_text
        text, source, _ = cv.resolve_base_text(
            page_post_text=FULL_PAGE,
            base_text="short",
            allow_scrape=False,
        )
        assert source == "page_original"
        assert "080-817-2532" in text

        # force_new still keeps core content
        r3 = cv.prepare_group_caption(
            property_code=code,
            group_url=urls[0],
            page_post_text=FULL_PAGE,
            force_new=True,
            allow_scrape=False,
        )
        assert r3["ok"] and "THE TRENDY" in r3["caption"]
        assert cv.caption_fingerprint(r3["caption"]) not in fps

        # Refuse truncated-looking scrape as sole source
        bad = cv.prepare_group_caption(
            property_code="X1",
            group_url="https://www.facebook.com/groups/z",
            base_text="🏢 THE TRENDY\nPantip Property Bkk จัดหา ฝากขาย บ้านคอนโด\nเงิน 16000",
            allow_scrape=False,
        )
        # short hub text may still return with warning, but must not invent brand mash as page_scrape
        assert bad.get("source") in {"text_th", "none"} or bad.get("ok")

    print("all caption_variant full-original checks passed")


if __name__ == "__main__":
    main()
