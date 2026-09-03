# Property Identity Contract (Phase B)

## Canonical rules

| Field | Role |
|-------|------|
| `property_id` (`id` in JSON) | Unique canonical machine identity |
| `property_code` (`code`) | Human/reference identifier — **not unique** |

## Resolution semantics

Implemented in `src/hub/property_resolve.py`:

- **By `property_id`:** 0 → `PROPERTY_NOT_FOUND`; 1 → success
- **By `property_code` (action paths):** 0 → not found; 1 → success; 2+ → `PROPERTY_CODE_AMBIGUOUS`
- **Never** use `matches[0]` on ambiguous codes for mutation or external side effects

## Action paths (require safe resolution)

- Property save/update/links (`project_store`)
- Caption generation / publish bundle (`publish_caption`)
- Publish job create + FB agent due queue (`group_post_publish_store`, `hub_server`)
- Group recommend when hydrating from code (`hub_server`)
- Focus pins by code (`focus_store`)
- Sheet overlay re-apply prefers `property_id`; ambiguous codes skip code-only overlay (`sheet_sync`)

## Search/display paths (may return multiple)

- Human code search may return candidate lists
- Co-Agent catalog lists all rows with distinct `property_id`
- Public catalog uses explicit allowlist projection only

## Deprecated (compatibility)

Legacy clients may still send `property_code` **only when unique**. Duplicate codes receive HTTP 409 with `PROPERTY_CODE_AMBIGUOUS` and candidate summaries (no private fields).
