"""Read/write Project Master — create projects and update shared transit."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROJECTS_JSON = BASE_DIR / "data" / "projects.json"
PROPERTIES_JSON = BASE_DIR / "data" / "properties.json"
DB_PATH = BASE_DIR / "data" / "hub.db"
# Catalog JS must live on the persistent data volume (Fly mounts /app/data).
# Writing only under hub/ loses saves after every deploy/restart.
PREVIEW_JS = BASE_DIR / "data" / "preview-data.js"
PREVIEW_META = BASE_DIR / "data" / "preview-data.meta.json"
# Legacy path from older deploys / local static opens — mirrored for compatibility.
PREVIEW_JS_LEGACY = BASE_DIR / "hub" / "preview-data.js"
PREVIEW_META_LEGACY = BASE_DIR / "hub" / "preview-data.meta.json"


def _e2e_data_root() -> Path | None:
    raw = (os.environ.get("PANTIP_E2E_DATA_ROOT") or "").strip()
    return Path(raw) if raw else None


def projects_path() -> Path:
    root = _e2e_data_root()
    return (root / "projects.json") if root else PROJECTS_JSON


def properties_path() -> Path:
    root = _e2e_data_root()
    return (root / "properties.json") if root else PROPERTIES_JSON

# ThreadingHTTPServer serves requests concurrently — serialize read-modify-write
# so multi-add / parallel saves cannot lose rows or collide on hub.db rebuild.
_STORE_LOCK = threading.RLock()


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


from src.hub.project_identity import resolve_bucket as _resolve_bucket
from src.hub.project_identity import soft_norm as _soft_norm


def coerce_pet_friendly(val) -> bool:
    """Normalize PETS / checkbox / notes-ish values to bool."""
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    if isinstance(val, (int, float)):
        return bool(val)
    s = str(val).strip().lower()
    if not s:
        return False
    if s in ("no", "n", "false", "0", "ไม่", "ห้าม", "off"):
        return False
    if s in ("yes", "y", "true", "1", "on", "pet", "pets", "pet friendly", "petfriendly"):
        return True
    raw = str(val)
    if "ห้ามสัตว์" in raw or "no pet" in s:
        return False
    return "pet friendly" in s or "เลี้ยงสัตว์ได้" in raw or "สัตว์เลี้ยงได้" in raw


def pets_sheet_value(prop: dict) -> str:
    return "Yes" if coerce_pet_friendly(prop.get("pet_friendly")) else "No"


MAIN_SHEET_CSV = BASE_DIR / "data" / "main_sheet.csv"


def backfill_pet_friendly_from_sheet(*, csv_path: Path | None = None) -> dict:
    """Apply PETS column from main_sheet.csv onto existing properties by code."""
    import csv

    path = csv_path or MAIN_SHEET_CSV
    if not path.is_file():
        return {"ok": False, "error": f"missing {path}", "updated": 0}

    with open(path, encoding="utf-8") as f:
        sheet = list(csv.reader(f))
    if not sheet:
        return {"ok": False, "error": "empty sheet", "updated": 0}
    headers = [h.strip() for h in sheet[0]]
    try:
        code_i = headers.index("รหัสทรัพย์")
        pets_i = headers.index("PETS")
    except ValueError:
        return {"ok": False, "error": "sheet missing รหัสทรัพย์ or PETS", "updated": 0}

    pets_by_code: dict[str, bool] = {}
    for r in sheet[1:]:
        if code_i >= len(r):
            continue
        code = str(r[code_i] or "").upper().replace(" ", "")
        if not code:
            continue
        raw = r[pets_i] if pets_i < len(r) else ""
        pets_by_code[code] = coerce_pet_friendly(raw)

    with _STORE_LOCK:
        projects = load_projects()
        properties = load_properties()
        updated = 0
        for prop in properties:
            code = str(prop.get("code") or "").upper().replace(" ", "")
            if code not in pets_by_code:
                continue
            want = pets_by_code[code]
            had = "pet_friendly" in prop
            cur = coerce_pet_friendly(prop.get("pet_friendly")) if had else None
            if had and cur == want:
                continue
            prop["pet_friendly"] = want
            updated += 1
        if updated:
            persist(projects, properties)
        return {
            "ok": True,
            "updated": updated,
            "sheet_pets_yes": sum(1 for v in pets_by_code.values() if v),
            "props_pets_yes": sum(1 for p in properties if coerce_pet_friendly(p.get("pet_friendly"))),
            "total_props": len(properties),
        }


def norm_key(name: str) -> str:
    """Normalize for bucket / identity — use outer name, drop parenthetical alias."""
    return _soft_norm(name)


def norm_search_key(name: str) -> str:
    """Normalize for search — keep Thai/EN inside parentheses."""
    n = name.lower().strip()
    n = re.sub(r"[()（）]", " ", n)
    n = re.sub(r"[^a-z0-9ก-๙]", "", n)
    return n


def project_bucket(name: str) -> str | None:
    return _resolve_bucket(name)

def split_tag_parts(raw: str | list[str]) -> list[str]:
    """Split free-text tags on commas, slashes, pipes, and Thai 'และ'."""
    if isinstance(raw, list):
        chunks = [str(x) for x in raw if x is not None]
    else:
        chunks = re.split(r"[,，\n]", raw or "")
    parts: list[str] = []
    for chunk in chunks:
        for part in re.split(r"[/,|]| และ ", chunk or ""):
            label = re.sub(r"\s+", " ", (part or "").strip())
            if label and len(label) <= 80:
                parts.append(label)
    return parts


def parse_tag_list(raw: str | list[str]) -> list[str]:
    """Dedupe tag parts without station canonicalization (safe for zones)."""
    out: list[str] = []
    seen: set[str] = set()
    for label in split_tag_parts(raw):
        k = norm_key(label)
        if k and k not in seen:
            seen.add(k)
            out.append(label)
    return out


def parse_station_tags(raw: str | list[str]) -> list[str]:
    """Split compounds and canonicalize to atomic BTS/MRT/ARL labels when possible."""
    try:
        from src.hub.project_location_enrich import canonicalize_station
    except Exception:  # noqa: BLE001
        canonicalize_station = None  # type: ignore[assignment]

    out: list[str] = []
    seen: set[str] = set()
    for label in split_tag_parts(raw):
        use = label
        if canonicalize_station is not None:
            canon = canonicalize_station(label)
            if canon:
                use = canon
            elif not re.search(r"\b(BTS|MRT|ARL|Airport\s*Link|APL)\b", label, re.I):
                # bare area name without rail prefix — skip in station lists
                continue
        k = norm_key(use)
        if k and k not in seen:
            seen.add(k)
            out.append(use)
    return out


def parse_transit_input(raw: str | list[str]) -> list[str]:
    """Backward-compatible tag parser — splits compounds; no station forcing."""
    return parse_tag_list(raw)


def dedupe_transit(tags: list[str]) -> list[str]:
    return parse_tag_list(tags)


def dedupe_stations(tags: list[str]) -> list[str]:
    return parse_station_tags(tags)


def load_projects() -> list[dict]:
    path = projects_path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_properties() -> list[dict]:
    path = properties_path()
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


_PROPERTIES_CACHE: dict = {"mtime": None, "data": None}


def load_properties_cached(*, max_age_s: float = 15.0) -> list[dict]:
    """Reuse a short-lived in-memory copy — health/next_code hit this often."""
    import time

    try:
        mtime = PROPERTIES_JSON.stat().st_mtime if PROPERTIES_JSON.exists() else None
    except OSError:
        mtime = None
    now = time.monotonic()
    cached = _PROPERTIES_CACHE.get("data")
    cached_mtime = _PROPERTIES_CACHE.get("mtime")
    cached_at = float(_PROPERTIES_CACHE.get("at") or 0)
    if (
        cached is not None
        and cached_mtime == mtime
        and (now - cached_at) < max_age_s
    ):
        return cached
    data = load_properties()
    _PROPERTIES_CACHE["data"] = data
    _PROPERTIES_CACHE["mtime"] = mtime
    _PROPERTIES_CACHE["at"] = now
    return data


def project_transit_display(proj: dict) -> list[str]:
    """Verified stations only — never concatenate unverified SEO piles for Hub/sheet."""
    verified = proj.get("transit_verified") or []
    if verified:
        return dedupe_stations(verified)
    return []


def project_zone_display(proj: dict) -> list[str]:
    """Verified ทำเล only — blank until Living/corridor verification."""
    verified = proj.get("zone_verified") or []
    if verified:
        return parse_tag_list(verified)
    return []


def project_location_label(project: dict) -> str:
    """ทำเล only (areas/landmarks) — never dump BTS/MRT into this field."""
    zones = project_zone_display(project)
    if zones:
        return ", ".join(zones[:5])
    # Orphan fallback: leave blank rather than pollute ทำเล with station list
    return ""


def sync_project_listings_location_ref(project: dict, properties: list[dict]) -> int:
    """Push master transit/zone onto every listing in this project."""
    tags = project_transit_display(project)
    loc = project_location_label(project)
    updated = 0
    for prop in properties:
        if prop.get("project_id") != project["id"]:
            continue
        changed = False
        if prop.get("location_ref") != loc:
            prop["location_ref"] = loc
            changed = True
        if list(prop.get("transit_from_sheet") or []) != list(tags):
            prop["transit_from_sheet"] = list(tags)
            changed = True
        if prop.get("project_name") != project.get("canonical_name"):
            prop["project_name"] = project.get("canonical_name") or prop.get("project_name")
            changed = True
        if changed:
            updated += 1
    return updated


def write_sqlite(projects: list[dict], properties: list[dict]) -> None:
    """Rebuild hub.db atomically (temp → replace) so concurrent readers never see a deleted file."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = DB_PATH.with_name(DB_PATH.name + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    conn = sqlite3.connect(tmp_path)
    conn.executescript(
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            bucket_key TEXT UNIQUE,
            canonical_name TEXT NOT NULL,
            aliases_json TEXT,
            transit_unverified_json TEXT,
            transit_verified_json TEXT,
            zone_verified_json TEXT,
            location_status TEXT DEFAULT 'pending_verification',
            is_thru_thonglor INTEGER DEFAULT 0,
            listing_count INTEGER DEFAULT 0
        );
        CREATE TABLE properties (
            id TEXT PRIMARY KEY,
            code TEXT,
            code_prefix TEXT,
            listing_kind TEXT,
            project_id TEXT,
            last_listed_at TEXT,
            property_type TEXT,
            bedrooms TEXT,
            size_sqm TEXT,
            floor TEXT,
            rent_price TEXT,
            sale_price TEXT,
            source_url TEXT,
            post_url TEXT,
            post_pages_url TEXT,
            notes TEXT,
            import_status TEXT,
            media_status TEXT,
            sheet_row INTEGER,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );
        CREATE INDEX idx_properties_code ON properties(code);
        CREATE INDEX idx_properties_project ON properties(project_id);
        """
    )

    for p in projects:
        conn.execute(
            """
            INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                p["id"],
                p["bucket_key"],
                p["canonical_name"],
                json.dumps(p.get("aliases") or [], ensure_ascii=False),
                json.dumps(p.get("transit_unverified") or [], ensure_ascii=False),
                json.dumps(p.get("transit_verified") or [], ensure_ascii=False),
                json.dumps(p.get("zone_verified") or [], ensure_ascii=False),
                p.get("location_status") or "pending_verification",
                1 if p.get("is_thru_thonglor") else 0,
                int(p.get("listing_count") or 0),
            ),
        )

    for prop in properties:
        conn.execute(
            """
            INSERT INTO properties VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                prop["id"],
                prop.get("code"),
                prop.get("code_prefix"),
                prop.get("listing_kind"),
                prop.get("project_id"),
                prop.get("last_listed_at"),
                prop.get("property_type"),
                prop.get("bedrooms"),
                prop.get("size_sqm"),
                prop.get("floor"),
                prop.get("rent_price"),
                prop.get("sale_price"),
                prop.get("source_url"),
                prop.get("post_url"),
                prop.get("post_pages_url"),
                prop.get("notes"),
                prop.get("import_status"),
                prop.get("media_status"),
                int(prop.get("sheet_row") or 0),
            ),
        )

    conn.commit()
    conn.close()
    os.replace(tmp_path, DB_PATH)


def write_preview_js(projects: list[dict], properties: list[dict]) -> None:
    # Omit project_map from the baked JS — client builds it from projects[]
    # (duplicate map nearly doubled catalog size and OOMed free-tier deploys).
    from src.hub.public_projection import build_public_catalog_payload

    flagged = sum(1 for p in properties if p.get("duplicate_flags"))
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    data_version = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    stats = {
        "projects": len(projects),
        "properties_total": len(properties),
        "properties_active": sum(
            1 for p in properties if p.get("import_status") == "active"
        ),
        "properties_archived": sum(
            1 for p in properties if p.get("import_status") == "archived"
        ),
        "properties_needs_review": sum(
            1 for p in properties if p.get("import_status") == "needs_review"
        ),
        "properties_flagged_duplicate": flagged,
    }
    payload = build_public_catalog_payload(
        projects,
        properties,
        stats=stats,
        generated_at=generated_at,
        data_version=data_version,
    )
    body = (
        "// Auto-generated — do not edit\n"
        "window.PTP_DATA = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    meta = (
        json.dumps(
            {
                "data_version": data_version,
                "generated_at": generated_at,
                "properties_total": stats["properties_total"],
                "projects": stats["projects"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    _atomic_write_text(PREVIEW_JS, body)
    _atomic_write_text(PREVIEW_META, meta)
    # Keep hub/ copy in sync for tools that still open hub/preview-data.js directly.
    try:
        _atomic_write_text(PREVIEW_JS_LEGACY, body)
        _atomic_write_text(PREVIEW_META_LEGACY, meta)
    except OSError:
        pass


def _json_properties_count() -> int | None:
    """Cheap-ish length of properties.json array; None if unreadable."""
    if not PROPERTIES_JSON.is_file():
        return None
    try:
        data = json.loads(PROPERTIES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if isinstance(data, list):
        return len(data)
    return None


def ensure_preview_js(*, min_bytes: int = 64, force: bool = False) -> dict:
    """Rebuild catalog JS from properties.json when missing/stale/corrupt.

    On Fly, hub/ is ephemeral image disk while data/ is the volume — always prefer
    rebuilding when the volume JSON disagrees with preview meta/count.
    """
    reason = "present"
    needs = bool(force)
    if force:
        reason = "forced"

    if not needs and not PREVIEW_JS.is_file():
        # Migrate legacy hub/ catalog onto the volume once.
        if PREVIEW_JS_LEGACY.is_file():
            try:
                PREVIEW_JS.parent.mkdir(parents=True, exist_ok=True)
                PREVIEW_JS.write_bytes(PREVIEW_JS_LEGACY.read_bytes())
                if PREVIEW_META_LEGACY.is_file():
                    PREVIEW_META.write_bytes(PREVIEW_META_LEGACY.read_bytes())
            except OSError:
                needs = True
                reason = "missing"
        else:
            needs = True
            reason = "missing"

    if not needs:
        try:
            size = PREVIEW_JS.stat().st_size
        except OSError:
            size = 0
        if size < min_bytes:
            needs = True
            reason = "empty"
        else:
            try:
                head = PREVIEW_JS.read_bytes()[:120].decode("utf-8", errors="replace")
                if "PTP_DATA" not in head:
                    needs = True
                    reason = "invalid"
            except OSError:
                needs = True
                reason = "unreadable"

    meta_total = 0
    if PREVIEW_META.is_file():
        try:
            meta = json.loads(PREVIEW_META.read_text(encoding="utf-8"))
            meta_total = int((meta or {}).get("properties_total") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            meta_total = 0

    json_count = _json_properties_count()
    if not needs and json_count is not None:
        if meta_total <= 0 and json_count > 0:
            needs = True
            reason = "meta_empty"
        elif meta_total != json_count:
            needs = True
            reason = "count_mismatch"
        else:
            # Volume JSON newer than catalog → rebuild (deploy left stale image copy).
            try:
                json_mtime = PROPERTIES_JSON.stat().st_mtime
                preview_mtime = PREVIEW_JS.stat().st_mtime
                if json_mtime > preview_mtime + 1.0:
                    needs = True
                    reason = "json_newer"
            except OSError:
                pass

    if not needs:
        return {
            "ok": True,
            "rebuilt": False,
            "reason": reason,
            "properties_total": meta_total or (json_count or 0),
        }

    with _STORE_LOCK:
        projects = load_projects()
        properties = load_properties()
        if not properties:
            return {
                "ok": False,
                "rebuilt": False,
                "reason": "no_properties",
                "properties_total": 0,
            }
        write_preview_js(projects, properties)
        return {
            "ok": True,
            "rebuilt": True,
            "reason": reason,
            "properties_total": len(properties),
            "projects": len(projects),
        }


def persist(projects: list[dict], properties: list[dict]) -> None:
    with _STORE_LOCK:
        _atomic_write_text(
            projects_path(),
            json.dumps(projects, ensure_ascii=False, indent=2),
        )
        _atomic_write_text(
            properties_path(),
            json.dumps(properties, ensure_ascii=False, indent=2),
        )
        if not _e2e_data_root():
            write_sqlite(projects, properties)
            write_preview_js(projects, properties)
        # Drop short-lived load cache so next_code / health see fresh rows.
        _PROPERTIES_CACHE["data"] = None
        _PROPERTIES_CACHE["mtime"] = None
        _PROPERTIES_CACHE["at"] = 0.0
        # Co-Agent (/api/co/catalog, /api/co/match) reads the same Hub volume —
        # invalidate its cache too so admin saves show up immediately, not just
        # after the mtime-based TTL next request happens to notice.
        try:
            from src.hub.co_catalog import invalidate_co_catalog

            invalidate_co_catalog()
        except Exception:  # noqa: BLE001
            pass


def _next_code_from_list(properties: list[dict], prefix: str = "RXT") -> str:
    from src.hub.codes import next_hub_code

    return next_hub_code(
        properties,
        prefix=prefix or "RXT",
        main_csv=BASE_DIR / "data" / "main_sheet.csv",
        hub_csv=BASE_DIR / "data" / "hub_sheet_export.csv",
    )


def save_new_property(payload: dict) -> dict:
    """Append a new listing from เพิ่มทรัพย์ form → properties.json + sqlite + preview."""
    with _STORE_LOCK:
        return _save_new_property_locked(payload)


def _save_new_property_locked(payload: dict) -> dict:
    from datetime import datetime

    from src.hub.codes import code_number, format_code

    projects = load_projects()
    properties = load_properties()

    project_id = (payload.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("เลือกโครงการจาก Master ก่อนบันทึก")
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise ValueError("ไม่พบโครงการใน Master")

    prefix = (payload.get("code_prefix") or "RXT").strip().upper() or "RXT"
    raw_code = (payload.get("code") or "").strip().upper().replace(" ", "")
    # Align prefix letters with the selected type (RXT/COA) when number is present
    num = code_number(raw_code)
    if num is not None:
        code = format_code(prefix, num)
    elif raw_code:
        code = raw_code
    else:
        code = ""

    taken = {(p.get("code") or "").strip().upper() for p in properties}
    if not code or code in taken:
        # Stale form code after first save → allocate next free instead of failing
        code = _next_code_from_list(properties, prefix=prefix)
    if code in taken:
        raise ValueError(f"รหัส {code} มีอยู่แล้ว — รีเฟรชแล้วลองใหม่")

    owner_phones = payload.get("owner_phones") or []
    owner_lines = payload.get("owner_lines") or []
    owner_facebook = payload.get("owner_facebook") or []
    if isinstance(owner_phones, str):
        owner_phones = [owner_phones]
    if isinstance(owner_lines, str):
        owner_lines = [owner_lines]
    if isinstance(owner_facebook, str):
        owner_facebook = [owner_facebook]

    # Always inherit location from project master form (ทำเล + BTS)
    transit = project_transit_display(proj)
    location_ref = project_location_label(proj)
    listing_kind = "co_agent" if prefix == "COA" else "direct"
    today = datetime.now().strftime("%d/%m/%Y")

    owner_fb_urls = [u.strip() for u in owner_facebook if isinstance(u, str) and u.strip()]
    post_url = (payload.get("post_url") or "").strip()
    post_pages_url = (payload.get("post_pages_url") or "").strip()
    # Never treat owner FB as "our post"
    if post_url and post_url in owner_fb_urls:
        post_url = ""

    prop = {
        "id": str(uuid.uuid4()),
        "code": code,
        "code_prefix": prefix,
        "data_source": "hub",
        "listing_kind": listing_kind,
        "project_id": project_id,
        "project_name": proj["canonical_name"],
        "last_listed_at": today,
        "property_type": payload.get("property_type") or "Condo",
        "bedrooms": payload.get("bedrooms") or "",
        "size_sqm": payload.get("size_sqm") or "",
        "floor": payload.get("floor") or "",
        "rent_price": payload.get("rent_price") or "",
        "sale_price": payload.get("sale_price") or "",
        "source_url": payload.get("source_url") or "",
        "post_url": post_url,
        "post_pages_url": post_pages_url,
        "notes": payload.get("notes") or "",
        "import_status": "active",
        "media_status": "has_link" if post_url else "pending",
        "sheet_row": "",
        "transit_from_sheet": transit,
        "duplicate_flags": [],
        "location_ref": location_ref,
        "owner_phones": [x for x in owner_phones if x],
        "owner_lines": [x for x in owner_lines if x],
        "owner_facebook": owner_fb_urls,
        "text_th": payload.get("text_th") or "",
        "text_en": payload.get("text_en") or "",
        "raw_text": payload.get("raw_text") or "",
        "page_post_text": (payload.get("page_post_text") or "").strip(),
        "linked_ptp_code": (payload.get("linked_ptp_code") or "").strip(),
        "pet_friendly": coerce_pet_friendly(payload.get("pet_friendly")),
    }

    properties.insert(0, prop)
    proj["listing_count"] = int(proj.get("listing_count") or 0) + 1
    projects.sort(key=lambda x: (-int(x.get("listing_count") or 0), x["canonical_name"]))
    persist(projects, properties)

    # Best-effort local Hub CSV export (Google push is separate / optional)
    try:
        from src.hub.sheet_write import write_hub_export_csv
        from src.hub.codes import is_hub_owned

        write_hub_export_csv([p for p in properties if is_hub_owned(p)])
    except Exception:
        pass
    return prop


# Fields Hub edits that the main-sheet CSV rebuild often blanks or mangles.
# Always re-apply from the pre-refresh snapshot so 「ดึงชีท」cannot wipe work.
HUB_OVERLAY_FIELDS = (
    "post_url",
    "post_pages_url",
    "owner_facebook",
    "owner_phones",
    "owner_lines",
    "notes",
    "text_th",
    "text_en",
    "raw_text",
    "page_post_text",
    "media_status",
    "hub_edited_at",
)


def _stamp_hub_edited(prop: dict) -> None:
    from datetime import datetime, timezone

    prop["hub_edited_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_internal_catalog_dict(projects: list[dict], properties: list[dict]) -> dict:
    """Full catalog for authenticated Hub admin (includes private fields)."""
    from src.hub.public_projection import build_internal_catalog_payload

    flagged = sum(1 for p in properties if p.get("duplicate_flags"))
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    data_version = datetime.now().astimezone().strftime("%Y%m%d%H%M%S")
    stats = {
        "projects": len(projects),
        "properties_total": len(properties),
        "properties_active": sum(
            1 for p in properties if p.get("import_status") == "active"
        ),
        "properties_archived": sum(
            1 for p in properties if p.get("import_status") == "archived"
        ),
        "properties_needs_review": sum(
            1 for p in properties if p.get("import_status") == "needs_review"
        ),
        "properties_flagged_duplicate": flagged,
    }
    return build_internal_catalog_payload(
        projects,
        properties,
        stats=stats,
        generated_at=generated_at,
        data_version=data_version,
    )


def set_property_page_post_text(
    text: str,
    *,
    property_id: str = "",
    code: str = "",
) -> dict | None:
    """Store full Page-post caption without touching other listing fields."""
    from src.hub.property_resolve import resolve_for_action

    with _STORE_LOCK:
        properties = load_properties()
        projects = load_projects()
        res = resolve_for_action(
            properties,
            property_id=property_id,
            property_code=code,
        )
        if not res.ok or not res.record:
            return None
        prop = res.record
        prop["page_post_text"] = (text or "").strip()
        _stamp_hub_edited(prop)
        persist(projects, properties)
        return prop


def update_property(property_id: str, payload: dict) -> dict:
    """Update an existing listing from the edit form (same fields as save)."""
    with _STORE_LOCK:
        return _update_property_locked(property_id, payload)


def _update_property_locked(property_id: str, payload: dict) -> dict:
    from datetime import datetime

    from src.hub.property_resolve import find_by_id, resolve_for_action

    properties = load_properties()
    projects = load_projects()
    prop = find_by_id(properties, property_id)
    if not prop:
        res = resolve_for_action(properties, property_code=property_id)
        if not res.ok or not res.record:
            if res.error_code == "PROPERTY_CODE_AMBIGUOUS":
                raise ValueError(
                    "รหัสทรัพย์ซ้ำหลายรายการ — บันทึกด้วย property_id"
                )
            raise ValueError("ไม่พบทรัพย์")
        prop = res.record

    old_project_id = prop.get("project_id")
    project_id = (payload.get("project_id") or prop.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("เลือกโครงการจาก Master ก่อนบันทึก")
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise ValueError("ไม่พบโครงการใน Master")

    owner_phones = payload.get("owner_phones") or []
    owner_lines = payload.get("owner_lines") or []
    owner_facebook = payload.get("owner_facebook") or []
    if isinstance(owner_phones, str):
        owner_phones = [owner_phones]
    if isinstance(owner_lines, str):
        owner_lines = [owner_lines]
    if isinstance(owner_facebook, str):
        owner_facebook = [owner_facebook]

    # Location always follows project master — room-level edits cannot diverge
    transit = project_transit_display(proj)
    location_ref = project_location_label(proj)

    owner_fb_urls = [u.strip() for u in owner_facebook if isinstance(u, str) and u.strip()]
    post_url = (payload.get("post_url") if "post_url" in payload else prop.get("post_url") or "").strip()
    post_pages_url = (
        payload.get("post_pages_url") if "post_pages_url" in payload else prop.get("post_pages_url") or ""
    ).strip()
    if post_url and post_url in owner_fb_urls:
        post_url = ""

    prefix = (payload.get("code_prefix") or prop.get("code_prefix") or "RXT").strip().upper() or "RXT"
    new_code = (payload.get("code") or prop.get("code") or "").strip().upper()
    if new_code and new_code != (prop.get("code") or "").upper():
        if any((p.get("code") or "").upper() == new_code and p.get("id") != prop.get("id") for p in properties):
            raise ValueError(f"รหัส {new_code} มีอยู่แล้ว")
        prop["code"] = new_code

    prop.update(
        {
            "code_prefix": prefix,
            "listing_kind": "co_agent" if prefix == "COA" else "direct",
            "project_id": project_id,
            "project_name": proj["canonical_name"],
            "property_type": payload.get("property_type") or prop.get("property_type") or "Condo",
            "bedrooms": payload.get("bedrooms") if "bedrooms" in payload else prop.get("bedrooms") or "",
            "size_sqm": payload.get("size_sqm") if "size_sqm" in payload else prop.get("size_sqm") or "",
            "floor": payload.get("floor") if "floor" in payload else prop.get("floor") or "",
            "rent_price": payload.get("rent_price") if "rent_price" in payload else prop.get("rent_price") or "",
            "sale_price": payload.get("sale_price") if "sale_price" in payload else prop.get("sale_price") or "",
            "source_url": payload.get("source_url") if "source_url" in payload else prop.get("source_url") or "",
            "post_url": post_url,
            "post_pages_url": post_pages_url,
            "notes": payload.get("notes") if "notes" in payload else prop.get("notes") or "",
            "media_status": "has_link" if post_url else (prop.get("media_status") or "pending"),
            "transit_from_sheet": transit,
            "location_ref": location_ref,
            "owner_phones": [x for x in owner_phones if x],
            "owner_lines": [x for x in owner_lines if x],
            "owner_facebook": owner_fb_urls,
            "last_listed_at": payload.get("last_listed_at")
            or prop.get("last_listed_at")
            or datetime.now().strftime("%d/%m/%Y"),
        }
    )
    if "pet_friendly" in payload:
        prop["pet_friendly"] = coerce_pet_friendly(payload.get("pet_friendly"))
    if "text_th" in payload:
        prop["text_th"] = payload.get("text_th") or ""
    if "text_en" in payload:
        prop["text_en"] = payload.get("text_en") or ""
    if "raw_text" in payload:
        prop["raw_text"] = payload.get("raw_text") or ""
    if "page_post_text" in payload:
        prop["page_post_text"] = (payload.get("page_post_text") or "").strip()
    _stamp_hub_edited(prop)

    if old_project_id != project_id:
        for pr in projects:
            if pr["id"] == old_project_id:
                pr["listing_count"] = max(0, int(pr.get("listing_count") or 0) - 1)
            if pr["id"] == project_id:
                pr["listing_count"] = int(pr.get("listing_count") or 0) + 1
        projects.sort(key=lambda x: (-int(x.get("listing_count") or 0), x["canonical_name"]))

    persist(projects, properties)
    return prop


def update_property_links(property_id: str, payload: dict) -> dict:
    """Update our post / page links (and optional owner contact) after save."""
    with _STORE_LOCK:
        return _update_property_links_locked(property_id, payload)


def _update_property_links_locked(property_id: str, payload: dict) -> dict:
    from src.hub.property_resolve import find_by_id, resolve_for_action

    properties = load_properties()
    projects = load_projects()
    prop = find_by_id(properties, property_id)
    if not prop:
        res = resolve_for_action(properties, property_code=property_id)
        if not res.ok or not res.record:
            if res.error_code == "PROPERTY_CODE_AMBIGUOUS":
                raise ValueError(
                    "รหัสทรัพย์ซ้ำหลายรายการ — บันทึกด้วย property_id"
                )
            raise ValueError("ไม่พบทรัพย์")
        prop = res.record

    if "post_url" in payload:
        post_url = (payload.get("post_url") or "").strip()
        owners = prop.get("owner_facebook") or []
        if post_url and post_url in owners:
            raise ValueError("ลิงก์โพสเราต้องไม่ซ้ำกับลิงก์เจ้าของ")
        prop["post_url"] = post_url
        prop["media_status"] = "has_link" if post_url else (prop.get("media_status") or "pending")
    if "post_pages_url" in payload:
        prop["post_pages_url"] = (payload.get("post_pages_url") or "").strip()
    if "owner_facebook" in payload:
        fb = payload.get("owner_facebook") or []
        if isinstance(fb, str):
            fb = [x.strip() for x in fb.replace("|", ",").split(",") if x.strip()]
        prop["owner_facebook"] = [x for x in fb if x]
    if "owner_phones" in payload:
        phones = payload.get("owner_phones") or []
        if isinstance(phones, str):
            phones = [x.strip() for x in phones.replace("|", ",").split(",") if x.strip()]
        prop["owner_phones"] = [x for x in phones if x]
    if "notes" in payload:
        prop["notes"] = payload.get("notes") or ""
    _stamp_hub_edited(prop)

    persist(projects, properties)
    return prop


def find_project_by_bucket(projects: list[dict], bucket: str) -> dict | None:
    for p in projects:
        if p.get("bucket_key") == bucket:
            return p
    return None


def create_project(
    canonical_name: str,
    transit_raw: str | list[str] = "",
    *,
    zone_raw: str | list[str] | None = None,
    aliases: str | list[str] | None = None,
) -> dict:
    with _STORE_LOCK:
        return _create_project_locked(
            canonical_name,
            transit_raw,
            zone_raw=zone_raw,
            aliases=aliases,
        )


def _create_project_locked(
    canonical_name: str,
    transit_raw: str | list[str] = "",
    *,
    zone_raw: str | list[str] | None = None,
    aliases: str | list[str] | None = None,
) -> dict:
    name = (canonical_name or "").strip()
    if not name:
        raise ValueError("กรุณาระบุชื่อโครงการ")
    bucket = project_bucket(name)
    if not bucket:
        raise ValueError("ชื่อโครงการสั้นเกินไป")

    transit = parse_station_tags(transit_raw) if transit_raw else []
    zones = parse_tag_list(zone_raw) if zone_raw is not None else []
    zones = [z for z in zones if not re.match(r"^(BTS|MRT|ARL|APL)\b", z, re.I)]

    if not transit and zone_raw is None:
        # Legacy modal: free-text "ทำเล / BTS / MRT" in transit_raw only
        transit = parse_station_tags(transit_raw) or parse_tag_list(transit_raw)

    if not transit and not zones:
        raise ValueError("กรุณาระบุทำเล / BTS / MRT อย่างน้อย 1 รายการ")

    alias_list = parse_tag_list(aliases) if aliases is not None else []

    projects = load_projects()
    existing = find_project_by_bucket(projects, bucket)
    if existing:
        raise ValueError(
            f"โครงการนี้มีใน Master แล้ว: {existing['canonical_name']}"
        )

    # Prefer verified master when caller split zone/transit (projects form).
    use_verified = zone_raw is not None
    project = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ptp-project-{bucket}")),
        "bucket_key": bucket,
        "canonical_name": name,
        "aliases": alias_list,
        "transit_unverified": [] if use_verified else transit,
        "zone_unverified": [] if use_verified else [],
        "transit_verified": transit if use_verified else [],
        "zone_verified": zones if use_verified else [],
        "location_status": "verified" if use_verified else "pending_verification",
        "is_thru_thonglor": bucket == "thru_thonglor",
        "listing_count": 0,
    }
    projects.append(project)
    projects.sort(key=lambda x: (-int(x.get("listing_count") or 0), x["canonical_name"]))
    properties = load_properties()
    persist(projects, properties)
    return project


def update_project_transit(project_id: str, transit_raw: str | list[str]) -> tuple[dict, int]:
    """Replace project BTS/transit master and sync all listings."""
    return update_project_standard(project_id, transit_raw=transit_raw)


def update_project_standard(
    project_id: str,
    *,
    transit_raw: str | list[str] | None = None,
    zone_raw: str | list[str] | None = None,
    canonical_name: str | None = None,
    aliases: str | list[str] | None = None,
) -> tuple[dict, int]:
    """
    Update the project master form (ทำเล/BTS).
    This becomes the single source of truth for every room in the project,
    including rooms added later (they read from master on create).
    """
    with _STORE_LOCK:
        return _update_project_standard_locked(
            project_id,
            transit_raw=transit_raw,
            zone_raw=zone_raw,
            canonical_name=canonical_name,
            aliases=aliases,
        )


def _update_project_standard_locked(
    project_id: str,
    *,
    transit_raw: str | list[str] | None = None,
    zone_raw: str | list[str] | None = None,
    canonical_name: str | None = None,
    aliases: str | list[str] | None = None,
) -> tuple[dict, int]:
    pid = (project_id or "").strip()
    if not pid:
        raise ValueError("ไม่พบโครงการ")

    projects = load_projects()
    properties = load_properties()
    proj = next((p for p in projects if p["id"] == pid), None)
    if not proj:
        raise ValueError("ไม่พบโครงการใน Master")

    if canonical_name is not None:
        name = canonical_name.strip()
        if not name:
            raise ValueError("กรุณาระบุชื่อโครงการ")
        proj["canonical_name"] = name

    if aliases is not None:
        proj["aliases"] = parse_tag_list(aliases)

    if transit_raw is not None:
        new_tags = parse_station_tags(transit_raw) or parse_tag_list(transit_raw)
        # Promote to verified master — replace, do not merge leftovers
        proj["transit_verified"] = new_tags
        proj["transit_unverified"] = []

    if zone_raw is not None:
        zones = parse_tag_list(zone_raw)
        # keep stations out of zone field
        zones = [z for z in zones if not re.match(r"^(BTS|MRT|ARL|APL)\b", z, re.I)]
        proj["zone_verified"] = zones
        proj["zone_unverified"] = []

    if not project_transit_display(proj) and not project_zone_display(proj):
        raise ValueError("กรุณาระบุทำเล หรือ BTS / MRT อย่างน้อย 1 รายการ")

    proj["location_status"] = "verified"
    listings_updated = sync_project_listings_location_ref(proj, properties)
    persist(projects, properties)
    return proj, listings_updated
