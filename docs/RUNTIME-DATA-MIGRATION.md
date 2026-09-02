# Runtime Data Git Migration — Prerequisites (Phase B)

**Status:** Do **not** remove `data/properties.json` / `data/projects.json` from Git yet.

## Prerequisites checklist

| # | Prerequisite | Phase B status |
|---|--------------|----------------|
| 1 | Property identity safe on mutation paths | Done (resolve API + tests) |
| 2 | Public catalog allowlist (no raw objects in preview-data.js) | Done |
| 3 | Backup tool + restore dry-run validated locally | Done (synthetic) |
| 4 | Dev seed design approved | Documented — owner review |
| 5 | Fly volume backup schedule | Planned — not configured |
| 6 | Production restore drill | Not run |
| 7 | `.gitignore` + docs for runtime JSON | Partial (Phase A) |
| 8 | CI/tests use fixtures not production JSON | Partial |

## Future procedure (when approved)

1. Add `data_seed/` synthetic bootstrap (see `docs/DEV-SEED-DESIGN.md`)
2. Update `.gitignore` for runtime SoT files
3. `git rm --cached data/properties.json data/projects.json` (keep volume copy)
4. Document clone flow: Docker seed → local volume
5. Deploy with existing volume unchanged
6. Rollback: restore volume from backup; re-track JSON only if emergency

## Rollback

Prefer Fly volume restore over Git history — Git copy may be stale vs production.
