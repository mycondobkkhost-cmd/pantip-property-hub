# Phase Z2 — Coordinate Source Policy

## Trusted local sources (read-only)

| Source | Lineage ID | Default tier |
|--------|-----------|--------------|
| project_master_v01 (existing) | lineage:coordinate_pin | T1/T2 |
| propertyhub_acquisition_* | lineage:propertyhub_acquisition | T2 if identity_match |
| project_location_profile_8z2d | lineage:location_profile_8z2d | T4 |
| location_fact_* | lineage:location_fact | T4 |
| pantip projects.json living URL | lineage:pantip_projects_json | URL inventory only |

## Public web (bounded)

- Allowed: public developer/directory pages, JSON-LD GeoCoordinates, inline lat/lng, map embeds
- Not allowed: paid APIs, login, CAPTCHA bypass, aggressive crawl
- Default new web evidence: **T4_COORD**
- Promotion to T3: ≥2 **independent** lineages within **75m**

## Location role protection

Only `PROJECT_SITE` coordinates support promotion. `SALES_OFFICE` and `DEVELOPER_HQ` are rejected.

## Provider independence

Same upstream syndication → same lineage family. `INDEPENDENCE_UNKNOWN` blocks automatic T3.
