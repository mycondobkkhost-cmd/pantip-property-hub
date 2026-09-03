#!/usr/bin/env python3
"""Minimal Hub operator/admin privilege boundary (Phase H).

Ordinary authenticated Hub users are NOT privileged by default.
Privileged operations (token rotate, reconciliation mutations) require an
explicit admin/operator designation.

Configuration (least disruptive):
1. Optional ``role`` on each HUB_USERS_JSON entry: ``admin`` / ``operator``
2. Optional ``HUB_ADMIN_USERS_JSON``: JSON list of usernames
3. Optional ``HUB_ADMIN_USERS``: comma-separated usernames

Missing admin configuration → fail closed (no privileged users).
Local demo: only when HUB_LOCAL_DEV=1, username ``angkarn1996`` is privileged.
No production passwords/tokens are hard-coded.
"""

from __future__ import annotations

import json
import os
from typing import Any


PRIVILEGED_ROLES = frozenset({"admin", "operator", "owner"})


def _parse_json_list(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [str(x).strip().lower() for x in data if str(x).strip()]
    return []


def admin_usernames_from_env() -> set[str]:
    names: set[str] = set(_parse_json_list(os.environ.get("HUB_ADMIN_USERS_JSON") or ""))
    csv = (os.environ.get("HUB_ADMIN_USERS") or "").strip()
    if csv:
        for part in csv.split(","):
            n = part.strip().lower()
            if n:
                names.add(n)
    return names


def role_from_user_record(record: dict[str, Any] | None) -> str:
    if not isinstance(record, dict):
        return ""
    return str(record.get("role") or record.get("privilege") or "").strip().lower()


def is_privileged_username(
    username: str,
    *,
    users: dict[str, Any] | None = None,
    cloud_host: bool = False,
    local_dev: bool = False,
) -> bool:
    """Return True only when username is explicitly designated privileged."""
    uname = (username or "").strip().lower()
    if not uname:
        return False

    # Explicit env allow-list always wins when present.
    env_admins = admin_usernames_from_env()
    if env_admins and uname in env_admins:
        return True

    if users and isinstance(users, dict):
        rec = users.get(uname)
        if isinstance(rec, dict) and role_from_user_record(rec) in PRIVILEGED_ROLES:
            return True
        # If env_admins was empty but roles exist in users, role check above is enough.
        # If neither env nor any role is configured, fail closed (except local demo).

    # Detect whether ANY privilege config exists.
    has_role_config = False
    if users and isinstance(users, dict):
        for rec in users.values():
            if isinstance(rec, dict) and role_from_user_record(rec) in PRIVILEGED_ROLES:
                has_role_config = True
                break
    has_any_config = bool(env_admins) or has_role_config

    if has_any_config:
        return False  # username not in allow-list / role

    # No privilege config at all.
    if cloud_host:
        return False  # fail closed in production

    # Local explicit demo: only the primary local account is operator.
    if local_dev and uname == "angkarn1996":
        return True
    return False


def strip_agent_tokens(payload: Any) -> Any:
    """Recursively remove agent_token fields from API payloads."""
    if isinstance(payload, dict):
        out = {}
        for k, v in payload.items():
            if k == "agent_token":
                continue
            out[k] = strip_agent_tokens(v)
        return out
    if isinstance(payload, list):
        return [strip_agent_tokens(x) for x in payload]
    return payload
