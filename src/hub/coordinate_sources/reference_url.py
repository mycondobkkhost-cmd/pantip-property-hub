"""Reference URL fetch + coordinate extraction — Phase Z2.

Bounded, respectful public access only. No login, no CAPTCHA bypass.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Any

from src.hub.coordinate_sources.base import (
    CoordinateCandidate,
    LOCATION_ROLE_PROJECT_SITE,
    classify_url,
    hash_coordinate,
    utc_now_iso,
)
from src.hub.coordinate_sources.map_embed import extract_map_embed_coordinates
from src.hub.coordinate_sources.structured_metadata import (
    extract_inline_latlng,
    extract_jsonld_geo,
    infer_location_role,
)

DEFAULT_USER_AGENT = "PantipPropertyResearch/2.0 (local-evidence-acquisition; read-only)"
DEFAULT_TIMEOUT_SEC = 20
DEFAULT_MIN_INTERVAL_SEC = 1.0

_last_fetch_at = 0.0


def fetch_public_page(url: str, *, user_agent: str = DEFAULT_USER_AGENT) -> tuple[int, str, str | None]:
    """Fetch one public page. Returns (status_code, body, error)."""
    global _last_fetch_at
    elapsed = time.time() - _last_fetch_at
    if elapsed < DEFAULT_MIN_INTERVAL_SEC:
        time.sleep(DEFAULT_MIN_INTERVAL_SEC - elapsed)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            _last_fetch_at = time.time()
            return resp.status, body, None
    except urllib.error.HTTPError as exc:
        _last_fetch_at = time.time()
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        return exc.code, body, str(exc)
    except Exception as exc:  # noqa: BLE001
        _last_fetch_at = time.time()
        return 0, "", str(exc)


def extract_coordinates_from_html(
    html: str,
    *,
    source_url: str,
    project_id: str,
    provider: str,
    lineage_id: str,
) -> list[CoordinateCandidate]:
    hits: list[dict[str, Any]] = []
    hits.extend(extract_jsonld_geo(html))
    hits.extend(extract_inline_latlng(html))
    hits.extend(extract_map_embed_coordinates(html))

    out: list[CoordinateCandidate] = []
    seen: set[str] = set()
    for hit in hits:
        lat, lng = hit["latitude"], hit["longitude"]
        key = f"{lat:.6f},{lng:.6f}"
        if key in seen:
            continue
        seen.add(key)
        role = hit.get("location_role") or infer_location_role(html, hit.get("context_type", ""))
        out.append(
            CoordinateCandidate(
                project_id=project_id,
                latitude=lat,
                longitude=lng,
                provider=provider,
                source_url=source_url,
                source_record_id=source_url,
                extraction_method=hit.get("extraction_method", "unknown"),
                retrieved_at=utc_now_iso(),
                evidence_lineage_id=lineage_id,
                tier="T4_COORD",
                confidence="LOW",
                location_role=role,
                raw_value_hash=hash_coordinate(lat, lng),
            )
        )
    return out


def fetch_and_extract(
    *,
    project_id: str,
    url: str,
    provider: str,
    lineage_id: str,
) -> tuple[list[CoordinateCandidate], dict[str, Any]]:
    status, body, error = fetch_public_page(url)
    meta = {
        "url": url,
        "status_code": status,
        "error": error,
        "provider": provider,
        "body_length": len(body or ""),
    }
    if error or status >= 400 or not body:
        return [], meta
    candidates = extract_coordinates_from_html(
        body,
        source_url=url,
        project_id=project_id,
        provider=provider,
        lineage_id=lineage_id,
    )
    # Only project-site coords from directory pages
    candidates = [c for c in candidates if c.location_role == LOCATION_ROLE_PROJECT_SITE]
    return candidates, meta
