"""Map embed coordinate extraction — Phase Z2."""

from __future__ import annotations

import re
from typing import Any

from src.hub.coordinate_sources.base import LOCATION_ROLE_UNKNOWN


def extract_map_embed_coordinates(html: str) -> list[dict[str, Any]]:
    """Extract coordinates from common map embed URL patterns."""
    results: list[dict[str, Any]] = []
    patterns = [
        r"google\.com/maps[^\"']*@([0-9.]+),([0-9.]+)",
        r"google\.com/maps\?[^\"']*q=([0-9.]+),([0-9.]+)",
        r"center=([0-9.]+)%2C([0-9.]+)",
        r"maps\.google\.com[^\"']*ll=([0-9.]+),([0-9.]+)",
        r"pb=![0-9]+!3d([0-9.]+)!4d([0-9.]+)",
    ]
    for pat in patterns:
        for lat_s, lng_s in re.findall(pat, html, re.I):
            try:
                lat_f, lng_f = float(lat_s), float(lng_s)
            except ValueError:
                continue
            if 5.0 <= lat_f <= 21.0 and 97.0 <= lng_f <= 106.0:
                results.append(
                    {
                        "latitude": lat_f,
                        "longitude": lng_f,
                        "context_type": "",
                        "extraction_method": "map_embed_url",
                        "location_role": LOCATION_ROLE_UNKNOWN,
                    }
                )
    return results
