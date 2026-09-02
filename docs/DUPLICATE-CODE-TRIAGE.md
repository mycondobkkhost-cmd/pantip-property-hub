# Duplicate Property Code Triage (Read-Only)

**Date:** Phase A analysis (updated Phase B/D)  
**Data file:** `data/properties.json` (local snapshot — not modified)

## Phase B status (implemented)

As of Phase B (`property_resolve.py`):

- **`property_id`** is canonical for all write paths hardened in Phase B
- Duplicate **`property_code`** → `PROPERTY_CODE_AMBIGUOUS` (no silent first-match)
- Sheet overlay uses `property_id` when available
- Synthetic cross-project duplicate fixture in `data_seed/` (Phase C/D)

Phase B does **not** renumber or merge historical duplicate codes in production data.

## Summary (historical snapshot analysis)

| Metric | Value |
|--------|-------|
| Total properties | 7,323 |
| Duplicate **codes** (groups) | **300** |
| Records in duplicate groups | **614** |
| Extra records (beyond first per code) | **314** |
| Max records sharing one code | **16** (`PTP4734`) |
| Duplicate property **IDs** | **0** |

## Classification (automated heuristic)

All 300 groups classified as **`CODE_REUSE_DIFFERENT_PROPERTIES`**:

- Same `property_code` assigned to listings with **different `project_id`**
- Different prices across rows in the same code group
- Not consistent with “same listing duplicated twice”

| Size | Groups |
|------|--------|
| 2 records | 299 |
| 16 records | 1 (`PTP4734`) |

**Interpretation:** This pattern resembles a **bulk import / code-assignment collision** (many distinct listings sharing one human code), not accidental double-save of one listing.

## Property identity rule

- **`property_id` (UUID)** = canonical internal identity ✓
- **`property_code`** = human reference only — **not unique** in current data

**No codes were changed in Phase A.**

---

## Owner review sample (30 groups)

Prioritized: multiple projects, price spread, high collision count.

### 1. `PTP4734` — 16 records, 16 different project IDs

- Prices span rent/sale ranges (multiple distinct values)
- Status mix: `active`, `needs_review`
- **Risk (pre-Phase B):** Any code-based lookup returns **only the first** matching row
- **Post-Phase B:** Code-only lookup returns ambiguous unless `property_id` supplied

### 2. `PTP3435` — 2 records, 2 project IDs — prices 18,000 vs 28,000

### 3. `PTP4500` — 2 records — 12,000 vs 24,000

### 4–30. (See Phase A analysis — additional two-record cross-project groups)

(Full machine-readable sample was produced during Phase A analysis; ask for export if needed.)

---

## Code paths using `property_code` lookup

Functions that resolved **first match by code** (risk when duplicates exist):

| Location | Function / pattern | Read/Write | Wrong-record risk |
|----------|-------------------|------------|-------------------|
| `src/hub/publish_caption.py` | `find_property_by_code` | Read | **Mitigated** — returns ambiguous |
| `src/hub/project_store.py` | property updates | **Write** | **Mitigated** — requires `property_id` |
| `scripts/hub_server.py` | publish, scrape, generate | Read | **Mitigated** via resolve |
| `src/hub/auto_follow_store.py` | code-based property match | Read/Write | Medium |
| `src/hub/sheet_sync.py` | overlay | **Write** on pull | High if pull enabled |

**Safer pattern:** always use `property_id` for updates when duplicates exist.

---

## Automation impact (if codes stay duplicated)

| System | Impact |
|--------|--------|
| Hub UI search by code | Must disambiguate or use id |
| Facebook publish | Blocked when code ambiguous (Phase B) |
| Group recommend | Property context must use id |
| Google Sheet export | Rows keyed by code may **collapse/overlays** |
| Co-Agent | Catalog lists **each property_id** separately (codes may repeat in UI) |
| CRM | Uses case IDs; code lists may ambiguous |

---

## Future options (owner decision — not executed)

### Option 1: Allow duplicate human codes; internal logic uses `property_id`

- **Benefit:** No mass migration
- **Risk:** Legacy paths must stay id-aware
- **Effort:** Medium (API/UI always pass id)
- **Status:** Phase B partial implementation

### Option 2: Unique codes for **new** listings only; leave historical duplicates

- **Benefit:** Stops growth of problem
- **Risk:** 300 historical groups remain
- **Effort:** Low policy + allocator change

### Option 3: Controlled historical code migration

- **Benefit:** Clean human-facing codes
- **Risk:** Breaks external references, FB links, sheet rows
- **Effort:** High — requires owner-approved mapping table

---

## Phase A actions taken

- ✅ Analysis only — **no renumber, merge, or delete**
- ✅ Tests added for duplicate-code + identity behavior
- ✅ Policy documented: `property_id` primary, `property_code` reference
