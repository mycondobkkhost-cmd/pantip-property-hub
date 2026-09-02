#!/usr/bin/env python3
"""Phase A safety tests — auth fail-closed, duplicate codes, public catalog fields."""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PhaseASafetyTests(unittest.TestCase):
    def test_cloud_has_no_demo_users_without_json(self) -> None:
        import scripts.hub_server as hub

        with mock.patch.dict(
            os.environ,
            {"FLY_APP_NAME": "property-hub", "HUB_USERS_JSON": "", "HUB_LOCAL_DEV": "1"},
            clear=False,
        ):
            users = hub._load_hub_users()
        self.assertEqual(users, {})

    def test_local_demo_users_require_explicit_flag(self) -> None:
        import scripts.hub_server as hub

        env = {k: v for k, v in os.environ.items() if k not in {"FLY_APP_NAME", "RENDER", "HUB_LOCAL_DEV", "HUB_ALLOW_DEMO_USERS", "HUB_USERS_JSON"}}
        with mock.patch.dict(os.environ, {**env, "HUB_USERS_JSON": ""}, clear=True):
            self.assertEqual(hub._load_hub_users(), {})
        with mock.patch.dict(os.environ, {**env, "HUB_USERS_JSON": "", "HUB_LOCAL_DEV": "1"}, clear=True):
            users = hub._load_hub_users()
            self.assertIn("angkarn1996", users)

    def test_cloud_missing_session_secret_exits_at_startup(self) -> None:
        import scripts.hub_server as hub

        with mock.patch.dict(
            os.environ,
            {
                "FLY_APP_NAME": "property-hub",
                "HUB_USERS_JSON": '{"u":{"password":"x","name":"U"}}',
                "HUB_SESSION_SECRET": "",
            },
            clear=False,
        ):
            with self.assertRaises(SystemExit):
                hub._validate_production_auth_config()

    def test_duplicate_codes_do_not_silently_pick_first(self) -> None:
        from src.hub.publish_caption import find_property_by_code

        props = [
            {"id": "id-a", "code": "PTP9999", "project_id": "p1", "rent_price": "10000"},
            {"id": "id-b", "code": "PTP9999", "project_id": "p2", "rent_price": "20000"},
        ]
        with mock.patch("src.hub.publish_caption.load_properties_cached", return_value=props):
            found = find_property_by_code("PTP9999")
        self.assertIsNone(found)
        ids = {p["id"] for p in props}
        self.assertEqual(len(ids), 2)

    def test_property_ids_unique_in_fixture(self) -> None:
        props = [
            {"id": "a", "code": "PTP1"},
            {"id": "b", "code": "PTP1"},
        ]
        self.assertEqual(len({p["id"] for p in props}), 2)
        self.assertEqual(len({p["code"] for p in props}), 1)

    def test_co_catalog_slim_excludes_sensitive_fields(self) -> None:
        from src.hub.co_catalog import slim_property, _CO_ITEM_KEYS

        prop = {
            "id": "uuid-1",
            "code": "RXT0001",
            "project_id": "proj",
            "project_name": "Test Condo",
            "rent_price": "15000",
            "post_url": "https://www.facebook.com/example/post",
            "notes": "private note",
            "owner_facebook": "https://facebook.com/owner",
            "page_post_text": "long caption with phone",
        }
        proj = {"id": "proj", "canonical_name": "Test Condo"}
        row = slim_property(prop, proj, require_page=True)
        assert row is not None
        for sensitive in ("notes", "owner_facebook", "page_post_text", "id"):
            self.assertNotIn(sensitive, row)
        self.assertEqual(set(row.keys()), set(_CO_ITEM_KEYS))

    def test_preview_public_catalog_excludes_notes(self) -> None:
        from src.hub import project_store as ps

        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            data = base / "data"
            data.mkdir()
            props = [{"id": "1", "code": "RXT1", "notes": "x", "import_status": "active", "project_id": "p"}]
            projs = [{"id": "p", "canonical_name": "P", "bucket_key": "p"}]
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
                self.assertEqual(payload.get("catalog_scope"), "public")
                self.assertNotIn("notes", payload["properties"][0])


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PhaseASafetyTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
