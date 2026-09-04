"""Internal operational settings — editable recheck / follow-up pilot config (TEST_ONLY)."""

from __future__ import annotations

from typing import Any

from src.hub.recheck_capacity import load_capacity_config, save_capacity_config

# Canonical setting keys exposed to internal back-office UI / API.
SETTING_KEYS = (
    "rent_recheck_threshold_days",
    "sale_recheck_threshold_days",
    "new_batch_per_day",
    "max_total_active",
    "max_active_per_operator",
    "contact_cooldown_days",
)

# Map API keys → recheck_capacity config keys.
_TO_CAPACITY = {
    "rent_recheck_threshold_days": "rent_recheck_threshold_days",
    "sale_recheck_threshold_days": "sale_recheck_threshold_days",
    "new_batch_per_day": "max_new_rechecks_per_day",
    "max_total_active": "max_total_active_rechecks",
    "max_active_per_operator": "max_active_rechecks_per_operator",
    "contact_cooldown_days": "minimum_days_between_owner_contacts",
}

_FROM_CAPACITY = {v: k for k, v in _TO_CAPACITY.items()}


def load_operational_settings() -> dict[str, Any]:
    cfg = load_capacity_config()
    out: dict[str, Any] = {
        "test_only": True,
        "policy_status": cfg.get("policy_status") or "POLICY_CANDIDATE",
    }
    for api_key, cap_key in _TO_CAPACITY.items():
        out[api_key] = cfg.get(cap_key)
    return out


def save_operational_settings(**fields: Any) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for api_key, value in fields.items():
        if value is None:
            continue
        cap_key = _TO_CAPACITY.get(api_key)
        if cap_key:
            mapped[cap_key] = value
    if mapped:
        save_capacity_config(**mapped)
    return load_operational_settings()


def build_settings_api_payload() -> dict[str, Any]:
    return {"ok": True, "settings": load_operational_settings()}
