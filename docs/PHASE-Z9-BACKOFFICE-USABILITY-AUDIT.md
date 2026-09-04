# Phase Z9 — Back-Office Usability Audit

Date: 2026-09-04  
Branch: `cursor/backoffice-product-hardening`

## Surfaces audited

| Surface | Path | Purpose |
|---------|------|---------|
| Property list | `hub/preview.html` (properties tab) | Search, filter, cards |
| Property create/edit | `hub/preview.html` (add panel) | CRUD, scrape, parse |
| Queue | `hub/preview.html` (queue tab) | Pre-post queue |
| Follow-up cases | `hub/preview.html` (followup tab) | Customer workflow |
| Tenants | `hub/preview.html` (tenants tab) | Lease capture |
| Operator follow-up | `hub/operator-follow-up/` | Z7/Z8 recheck dashboard |
| Policy review | `hub/operator-policy-review/` | Z8 owner policy packet |
| Co-Agent catalog | `src/hub/co_catalog.py` | Read-only public view |
| Hub API | `scripts/hub_server.py` | CRUD, scrape, recheck |

## Findings

### BUG — source reference URL-only restriction

| Field | Classification |
|-------|----------------|
| `source_url` / ลิงก์ต้นโพสต์ | **BUG** + **UNNECESSARY_RESTRICTION** |

- **Current behavior:** `#add-url` used `type="url"` causing browser HTML5 validation to reject plain text on edit/save.
- **Expected:** Accept URL, Facebook URL, plain Thai/English text, source ID, or staff note.
- **Risk:** Staff cannot save useful non-URL references; blocks workflow.
- **Fix (Z9):** Change to `type="text"`, update label/helper, render clickable only when valid http(s) URL.
- **Test:** `test_phase_z9_backoffice_hardening.py` source-reference cases.

### COAGENT_PRIVACY_RISK — mitigated (pre-existing, verified)

- `source_url` was already excluded from `_CO_ITEM_KEYS` / `slim_property`.
- Z9 adds explicit `derive_public_listing_url()` — only `post_pages_url` / `post_url`.
- Internal free-text references cannot leak to Co-Agent.

### UNNECESSARY_RESTRICTION — scrape action (by design, boundary correct)

- `/api/scrape` requires valid URL — correct at action boundary only.
- Property save accepts any `source_url` string (no server-side URL validation).

### CONFUSING_UX — label mismatch

- Label said "ลิงก์โพสต์ต้นทาง" implying URL-only.
- **Fix:** "ลิงก์ต้นโพสต์ / แหล่งอ้างอิง" + helper text.

### CONFUSING_UX — list cell showed dash for non-URL text

- `linksCell()` used `linkHtml()` which returned `—` for non-URLs.
- **Fix:** Show truncated plain text with full text in title.

### NICE_TO_HAVE — follow-up integration

- Z7/Z8 dashboards were separate pages.
- **Fix (Z9):** Sidebar link under ฟอโล่ว → "ติดตามทรัพย์เก่า" → `/operator-follow-up/`.

### NICE_TO_HAVE — editable recheck settings

- Z8 had `recheck_capacity.load_capacity_config()` but no unified settings API.
- **Fix (Z9):** `operational_settings.py` + `/api/operational-settings` GET/POST.

### DATA_RISK — none found in CRUD parity

- Create and edit both send `source_url` via same `addFormPayload()` / API fields.
- Backend `project_store.py` stores string without validation.

### Deferred

| Item | Classification | Notes |
|------|----------------|-------|
| `add-post-url` / `add-page-url` remain `type="url"` | Intentional | These are actual published post URLs |
| Facebook group form URLs | Intentional | Real URLs required for automation |
| Full in-page recheck UI merge | NICE_TO_HAVE | Z10 could embed recheck panel in preview.html |

## Create/edit parity

| Field | Create | Edit | Parity |
|-------|--------|------|--------|
| source_url | ✓ | ✓ | OK |
| project | ✓ | ✓ | OK |
| price rent/sale | ✓ | ✓ | OK |
| bedrooms/bathrooms | ✓ | ✓ | OK |
| size | ✓ | ✓ | OK |
| owner notes | ✓ | ✓ | OK |
| post_url / post_pages_url | ✓ | ✓ | OK |

## Root cause summary (Z9 question A/B)

**A.** Primary cause: HTML5 `<input type="url">` on `#add-url` in `hub/preview.html`.

**B.** Validation layer: Browser-native constraint validation (client-side). No server-side URL-only restriction on `source_url` persistence.
