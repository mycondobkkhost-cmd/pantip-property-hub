# Master Review Apply Boundary

Phase X explicitly does **not** apply canonical corrections to production.

## What Phase X may write

| Target | Allowed |
|--------|---------|
| `.local/master_review/master_review_decisions.jsonl` | Yes (dev) |
| Promotion candidate export (download) | Yes |
| `projects.json` | **NO** |
| `properties.json` | **NO** |
| Fly `/app/data` | **NO** |
| RealXtate | **NO** |

## Stale decision protection

Each review item stores:

- `source_snapshot.source_hash` — hash of Phase W crosswalk file
- `source_project_fingerprint` — hash of project fields at review time

Future correction phase must reject approved decisions when:

1. `expected_source_snapshot_hash` ≠ current crosswalk hash, OR
2. `source_project_fingerprint` ≠ current live project fingerprint

## Promotion candidate artifact

Filename pattern: `canonical-promotion-candidate-v0.1.json`

This is **not** a production patch. It lists owner-approved proposals for a future dry-run phase.

## Future apply pipeline (not implemented)

```
1. Load promotion candidate
2. Fresh production backup
3. Re-validate fingerprints
4. Dry-run patch (counts only)
5. Owner authorization (separate phase)
6. Transactional apply + audit log
```

Phase X stops before step 1 execution against production.
