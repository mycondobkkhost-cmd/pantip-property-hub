"""Structured metadata coordinate extraction — JSON-LD GeoCoordinates etc."""

from __future__ import annotations

import json
import re
from typing import Any

from src.hub.coordinate_sources.base import (
    LOCATION_ROLE_DEVELOPER_HQ,
    LOCATION_ROLE_PROJECT_SITE,
    LOCATION_ROLE_SALES_OFFICE,
    LOCATION_ROLE_UNKNOWN,
)


def _valid(lat: float | None, lng: float | None) -> bool:
    if lat is None or lng is None:
        return False
    if lat == 0 and lng == 0:
        return False
    return 5.0 <= lat <= 21.0 and 97.0 <= lng <= 106.0


def infer_location_role(html: str, context_type: str = "") -> str:
    low = (html or "").lower()
    ctx = (context_type or "").lower()
    if any(k in low for k in ("sales gallery", "sales office", "ชูมการขาย", "sale office")):
        return LOCATION_ROLE_SALES_OFFICE
    if any(k in low for k in ("head office", "สำนักงานใหญ่", "corporate office", "developer hq")):
        return LOCATION_ROLE_DEVELOPER_HQ
    if ctx in {"place", "residence", "apartmentcomplex", "singlefamilyresidence"}:
        return LOCATION_ROLE_PROJECT_SITE
    if "living_project" in low or "real estate agent" in low or "realestateagent" in low:
        return LOCATION_ROLE_PROJECT_SITE
    return LOCATION_ROLE_UNKNOWN


def extract_jsonld_geo(html: str) -> list[dict[str, Any]]:
    """Extract GeoCoordinates from JSON-LD blocks."""
    results: list[dict[str, Any]] = []
    for match in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S | re.I):
        raw = match.group(1).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        for item in stack:
            _walk_jsonld(item, results)
    return results


def _walk_jsonld(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        geo = node.get("geo")
        ctx = str(node.get("@type") or "")
        if isinstance(geo, dict):
            lat = geo.get("latitude")
            lng = geo.get("longitude")
            try:
                lat_f, lng_f = float(lat), float(lng)
            except (TypeError, ValueError):
                lat_f, lng_f = None, None
            if _valid(lat_f, lng_f):
                out.append(
                    {
                        "latitude": lat_f,
                        "longitude": lng_f,
                        "context_type": ctx,
                        "extraction_method": "jsonld_geocoordinates",
                    }
                )
        lat = node.get("latitude")
        lng = node.get("longitude")
        if lat is not None and lng is not None:
            try:
                lat_f, lng_f = float(lat), float(lng)
            except (TypeError, ValueError):
                lat_f, lng_f = None, None
            if _valid(lat_f, lng_f):
                out.append(
                    {
                        "latitude": lat_f,
                        "longitude": lng_f,
                        "context_type": ctx,
                        "extraction_method": "jsonld_direct_latlng",
                    }
                )
        for v in node.values():
            _walk_jsonld(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_jsonld(item, out)


def extract_inline_latlng(html: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    lat_m = re.search(r'latitude["\']?\s*[:=]\s*([0-9.]+)', html, re.I)
    lng_m = re.search(r'longitude["\']?\s*[:=]\s*([0-9.]+)', html, re.I)
    if lat_m and lng_m:
        try:
            lat_f, lng_f = float(lat_m.group(1)), float(lng_m.group(1))
            if _valid(lat_f, lng_f):
                results.append(
                    {
                        "latitude": lat_f,
                        "longitude": lng_f,
                        "context_type": "",
                        "extraction_method": "inline_latlng_pair",
                    }
                )
        except ValueError:
            pass
    return results
