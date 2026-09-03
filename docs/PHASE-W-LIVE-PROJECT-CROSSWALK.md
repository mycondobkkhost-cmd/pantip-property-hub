# Phase W — Live Project Crosswalk

Completed 2026-09-04. Read-only analysis of **current Fly production** `/app/data` against RealXtate trusted master reference.

## Key finding

**Git `data/projects.json` is NOT authoritative for production correction planning.**

| Source | Projects | Properties |
|--------|----------|------------|
| **LIVE production** (Fly `/app/data`) | **2,175** | **7,481** |
| Git snapshot | 2,234 | 7,323 |
| RealXtate catalog | 2,156 | 7,288 |

## Live acquisition (read-only)

- Method: `fly ssh sftp get` from machine `28623d2ae33748`
- Local temp copy: `/tmp/pantip-phase-w-live/`
- Files: `projects.json`, `properties.json`, `project_aliases.json`
- SHA-256 at acquisition recorded in phase-w-summary
- **No production writes performed**

## Live ↔ Git delta (by project_id)

| Bucket | Count | Meaning |
|--------|------:|---------|
| LIVE_AND_GIT | 2,156 | Shared stable IDs |
| LIVE_ONLY | 19 | New production projects not in Git |
| GIT_ONLY | 78 | **Stale Git-only projects — NOT in live production** |

## Phase V "78 conflicts" reconciliation

All **78** Phase V conflict records are **`GIT_ONLY_STALE`**.

None exist in current live production. The Phase V conflict finding was an artifact of analyzing obsolete Git snapshot projects, not live identity debt.

## Live crosswalk match classes

| Class | Count |
|-------|------:|
| EXACT_ID_MATCH | 2,156 |
| PANTIP_ONLY | 19 |
| CONFLICT | 0 |

Current live Pantip projects map deterministically to RealXtate by stable `project_id` except 19 Pantip-only projects (mostly non-condo / townhouse / home-office entries).

## Legacy "verified" promotion audit (LIVE)

| Metric | Count |
|--------|------:|
| `zone_verified == zone_unverified` | 2,041 / 2,175 |
| `transit_verified == transit_unverified` | 1,879 / 2,175 |
| Listings on legacy-promotion projects | 7,297 / 7,481 |

**Interpretation:** Most "verified" zone/transit values are sheet copies, not independently corroborated.

### Suspicious bulk concentrations

| Label | Projects |
|-------|----------|
| Zone: สุขุมวิท | 579 |
| Zone: เจริญนคร | 573 |
| Transit: BTS กรุงธนบุรี | 572 |
| Transit: BTS เจริญนคร | 478 |

## RealXtate marketplace area overlay (LIVE)

| Confidence | Projects | Live listings affected (HIGH+MEDIUM) |
|------------|----------|--------------------------------------|
| REALXTATE_HIGH | 464 | (subset of 4,888 total) |
| REALXTATE_MEDIUM | 295 | |
| REALXTATE_LOW | 1,280 | |
| NO_REALXTATE_AREA | 136 | |

**759** live projects have RealXtate HIGH/MEDIUM area assignments.

## Area agreement matrix (HIGH/MEDIUM RealXtate only)

| Class | Projects | Listings |
|-------|----------:|---------:|
| DIRECT_CONFLICT | 134 | 922 |
| SEMANTICALLY_DIFFERENT_BUT_NOT_CONFLICT | 396 | 2,806 |
| PARTIAL_AGREE | 229 | 1,160 |
| PANTIP_HAS_VALUE_REALXTATE_MISSING | 1,298 | 2,461 |
| INSUFFICIENT_EVIDENCE | 118 | 123 |

Pantip `zone_verified` is **not** equivalent to RealXtate marketplace area. Admin/corridor labels (e.g. วัฒนา, สุขุมวิท) vs marketplace areas (e.g. thonglor) are classified as semantically different, not direct conflicts.

## Owner review queue

Top 50 candidates generated offline. All scored P0 in this run (HIGH RealXtate confidence + DIRECT_CONFLICT + high listing count).

Examples:
- Life Asoke Rama 9 — 84 listings — REVIEW_RECOMMENDED
- Life Asoke Hype — 63 listings — REVIEW_RECOMMENDED
- The Tree Pattanakarn-Ekkamai — 57 listings — REVIEW_RECOMMENDED

## Analysis artifacts (local only, NOT in Git)

| Path | Purpose |
|------|---------|
| `/tmp/pantip-phase-w-crosswalk/live-project-crosswalk.json` | Full crosswalk |
| `/tmp/pantip-phase-w-crosswalk/area-reference-overlay.json` | HIGH/MEDIUM overlay |
| `/tmp/pantip-phase-w-crosswalk/identity-conflicts.json` | Phase V reconciliation |
| `/tmp/pantip-phase-w-crosswalk/owner-review-top50.csv` | Review queue |
| `/tmp/pantip-phase-w-crosswalk/phase-w-summary.json` | Summary metrics |

Backup copy: `/Users/angkarn1996/Backups/pantip-property-automation/phase-w-crosswalk-20260904T035800Z/`

## Tooling

```bash
python3 scripts/build_live_project_crosswalk.py \
  --pantip-projects /tmp/pantip-phase-w-live/projects.json \
  --pantip-properties /tmp/pantip-phase-w-live/properties.json \
  --realxtate-catalog /path/to/realxtate-catalog.sqlite \
  --realxtate-trusted /path/to/realxtate-trusted-master.sqlite \
  --git-projects data/projects.json \
  --output-dir /tmp/pantip-phase-w-crosswalk
```

## Next phase

See `docs/PROJECT-CROSSWALK-REVIEW-POLICY.md` for Phase X owner review system scope.
