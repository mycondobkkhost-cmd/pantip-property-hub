"""Administrative geography adapter — Phase Z1 foundation (design only).

No official polygon source is imported locally. Adapter is fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ADMIN_POLYGON_DATA_MISSING = "ADMIN_POLYGON_DATA_MISSING"


@dataclass
class AdminGeographyResult:
    province: str | None
    district: str | None
    subdistrict: str | None
    source: str
    confidence: str
    status: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "province": self.province,
            "district": self.district,
            "subdistrict": self.subdistrict,
            "source": self.source,
            "confidence": self.confidence,
            "status": self.status,
            "notes": self.notes,
        }


def resolve_admin_geography(latitude: float, longitude: float) -> AdminGeographyResult:
    """Resolve admin geography from coordinates.

    Official polygon data is not available locally — returns missing status.
    """
    _ = latitude, longitude
    return AdminGeographyResult(
        province=None,
        district=None,
        subdistrict=None,
        source="none",
        confidence="NONE",
        status=ADMIN_POLYGON_DATA_MISSING,
        notes="Official admin polygon source not loaded — adapter reserved for future import",
    )
