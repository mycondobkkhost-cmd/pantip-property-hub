"""Selective RealXtate export projection — local dry-run only (no network)."""

from __future__ import annotations

from typing import Any

from src.hub.source_reference import derive_public_listing_url

EXPORT_SCHEMA = "pantip_realxtate_export/v1"
SOURCE_SYSTEM = "pantip_property"

# Explicit allowlist for future RealXtate publish payload.
EXPORT_ALLOWLIST = (
    "export_schema_version",
    "source_system",
    "source_property_id",
    "property_code",
    "project_id",
    "project_name",
    "property_type",
    "bedrooms",
    "size_sqm",
    "rent_price",
    "sale_price",
    "public_description_th",
    "public_description_en",
    "public_listing_url",
    "zones",
    "transit",
    "listing_status",
    "last_listed_at",
    "image_urls",
)

# Never export these internal fields.
FORBIDDEN_EXPORT_FIELDS = frozenset(
    {
        "source_url",
        "notes",
        "owner_phones",
        "owner_lines",
        "owner_facebook",
        "owner_name",
        "raw_text",
        "page_post_text",
        "hub_edited_at",
        "contact_history",
        "tenant",
        "customer",
        "queue_state",
        "recheck_status",
        "policy_evidence",
        "credentials",
    }
)


def _safe_images(prop: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for key in ("image_urls", "gallery_urls", "thumb_url"):
        val = prop.get(key)
        if isinstance(val, str) and val.strip().startswith("http"):
            urls.append(val.strip())
        elif isinstance(val, list):
            for u in val:
                s = str(u or "").strip()
                if s.startswith("http"):
                    urls.append(s)
    return urls[:20]


def evaluate_export_eligibility(prop: dict[str, Any], proj: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return eligibility verdict without mutating source."""
    proj = proj or {}
    errors: list[str] = []
    pid = str(prop.get("id") or "").strip()
    if not pid:
        errors.append("missing_property_id")
    code = str(prop.get("code") or "").strip()
    if not code:
        errors.append("missing_property_code")
    project_id = str(prop.get("project_id") or proj.get("id") or "").strip()
    if not project_id:
        errors.append("missing_project_id")
    rent = str(prop.get("rent_price") or "").strip()
    sale = str(prop.get("sale_price") or "").strip()
    if not rent and not sale:
        errors.append("missing_price")
    pub_url = derive_public_listing_url(prop)
    if not pub_url:
        errors.append("missing_public_listing_url")
    return {
        "eligible": not errors,
        "errors": errors,
        "source_property_id": pid,
    }


def project_realxtate_export(prop: dict[str, Any], proj: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build allowlisted export object. Never mutates source. No network."""
    proj = proj or {}
    eligibility = evaluate_export_eligibility(prop, proj)
    pub_url = derive_public_listing_url(prop)
    zones = prop.get("zones") or proj.get("zone_verified") or []
    if isinstance(zones, str):
        zones = [z.strip() for z in zones.split(",") if z.strip()]
    transit = prop.get("transit_from_sheet") or proj.get("transit_verified") or []
    out: dict[str, Any] = {
        "export_schema_version": EXPORT_SCHEMA,
        "source_system": SOURCE_SYSTEM,
        "source_property_id": str(prop.get("id") or ""),
        "property_code": str(prop.get("code") or ""),
        "project_id": str(prop.get("project_id") or proj.get("id") or ""),
        "project_name": str(prop.get("project_name") or proj.get("canonical_name") or ""),
        "property_type": str(prop.get("property_type") or ""),
        "bedrooms": str(prop.get("bedrooms") or ""),
        "size_sqm": str(prop.get("size_sqm") or ""),
        "rent_price": str(prop.get("rent_price") or ""),
        "sale_price": str(prop.get("sale_price") or ""),
        "public_description_th": str(prop.get("text_th") or ""),
        "public_description_en": str(prop.get("text_en") or ""),
        "public_listing_url": pub_url,
        "zones": list(zones)[:8],
        "transit": list(transit)[:8],
        "listing_status": str(prop.get("import_status") or "active"),
        "last_listed_at": str(prop.get("last_listed_at") or ""),
        "image_urls": _safe_images(prop),
        "_eligibility": eligibility,
    }
    # Enforce allowlist keys only in exported payload (except internal _eligibility for dry-run).
    return {k: out[k] for k in EXPORT_ALLOWLIST if k in out} | {"_eligibility": eligibility}


def assert_export_private_safe(export_obj: dict[str, Any]) -> list[str]:
    """Return leaked forbidden keys if any."""
    leaked = [k for k in export_obj if k in FORBIDDEN_EXPORT_FIELDS]
    extra = [k for k in export_obj if k not in EXPORT_ALLOWLIST and not k.startswith("_")]
    return leaked + extra


def idempotency_key(prop: dict[str, Any]) -> dict[str, str]:
    """Future cross-system idempotency design (dry-run documentation helper)."""
    return {
        "source_system": SOURCE_SYSTEM,
        "source_property_id": str(prop.get("id") or ""),
        "export_schema_version": EXPORT_SCHEMA,
    }
