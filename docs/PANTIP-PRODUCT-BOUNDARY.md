# Pantip Product Boundary

## Pantip Property Automation

Pantip is an **internal back-office** system for owner/admin/operator/staff.

Primary purposes:

- Manage the internal property database
- Inspect property details and maintain listings
- Track old properties and follow-up workflows
- Preserve owner/operational information
- Keep existing Hub functions reliable

The only externally viewable surface is **Co-Agent** — a read-only safe view of selected listing data.

## Co-Agent boundary

Co-Agent:

- Reads selected/safe property information from Pantip data
- Must **not** access owner/private/internal fields
- May view listing details allowed for agents
- May follow **public** listing/post URLs supplied by Pantip staff (`post_url`, `post_pages_url`)
- Is **not** a separate canonical property database

Internal `source_url` (source reference) may contain arbitrary staff reference text and is **never** exposed to Co-Agent.

## RealXtate

RealXtate is a **separate product and database**.

Pantip does **not** mirror RealXtate architecture.

Future relationship (not in scope for Z9):

```
Pantip internal property → operator explicitly selects property → selected safe data exported/published to RealXtate
```

No shared runtime database is assumed. Integration is explicit selective export/publish only.

## Z9 scope

- Harden internal back-office usability
- Generalize source reference field (not URL-only)
- Integrate Z7/Z8 follow-up into operational UI
- Enforce Co-Agent privacy boundary
- No RealXtate mutation or redesign
