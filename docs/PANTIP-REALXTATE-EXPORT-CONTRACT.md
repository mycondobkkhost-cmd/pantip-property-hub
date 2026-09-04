# Pantip → RealXtate Selective Export Contract (v1)

## Product boundary

| System | Role |
|--------|------|
| **Pantip Property Automation** | Internal operations + safe Co-Agent read view |
| **RealXtate** | Separate customer-facing product and database |

There is **no shared runtime database**. Integration is **explicit selective publish/export only**.

## Integration mechanism

1. Operator selects a Pantip property in internal back-office.
2. System evaluates export eligibility (`evaluate_export_eligibility`).
3. If eligible, operator explicitly triggers publish/export (future phase — not implemented in Z10).
4. RealXtate receives only the allowlisted projection (`project_realxtate_export`).

No automatic whole-database sync. No bidirectional hidden coupling.

## Schema

- **Version:** `pantip_realxtate_export/v1`
- **Source system:** `pantip_property`
- **Canonical Pantip identity:** `source_property_id` = Pantip `property_id` (UUID)

## Allowlisted export fields

- `export_schema_version`
- `source_system`
- `source_property_id`
- `property_code`
- `project_id`, `project_name`
- `property_type`, `bedrooms`, `size_sqm`
- `rent_price`, `sale_price`
- `public_description_th`, `public_description_en`
- `public_listing_url` (from `post_pages_url` or `post_url` only — never `source_url`)
- `zones`, `transit`
- `listing_status`, `last_listed_at`
- `image_urls`

## Never export

- `source_url` (internal reference text)
- `notes`, owner phones/LINE/Facebook
- contact history, tenant/customer data
- internal queue/recheck status
- credentials/tokens

## Eligibility rules

A property is exportable only when:

1. `property_id` present
2. `property_code` present
3. `project_id` present
4. At least one of `rent_price` or `sale_price`
5. Valid `public_listing_url` from published post links

## Idempotency (future)

Recommended cross-system key:

```json
{
  "source_system": "pantip_property",
  "source_property_id": "<property_id>",
  "export_schema_version": "pantip_realxtate_export/v1"
}
```

Updates should upsert by `(source_system, source_property_id)` to avoid duplicate RealXtate listings.

## Z10 scope

- Contract documentation (this file)
- Local projection module: `src/hub/realxtate_export.py`
- Dry-run tooling: `scripts/realxtate_export_dry_run.py`
- **No network calls, no RealXtate repo access, no writes**
