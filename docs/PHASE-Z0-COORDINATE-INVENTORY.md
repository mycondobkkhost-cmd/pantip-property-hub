# Phase Z0 — Coordinate Inventory

## Sources audited (read-only)

| Source | Scope | Notes |
|---|---|---|
| `project_master_v01` (RealXtate trusted) | 2,156 projects | Primary coordinate reference |
| Phase W `live-project-crosswalk.json` | 2,175 LIVE projects | Identity context |
| Pantip `data/projects.json` | Git snapshot | **Not production truth for Z0** |
| PropertyHub catalog sqlite | `property_projects` | Listing location bags |

## Phase W label correction

Phase W reported `COORD_CONFLICT: 1078` — **misleading**.

Root cause in `scripts/build_live_project_crosswalk.py` `load_coordinate_states()`:

- Checks `coord.get("lat")` but RealXtate payload uses `latitude` / `longitude`.
- All 1,078 SOURCE_PROVIDED pins were mis-bucketed.

## Re-audited coordinate states (project_master_v01)

| State | Count |
|---|---|
| SOURCE_PROVIDED + ACCEPTED + lat/lng | **1,078** |
| NONE (missing) | **1,078** |
| REJECTED_IDENTITY | 39 |

Classification for Z0 engine:

| Class | Count | Definition |
|---|---|---|
| CANDIDATE | 1,078 | SOURCE_PROVIDED, ACCEPTED, has lat/lng (T2 pin) |
| MISSING | 1,097 | No usable coordinate in trusted master |
| VERIFIED | 0 | No owner-verified canonical pins found |
| CONFLICT | 0 | No true lat/lng conflicts detected at project level |

## Coverage vs LIVE crosswalk (2,175)

- Evaluable with pin: **1,078 (49.6%)**
- Not evaluable: **1,097 (50.4%)**

## Quality signals

| Signal | Finding |
|---|---|
| Duplicate exact coordinates | Present (multiple projects share identical pins — needs Z1 clustering review) |
| Coordinates outside Bangkok metro | Rare; not primary failure mode |
| Impossible coordinates | Not observed in Aspire case |
| Actual project pins vs district centroid | PropertyHub directory pins used; treat as CANDIDATE not VERIFIED |

## Z0 policy

- Coordinates are **read for analysis only** — no writes.
- AUTO_SAFE requires CANDIDATE pin + spatial evidence; never from sheet zone text alone.
