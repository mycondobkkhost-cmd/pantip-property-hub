#!/usr/bin/env python3
"""Phase B public data boundary tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


SYNTHETIC_PROP = {
    "id": "pub-1",
    "code": "RXT9001",
    "project_id": "p1",
    "project_name": "Sample Condo",
    "rent_price": "18000",
    "import_status": "active",
    "post_url": "https://www.facebook.com/example/post",
    "notes": "private owner note",
    "owner_facebook": "https://facebook.com/owner-secret",
    "owner_phones": ["0812345678"],
    "owner_lines": ["line-secret"],
    "page_post_text": "internal caption draft",
    "hub_edited_at": "2026-01-01",
}


class PhaseBPublicTests(unittest.TestCase):
    def test_public_projection_excludes_private_fields(self) -> None:
        from src.hub.public_projection import assert_public_property_safe, public_property

        pub = public_property(SYNTHETIC_PROP)
        leaked = assert_public_property_safe(pub)
        self.assertEqual(leaked, [])
        for key in (
            "notes",
            "owner_facebook",
            "owner_phones",
            "owner_lines",
            "page_post_text",
            "hub_edited_at",
        ):
            self.assertNotIn(key, pub)
        self.assertIn("code", pub)
        self.assertIn("rent_price", pub)

    def test_preview_js_uses_public_projection_only(self) -> None:
        from src.hub import project_store as ps

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            data = base / "data"
            data.mkdir()
            props = [dict(SYNTHETIC_PROP)]
            projs = [{"id": "p1", "canonical_name": "Sample Condo", "bucket_key": "sample"}]
            with mock.patch.object(ps, "BASE_DIR", base), mock.patch.object(
                ps, "PROPERTIES_JSON", data / "properties.json"
            ), mock.patch.object(ps, "PROJECTS_JSON", data / "projects.json"), mock.patch.object(
                ps, "PREVIEW_JS", data / "preview-data.js"
            ), mock.patch.object(
                ps, "PREVIEW_META", data / "preview-data.meta.json"
            ), mock.patch.object(
                ps, "PREVIEW_JS_LEGACY", base / "hub" / "preview-data.js"
            ), mock.patch.object(
                ps, "PREVIEW_META_LEGACY", base / "hub" / "preview-data.meta.json"
            ), mock.patch.object(ps, "DB_PATH", data / "hub.db"):
                ps.write_preview_js(projs, props)
                body = (data / "preview-data.js").read_text(encoding="utf-8")
                payload = json.loads(body.split("=", 1)[1].strip().rstrip(";"))
                row = payload["properties"][0]
                self.assertEqual(payload.get("catalog_scope"), "public")
                self.assertNotIn("notes", row)
                self.assertNotIn("owner_facebook", row)
                self.assertNotIn("page_post_text", row)

    def test_co_catalog_keys_safe(self) -> None:
        from src.hub.co_catalog import _CO_ITEM_KEYS, slim_property

        row = slim_property(
            SYNTHETIC_PROP,
            {"id": "p1", "canonical_name": "Sample Condo"},
            require_page=True,
        )
        assert row is not None
        self.assertEqual(set(row.keys()), set(_CO_ITEM_KEYS))
        self.assertNotIn("notes", row)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PhaseBPublicTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
