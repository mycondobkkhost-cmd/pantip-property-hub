#!/usr/bin/env python3
"""Quick checks for unique group captions."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hub import caption_variant as cv


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        cv.HISTORY_PATH = Path(td) / "caption_copy_history.json"
        base = (
            "คอนโดให้เช่า พร้อมอยู่\n\n"
            "• 1 Bed 1 Bath\n"
            "• ใกล้ BTS\n\n"
            "ราคา 25,000 บาท/เดือน"
        )
        code = "RXTTEST1"
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
                group_name=url,
                base_text=base,
                allow_scrape=False,
            )
            assert r["ok"], r
            captions.append(r["caption"])
            print("OK", url, "hash=", r["hash"], "variant=", r["variant_index"])

        fps = [cv.caption_fingerprint(c) for c in captions]
        assert len(set(fps)) == 3, fps

        # same group within reuse window → same caption
        r2 = cv.prepare_group_caption(
            property_code=code,
            group_url=urls[0],
            base_text=base,
            allow_scrape=False,
        )
        assert r2["reused"] is True
        assert r2["caption"] == captions[0]

        # force new on same group → different fingerprint
        r3 = cv.prepare_group_caption(
            property_code=code,
            group_url=urls[0],
            base_text=base,
            force_new=True,
            allow_scrape=False,
        )
        assert r3["ok"] and not r3["reused"]
        assert cv.caption_fingerprint(r3["caption"]) not in fps
        print("force_new OK", r3["hash"])

    print("all caption_variant checks passed")


if __name__ == "__main__":
    main()
