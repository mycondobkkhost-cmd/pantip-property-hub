# Duplicate Property Code Triage (Read-Only)

**Date:** Phase A analysis  
**Data file:** `data/properties.json` (local snapshot — not modified)

## Summary

| Metric | Value |
|--------|------|
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

## Property identity rule (unchanged)

- **`property_id` (UUID)** = canonical internal identity ✓
- **`property_code`** = human reference only — **not unique** in current data

**No codes were changed in Phase A.**

---

## Owner review sample (30 groups)

Prioritized: multiple projects, price spread, high collision count.

### 1. `PTP4734` — 16 records, 16 different project IDs

- Prices span rent/sale ranges (multiple distinct values)
- Status mix: `active`, `needs_review`
- **Risk:** Any code-based lookup returns **only the first** matching row

### 2. `PTP3435` — 2 records, 2 project IDs — prices 18,000 vs 28,000

### 3. `PTP4500` — 2 records — 12,000 vs 24,000

### 4. `PTP4501` — 2 records — 20,000 vs 30,000

### 5. `PTP4502` — 2 records — 1,600,000 vs 20,000 (rent vs sale scale)

### 6. `PTP4503` — 13,000 vs 18,000

### 7. `PTP4504` — 15,000 vs 9,500

### 8. `PTP4505` — 120,000 vs 16,500

### 9. `PTP4506` — 16,000 vs 19,000

### 10. `PTP4507` — 13,000 vs 15,000

### 11. `PTP4508` — 19,000 vs 65,000

### 12. `PTP4509` — 22,000 vs 35,000

### 13. `PTP4510` — 12,000 vs 17,000

### 14. `PTP4511` — 12,000 vs 18,000

### 15. `PTP4512` — 27,000 vs 45,000

### 16. `PTP4513` — 10,000 vs 26,000

### 17. `PTP4514` — 10,000 vs 25,000

### 18. `PTP4515` — 11,500 vs 12,000

### 19. `PTP4516` — 22,000 vs 46,000

### 20. `PTP4517` — 20,000 vs 40,000

### 21. `PTP4518` — 11,000 vs 19,000

### 22. `PTP4519` — 20,000 vs 23,000

### 23. `PTP4520` — 15,000 vs 18,000

### 24. `PTP4521` — 160,000 vs 18,000

### 25. `PTP4522` — 13,000 vs 23,000

### 26. `PTP4523` — 25,000 vs 34,000

### 27. `PTP4524` — 22,000 vs 25,000

### 28. `PTP4525` — 25,000 vs 39,500

### 29. `PTP4526` — 30,000 vs 52,000

### 30. `PTP4527` — 18,000 vs 28,000

(Full machine-readable sample was produced during Phase A analysis; ask for export if needed.)

---

## Code paths using `property_code` lookup

Functions that resolve **first match by code** (risk when duplicates exist):

| Location | Function / pattern | Read/Write | Wrong-record risk |
|----------|-------------------|------------|-------------------|
| `src/hub/publish_caption.py` | `find_property_by_code` | Read | **High** — publish caption/images |
| `src/hub/project_store.py` | `set_property_page_post_text` | **Write** | **High** |
| `src/hub/project_store.py` | `update_property` accepts code as id fallback | **Write** | Medium |
| `scripts/hub_server.py` | `/api/groups/recommend`, publish, scrape, generate | Read | **High** |
| `src/hub/auto_follow_store.py` | code-based property match | Read/Write | Medium |
| `src/hub/sheet_sync.py` | overlay keyed by code | **Write** on pull | High if pull enabled |

**Safer pattern:** always use `property_id` for updates when duplicates exist.

---

## Automation impact (if codes stay duplicated)

| System | Impact |
|--------|--------|
| Hub UI search by code | May show/open wrong row if UI picks first match |
| Facebook publish | Caption/images for **first** matching code |
| Group recommend | Property context from first match |
| Google Sheet export | Rows keyed by code may **collapse/overlays** |
| Co-Agent | Catalog lists **each property_id** separately (codes may repeat in UI) |
| CRM | Uses case IDs; code lists may ambiguous |

---

## Future options (owner decision — not executed)

### Option 1: Allow duplicate human codes; internal logic uses `property_id`

- **Benefit:** No mass migration
- **Risk:** Must fix code-based write paths or accept ambiguity
- **Effort:** Medium (API/UI always pass id)

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
