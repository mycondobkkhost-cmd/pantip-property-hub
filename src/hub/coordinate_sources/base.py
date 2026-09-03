"""Coordinate source adapter base — Phase Z2."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

LOCATION_ROLE_PROJECT_SITE = "PROJECT_SITE"
LOCATION_ROLE_SALES_OFFICE = "SALES_OFFICE"
LOCATION_ROLE_DEVELOPER_HQ = "DEVELOPER_HQ"
LOCATION_ROLE_UNKNOWN = "UNKNOWN_LOCATION_ROLE"

URL_OFFICIAL_PROJECT = "OFFICIAL_PROJECT"
URL_DEVELOPER = "DEVELOPER"
URL_PROPERTY_DIRECTORY = "PROPERTY_DIRECTORY"
URL_STRUCTURED_REFERENCE = "STRUCTURED_REFERENCE"
URL_UNKNOWN = "UNKNOWN"


@dataclass
class CoordinateCandidate:
    project_id: str
    latitude: float
    longitude: float
    provider: str
    source_url: str
    source_record_id: str
    extraction_method: str
    retrieved_at: str
    evidence_lineage_id: str
    tier: str
    confidence: str
    location_role: str = LOCATION_ROLE_PROJECT_SITE
    provider_upstream: str | None = None
    independence: str = "INDEPENDENT"
    raw_value_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "provider": self.provider,
            "source_url": self.source_url,
            "source_record_id": self.source_record_id,
            "extraction_method": self.extraction_method,
            "retrieved_at": self.retrieved_at,
            "evidence_lineage_id": self.evidence_lineage_id,
            "tier": self.tier,
            "confidence": self.confidence,
            "location_role": self.location_role,
            "provider_upstream": self.provider_upstream,
            "independence": self.independence,
            "raw_value_hash": self.raw_value_hash,
            "metadata": self.metadata,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def hash_coordinate(lat: float, lon: float) -> str:
    return hashlib.sha256(f"{lat:.8f},{lon:.8f}".encode()).hexdigest()


def classify_url(url: str) -> str:
    low = (url or "").lower()
    if "livinginsider.com" in low:
        return URL_PROPERTY_DIRECTORY
    if "propertyhub.in.th" in low:
        return URL_PROPERTY_DIRECTORY
    if "ddproperty" in low or "hipflat" in low or "dotproperty" in low:
        return URL_PROPERTY_DIRECTORY
    if any(x in low for x in (".co.th/project", "/projects/", "condo", "residence")):
        return URL_OFFICIAL_PROJECT
    if "developer" in low or "corporate" in low:
        return URL_DEVELOPER
    return URL_UNKNOWN
