#!/usr/bin/env python3
"""Phase H operator privilege + token exposure tests (offline)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PhaseHOperatorAuthTests(unittest.TestCase):
    def test_01_unauthenticated_rotate_blocked_by_require_operator(self) -> None:
        import scripts.hub_server as hub

        src = Path(hub.__file__).read_text(encoding="utf-8")
        self.assertIn("if path == \"/api/fb-agent/rotate-token\":", src)
        self.assertIn("_require_operator(self)", src)

    def test_02_ordinary_user_not_privileged(self) -> None:
        from src.hub.operator_auth import is_privileged_username

        users = {
            "alice": {"password": "x", "name": "A", "role": ""},
            "bob": {"password": "y", "name": "B", "role": "admin"},
        }
        self.assertFalse(
            is_privileged_username("alice", users=users, cloud_host=True, local_dev=False)
        )

    def test_03_privileged_operator_allowed(self) -> None:
        from src.hub.operator_auth import is_privileged_username

        users = {"bob": {"password": "y", "name": "B", "role": "admin"}}
        self.assertTrue(
            is_privileged_username("bob", users=users, cloud_host=True, local_dev=False)
        )

    def test_04_missing_admin_config_fail_closed_cloud(self) -> None:
        from src.hub.operator_auth import is_privileged_username

        users = {"alice": {"password": "x", "name": "A", "role": ""}}
        with mock.patch.dict(os.environ, {"HUB_ADMIN_USERS": "", "HUB_ADMIN_USERS_JSON": ""}, clear=False):
            self.assertFalse(
                is_privileged_username("alice", users=users, cloud_host=True, local_dev=False)
            )

    def test_05_status_never_includes_token(self) -> None:
        from src.hub import fb_agent_store as store
        import tempfile
        from pathlib import Path as P

        with tempfile.TemporaryDirectory() as td:
            path = P(td) / "fb.json"
            with mock.patch.object(store, "STORE_PATH", path):
                store.ensure_agents()
                store.rotate_agent_token()
                status = store.public_status(include_token=False)
                self.assertNotIn("agent_token", status)

    def test_06_hub_json_strips_token_by_default(self) -> None:
        import scripts.hub_server as hub

        src = Path(hub.__file__).read_text(encoding="utf-8")
        self.assertIn("allow_agent_token: bool = False", src)
        self.assertIn("strip_agent_tokens", src)

    def test_07_reconcile_requires_operator_in_hub(self) -> None:
        import scripts.hub_server as hub

        src = Path(hub.__file__).read_text(encoding="utf-8")
        self.assertIn('/api/groups/publish/reconcile', src)
        self.assertIn('/api/line/reconcile', src)
        # Both list and mutate call _require_operator
        self.assertGreaterEqual(src.count("_require_operator"), 4)

    def test_08_ordinary_user_blocked_when_admin_list_set(self) -> None:
        from src.hub.operator_auth import is_privileged_username

        with mock.patch.dict(os.environ, {"HUB_ADMIN_USERS": "owner"}, clear=False):
            self.assertFalse(
                is_privileged_username(
                    "ptp2",
                    users={"ptp2": {"password": "x", "role": ""}},
                    cloud_host=False,
                    local_dev=True,
                )
            )
            self.assertTrue(
                is_privileged_username(
                    "owner",
                    users={"owner": {"password": "x", "role": ""}},
                    cloud_host=False,
                    local_dev=True,
                )
            )

    def test_09_operator_allowed_via_admin_json(self) -> None:
        from src.hub.operator_auth import is_privileged_username

        with mock.patch.dict(
            os.environ,
            {"HUB_ADMIN_USERS_JSON": '["ops1"]', "HUB_ADMIN_USERS": ""},
            clear=False,
        ):
            self.assertTrue(
                is_privileged_username("ops1", users={}, cloud_host=True, local_dev=False)
            )

    def test_10_no_password_in_operator_module(self) -> None:
        from src.hub import operator_auth

        src = Path(operator_auth.__file__).read_text(encoding="utf-8")
        # Mentions passwords only to say they are not hard-coded
        self.assertIn("No production passwords", src)
        self.assertNotRegex(src, r'password\s*=\s*["\'][^"\']+["\']')

    def test_11_local_dev_only_primary_privileged(self) -> None:
        from src.hub.operator_auth import is_privileged_username

        with mock.patch.dict(os.environ, {"HUB_ADMIN_USERS": "", "HUB_ADMIN_USERS_JSON": ""}, clear=False):
            self.assertTrue(
                is_privileged_username("angkarn1996", users={}, cloud_host=False, local_dev=True)
            )
            self.assertFalse(
                is_privileged_username("ptp2", users={}, cloud_host=False, local_dev=True)
            )

    def test_12_no_hardcoded_production_admin(self) -> None:
        from src.hub import operator_auth
        import scripts.hub_server as hub

        for mod in (operator_auth, hub):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            self.assertNotIn("realxtate", src.lower())
            self.assertNotIn("@gmail.com", src.lower())

    def test_13_forbidden_response_generic(self) -> None:
        import scripts.hub_server as hub

        src = Path(hub.__file__).read_text(encoding="utf-8")
        self.assertIn("ไม่มีสิทธิ์ดำเนินการนี้", src)
        self.assertNotIn("HUB_ADMIN_USERS", src.split("ไม่มีสิทธิ์ดำเนินการนี้")[1][:200])

    def test_14_strip_agent_tokens_helper(self) -> None:
        from src.hub.operator_auth import strip_agent_tokens

        payload = {
            "ok": True,
            "agent_token": "SECRET",
            "agents": [{"id": "a", "agent_token": "SECRET2"}],
        }
        out = strip_agent_tokens(payload)
        self.assertNotIn("agent_token", out)
        self.assertNotIn("agent_token", out["agents"][0])
        dumped = json.dumps(out)
        self.assertNotIn("SECRET", dumped)

    def test_15_xff_not_trusted_by_default(self) -> None:
        import scripts.hub_server as hub

        class H:
            headers = {"X-Forwarded-For": "9.9.9.9"}
            client_address = ("10.0.0.5", 1)

        with mock.patch.dict(os.environ, {"HUB_TRUST_X_FORWARDED_FOR": ""}, clear=False):
            self.assertEqual(hub._client_ip(H()), "10.0.0.5")

    def test_16_xff_trusted_when_explicit(self) -> None:
        import scripts.hub_server as hub

        class H:
            headers = {"X-Forwarded-For": "9.9.9.9"}
            client_address = ("10.0.0.5", 1)

        with mock.patch.dict(os.environ, {"HUB_TRUST_X_FORWARDED_FOR": "1"}, clear=False):
            self.assertEqual(hub._client_ip(H()), "9.9.9.9")

    def test_17_query_token_rejected(self) -> None:
        import scripts.hub_server as hub

        src = Path(hub.__file__).read_text(encoding="utf-8")
        self.assertIn("do not accept agent tokens from query strings", src)
        self.assertNotIn('qs.get("t")', src)

    def test_18_login_rate_limit_still_present(self) -> None:
        from src.hub import login_rate_limit as lim

        lim.reset_all_for_tests()
        now = 1_700_000_000.0
        for _ in range(lim.MAX_FAILURES):
            lim.record_login_failure(ip="1.1.1.1", now=now)
        self.assertFalse(lim.check_login_allowed(ip="1.1.1.1", now=now + 1)["allowed"])
        lim.reset_all_for_tests()


if __name__ == "__main__":
    unittest.main()
