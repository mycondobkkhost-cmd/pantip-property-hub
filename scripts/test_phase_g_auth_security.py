#!/usr/bin/env python3
"""Phase G auth: login rate limit + fb-agent token exposure (offline)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class PhaseGAuthSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        from src.hub import login_rate_limit as lim

        self.lim = lim
        lim.reset_all_for_tests()

    def tearDown(self) -> None:
        self.lim.reset_all_for_tests()

    def test_01_status_endpoint_excludes_agent_token(self) -> None:
        from src.hub import fb_agent_store as store

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fb_agent.json"
            with mock.patch.object(store, "STORE_PATH", path):
                store.ensure_agents()
                status = store.public_status(include_token=False)
                self.assertNotIn("agent_token", status)
                blob = json.dumps(status)
                self.assertNotIn("agent_token", blob)

    def test_02_serialized_status_no_token_like_secret(self) -> None:
        from src.hub import fb_agent_store as store

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "fb_agent.json"
            with mock.patch.object(store, "STORE_PATH", path):
                store.ensure_agents()
                rotated = store.rotate_agent_token()
                self.assertIn("agent_token", rotated)
                token = rotated["agent_token"]
                status = store.public_status(include_token=False)
                dumped = json.dumps(status)
                self.assertNotIn(token, dumped)
                self.assertNotIn("agent_token", status)

    def test_03_hub_status_handler_uses_include_token_false(self) -> None:
        import scripts.hub_server as hub

        src = Path(hub.__file__).read_text(encoding="utf-8")
        # Status path must force include_token=False
        self.assertIn("include_token=False, agent_id=agent_id)", src)
        self.assertIn("Phase G: never return agent_token on status endpoint", src)

    def test_04_login_failures_rate_limited(self) -> None:
        now = time.time()
        for _ in range(self.lim.MAX_FAILURES):
            self.lim.record_login_failure(ip="1.2.3.4", now=now)
        gate = self.lim.check_login_allowed(ip="1.2.3.4", now=now + 1)
        self.assertFalse(gate["allowed"])
        self.assertGreater(gate["retry_after_sec"], 0)

    def test_05_successful_login_resets(self) -> None:
        now = time.time()
        for _ in range(self.lim.MAX_FAILURES - 1):
            self.lim.record_login_failure(ip="9.9.9.9", now=now)
        self.lim.record_login_success(ip="9.9.9.9", now=now)
        gate = self.lim.check_login_allowed(ip="9.9.9.9", now=now + 1)
        self.assertTrue(gate["allowed"])
        # After success, can fail again without immediate lock from old count
        for _ in range(self.lim.MAX_FAILURES - 1):
            self.lim.record_login_failure(ip="9.9.9.9", now=now + 2)
        gate2 = self.lim.check_login_allowed(ip="9.9.9.9", now=now + 3)
        self.assertTrue(gate2["allowed"])

    def test_06_password_never_in_rate_limit_api(self) -> None:
        # Module API accepts no password; ensure no accidental logging helpers.
        src = Path(self.lim.__file__).read_text(encoding="utf-8")
        self.assertNotIn("password", src.lower())

    def test_07_rate_limit_response_generic(self) -> None:
        import scripts.hub_server as hub

        src = Path(hub.__file__).read_text(encoding="utf-8")
        self.assertIn("ลองเข้าสู่ระบบบ่อยเกินไป", src)
        # Same 401 wording for missing/wrong user
        self.assertIn("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", src)

    def test_08_separate_ips_independent(self) -> None:
        now = time.time()
        for _ in range(self.lim.MAX_FAILURES):
            self.lim.record_login_failure(ip="10.0.0.1", now=now)
        self.assertFalse(self.lim.check_login_allowed(ip="10.0.0.1", now=now + 1)["allowed"])
        self.assertTrue(self.lim.check_login_allowed(ip="10.0.0.2", now=now + 1)["allowed"])

    def test_09_lockout_expiration(self) -> None:
        now = time.time()
        for _ in range(self.lim.MAX_FAILURES):
            self.lim.record_login_failure(ip="8.8.8.8", now=now)
        later = now + self.lim.LOCKOUT_SEC + 5
        self.assertTrue(self.lim.check_login_allowed(ip="8.8.8.8", now=later)["allowed"])

    def test_10_local_dev_gated(self) -> None:
        import scripts.hub_server as hub

        env = {
            k: v
            for k, v in os.environ.items()
            if k
            not in {
                "FLY_APP_NAME",
                "RENDER",
                "HUB_LOCAL_DEV",
                "HUB_ALLOW_DEMO_USERS",
                "HUB_USERS_JSON",
            }
        }
        with mock.patch.dict(os.environ, {**env, "HUB_USERS_JSON": ""}, clear=True):
            self.assertEqual(hub._load_hub_users(), {})
        with mock.patch.dict(
            os.environ, {**env, "HUB_USERS_JSON": "", "HUB_LOCAL_DEV": "1"}, clear=True
        ):
            self.assertIn("angkarn1996", hub._load_hub_users())

    def test_11_client_ip_prefers_fly_header(self) -> None:
        import scripts.hub_server as hub

        class H:
            headers = {"Fly-Client-IP": "203.0.113.9", "X-Forwarded-For": "1.1.1.1"}
            client_address = ("127.0.0.1", 1)

        self.assertEqual(hub._client_ip(H()), "203.0.113.9")

    def test_12_starter_download_no_embedded_token(self) -> None:
        import scripts.hub_server as hub

        src = Path(hub.__file__).read_text(encoding="utf-8")
        self.assertIn("do NOT embed agent_token", src)
        self.assertIn('token_placeholder = ""', src)


if __name__ == "__main__":
    unittest.main()
