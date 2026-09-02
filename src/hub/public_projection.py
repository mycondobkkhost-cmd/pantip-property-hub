"""Explicit allowlists for public catalog surfaces — never expose raw property objects."""

from __future__ import annotations

from typing import Any

# Fields required for Hub table / Co-Agent / search (no owner contact or internal ops).
PUBLIC_PROPERTY_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "code",
        "code_prefix",
        "project_id",
        "project_name",
        "listing_kind",
        "property_type",
        "bedrooms",
        "size_sqm",
        "floor",
        "rent_price",
        "sale_price",
        "last_listed_at",
        "import_status",
        "media_status",
        "location_ref",
        "transit_from_sheet",
        "post_url",
        "post_pages_url",
        "source_url",
        "duplicate_flags",
        "sheet_row",
        "data_source",
        "pet_friendly",
    }
)

PUBLIC_PROJECT_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "canonical_name",
        "bucket_key",
        "aliases",
        "transit_verified",
        "transit_unverified",
        "zone_verified",
        "location_status",
        "is_thru_thonglor",
        "listing_count",
    }
)

# Must never appear on public surfaces regardless of key naming drift.
PRIVATE_DENY_SUBSTRINGS: tuple[str, ...] = (
    "note",
    "owner",
    "phone",
    "email",
    "line_id",
    "line_user",
    "tenant",
    "customer",
    "password",
    "token",
    "cookie",
    "secret",
    "crm",
    "page_post_text",
    "text_th",
    "text_en",
    "hub_edited_at",
    "internal",
)

INTERNAL_PROPERTY_KEYS: frozenset[str] = frozenset(
    {
        "notes",
        "page_post_text",
        "text_th",
        "text_en",
        "owner_facebook",
        "hub_edited_at",
        "caption_history",
        "private",
    }
)


def _is_private_key(key: str) -> bool:
    low = str(key or "").lower()
    if low in INTERNAL_PROPERTY_KEYS:
        return True
    return any(part in low for part in PRIVATE_DENY_SUBSTRINGS)


def public_property(prop: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(prop, dict):
        return {}
    out: dict[str, Any] = {}
    for key in PUBLIC_PROPERTY_KEYS:
        if key in prop:
            out[key] = prop[key]
    return out


def internal_property(prop: dict[str, Any]) -> dict[str, Any]:
    """Full property for authenticated Hub admin APIs."""
    if not isinstance(prop, dict):
        return {}
    return dict(prop)


def public_project(proj: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(proj, dict):
        return {}
    return {k: proj[k] for k in PUBLIC_PROJECT_KEYS if k in proj}


def assert_public_property_safe(prop: dict[str, Any]) -> list[str]:
    """Return list of private keys that leaked into a public projection."""
    if not isinstance(prop, dict):
        return []
    leaked: list[str] = []
    for key in prop:
        if _is_private_key(key):
            leaked.append(key)
    return leaked


def build_public_catalog_payload(
    projects: list[dict],
    properties: list[dict],
    *,
    stats: dict | None = None,
    generated_at: str = "",
    data_version: str = "",
) -> dict[str, Any]:
    pub_projects = [public_project(p) for p in projects if isinstance(p, dict)]
    pub_properties = [public_property(p) for p in properties if isinstance(p, dict)]
    return {
        "projects": pub_projects,
        "properties": pub_properties,
        "stats": stats or {},
        "generated_at": generated_at,
        "data_version": data_version,
        "catalog_scope": "public",
    }


def build_internal_catalog_payload(
    projects: list[dict],
    properties: list[dict],
    *,
    stats: dict | None = None,
    generated_at: str = "",
    data_version: str = "",
) -> dict[str, Any]:
    return {
        "projects": [dict(p) for p in projects if isinstance(p, dict)],
        "properties": [dict(p) for p in properties if isinstance(p, dict)],
        "stats": stats or {},
        "generated_at": generated_at,
        "data_version": data_version,
        "catalog_scope": "internal",
    }
