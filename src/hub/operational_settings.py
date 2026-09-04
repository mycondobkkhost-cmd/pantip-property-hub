"""Internal operational settings — validation, audit log, production write gate."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.hub.recheck_capacity import load_capacity_config, save_capacity_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _audit_dir() -> Path:
    root = (os.environ.get("PANTIP_OPERATIONAL_STATE_ROOT") or "").strip()
    if root:
        return Path(root) / "operational_settings_audit"
    return BASE_DIR / ".local" / "operational_settings_audit"


def _audit_path() -> Path:
    return _audit_dir() / "audit.jsonl"


_AUDIT_LOCK = threading.RLock()
_SETTINGS_LOCK = threading.RLock()

# Canonical setting keys exposed to internal back-office UI / API.
SETTING_KEYS = (
    "rent_recheck_threshold_days",
    "sale_recheck_threshold_days",
    "new_batch_per_day",
    "max_total_active",
    "max_active_per_operator",
    "contact_cooldown_days",
)

_TO_CAPACITY = {
    "rent_recheck_threshold_days": "rent_recheck_threshold_days",
    "sale_recheck_threshold_days": "sale_recheck_threshold_days",
    "new_batch_per_day": "max_new_rechecks_per_day",
    "max_total_active": "max_total_active_rechecks",
    "max_active_per_operator": "max_active_rechecks_per_operator",
    "contact_cooldown_days": "minimum_days_between_owner_contacts",
}

_FROM_CAPACITY = {v: k for k, v in _TO_CAPACITY.items()}

# Integer bounds — reject out-of-range instead of silent coercion.
SETTING_BOUNDS: dict[str, tuple[int, int]] = {
    "rent_recheck_threshold_days": (30, 730),
    "sale_recheck_threshold_days": (30, 1095),
    "new_batch_per_day": (1, 200),
    "max_total_active": (1, 500),
    "max_active_per_operator": (1, 100),
    "contact_cooldown_days": (0, 90),
}

PRODUCTION_WRITE_ENV = "OPERATIONAL_SETTINGS_PRODUCTION_WRITE"


def is_production_host() -> bool:
    import os

    fly = (os.environ.get("FLY_APP_NAME") or "").strip()
    if fly:
        return True
    cloud = (os.environ.get("HUB_CLOUD_HOST") or "").strip().lower()
    return cloud in {"1", "true", "yes", "on"}


def production_write_enabled() -> bool:
    """Production settings writes require explicit env flag (default OFF)."""
    raw = (os.environ.get(PRODUCTION_WRITE_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def can_write_operational_settings() -> dict[str, Any]:
    """Return whether settings mutation is allowed and why."""
    if is_production_host():
        if production_write_enabled():
            return {"allowed": True, "mode": "production_explicit", "test_only": False}
        return {
            "allowed": False,
            "mode": "production_read_only",
            "test_only": False,
            "reason": f"{PRODUCTION_WRITE_ENV} is not enabled",
        }
    return {"allowed": True, "mode": "local_test", "test_only": True}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _append_audit(entry: dict[str, Any]) -> None:
    path = _audit_path()
    audit_dir = _audit_dir()
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _AUDIT_LOCK:
        audit_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)


def list_settings_audit(*, limit: int = 50) -> list[dict[str, Any]]:
    path = _audit_path()
    if not path.exists():
        return []
    with _AUDIT_LOCK:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    out: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def validate_setting_value(key: str, value: Any) -> int:
    if key not in SETTING_BOUNDS:
        raise ValueError(f"unknown setting: {key}")
    if isinstance(value, bool):
        raise ValueError(f"{key} must be integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{key} must be integer")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be integer") from exc
    lo, hi = SETTING_BOUNDS[key]
    if n < lo or n > hi:
        raise ValueError(f"{key} must be between {lo} and {hi}")
    return n


def validate_settings_payload(fields: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in fields.items():
        if key in ("ok", "reason", "comment", "source"):
            continue
        if value is None:
            continue
        if key not in SETTING_KEYS:
            raise ValueError(f"unknown setting: {key}")
        out[key] = validate_setting_value(key, value)
    return out


def load_operational_settings() -> dict[str, Any]:
    cfg = load_capacity_config()
    gate = can_write_operational_settings()
    out: dict[str, Any] = {
        "test_only": gate.get("test_only", True),
        "policy_status": cfg.get("policy_status") or "POLICY_CANDIDATE",
        "write_allowed": gate.get("allowed", False),
        "write_mode": gate.get("mode"),
        "production_write_env": PRODUCTION_WRITE_ENV,
        "production_write_enabled": production_write_enabled(),
    }
    for api_key, cap_key in _TO_CAPACITY.items():
        out[api_key] = cfg.get(cap_key)
    out["bounds"] = {k: {"min": v[0], "max": v[1]} for k, v in SETTING_BOUNDS.items()}
    return out


def save_operational_settings(
    *,
    operator_id: str = "",
    reason: str = "",
    source: str = "api",
    **fields: Any,
) -> dict[str, Any]:
    gate = can_write_operational_settings()
    if not gate.get("allowed"):
        raise PermissionError(gate.get("reason") or "operational settings writes disabled")

    validated = validate_settings_payload(fields)
    if not validated:
        raise ValueError("no valid settings fields to save")

    old = load_operational_settings()
    mapped: dict[str, Any] = {}
    for api_key, value in validated.items():
        cap_key = _TO_CAPACITY[api_key]
        mapped[cap_key] = value
    with _SETTINGS_LOCK:
        save_capacity_config(**mapped)
        new = load_operational_settings()
        changed_keys = [k for k in validated if old.get(k) != new.get(k)]
        if changed_keys:
            _append_audit(
                {
                    "timestamp": _now_iso(),
                    "operator_id": operator_id or "unknown",
                    "source": source,
                    "reason": (reason or "")[:500],
                    "changed_keys": changed_keys,
                    "old_values": {k: old.get(k) for k in changed_keys},
                    "new_values": {k: new.get(k) for k in changed_keys},
                    "write_mode": gate.get("mode"),
                }
            )
    return new


def build_settings_api_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "settings": load_operational_settings(),
        "audit_recent": list_settings_audit(limit=10),
        "write_gate": can_write_operational_settings(),
    }


# Backward-compatible path for tests
def audit_path() -> Path:
    return _audit_path()
