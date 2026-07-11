"""Read/write Project Master — create projects and update shared transit."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
PROJECTS_JSON = BASE_DIR / "data" / "projects.json"
PROPERTIES_JSON = BASE_DIR / "data" / "properties.json"
DB_PATH = BASE_DIR / "data" / "hub.db"
PREVIEW_JS = BASE_DIR / "hub" / "preview-data.js"


def norm_key(name: str) -> str:
    """Normalize for bucket / identity — use outer name, drop parenthetical alias."""
    n = name.lower().strip()
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"[()（）]", " ", n)
    n = re.sub(r"[^a-z0-9ก-๙]", "", n)
    return n


def norm_search_key(name: str) -> str:
    """Normalize for search — keep Thai/EN inside parentheses."""
    n = name.lower().strip()
    n = re.sub(r"[()（）]", " ", n)
    n = re.sub(r"[^a-z0-9ก-๙]", "", n)
    return n


def project_bucket(name: str) -> str | None:
    if not name or not name.strip():
        return None
    k = norm_key(name)
    if len(k) < 3:
        return None
    if "thru" in k and "thonglor" in k:
        return "thru_thonglor"
    if "lifeasoke" in k or k.startswith("lifeasoke"):
        if "hype" in k:
            return "life_asoke_hype"
        if "rama9" in k:
            return "life_asoke_rama9"
        return "life_asoke"
    return k


def parse_transit_input(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        parts = raw
    else:
        parts = re.split(r"[,，\n]", raw or "")
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        label = re.sub(r"\s+", " ", (p or "").strip())
        if not label or len(label) > 80:
            continue
        k = norm_key(label)
        if k and k not in seen:
            seen.add(k)
            out.append(label)
    return out


def dedupe_transit(tags: list[str]) -> list[str]:
    return parse_transit_input(tags)


def load_projects() -> list[dict]:
    if not PROJECTS_JSON.exists():
        return []
    return json.loads(PROJECTS_JSON.read_text(encoding="utf-8"))


def load_properties() -> list[dict]:
    if not PROPERTIES_JSON.exists():
        return []
    return json.loads(PROPERTIES_JSON.read_text(encoding="utf-8"))


def project_transit_display(proj: dict) -> list[str]:
    verified = proj.get("transit_verified") or []
    if verified:
        return dedupe_transit(verified)
    return dedupe_transit(proj.get("transit_unverified") or [])


def sync_project_listings_location_ref(project: dict, properties: list[dict]) -> int:
    loc = ", ".join(project_transit_display(project)[:6])
    updated = 0
    for prop in properties:
        if prop.get("project_id") != project["id"]:
            continue
        if prop.get("location_ref") != loc:
            prop["location_ref"] = loc
            updated += 1
    return updated


def write_sqlite(projects: list[dict], properties: list[dict]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
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


def write_preview_js(projects: list[dict], properties: list[dict]) -> None:
    project_map = {p["id"]: p for p in projects}
    flagged = sum(1 for p in properties if p.get("duplicate_flags"))
    payload = {
        "projects": projects,
        "properties": properties,
        "project_map": project_map,
        "stats": {
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
        },
    }
    PREVIEW_JS.write_text(
        "// Auto-generated — do not edit\n"
        f"window.PTP_DATA = {json.dumps(payload, ensure_ascii=False, indent=2)};\n",
        encoding="utf-8",
    )


def persist(projects: list[dict], properties: list[dict]) -> None:
    PROJECTS_JSON.write_text(
        json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    PROPERTIES_JSON.write_text(
        json.dumps(properties, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_sqlite(projects, properties)
    write_preview_js(projects, properties)


def _next_rxt_from_list(properties: list[dict]) -> str:
    max_num = 0
    for p in properties:
        code = (p.get("code") or "").upper()
        if code.startswith("RXT"):
            try:
                max_num = max(max_num, int(code[3:]))
            except ValueError:
                pass
    return f"RXT{max_num + 1:04d}"


def save_new_property(payload: dict) -> dict:
    """Append a new listing from เพิ่มทรัพย์ form → properties.json + sqlite + preview."""
    from datetime import datetime

    projects = load_projects()
    properties = load_properties()

    project_id = (payload.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("เลือกโครงการจาก Master ก่อนบันทึก")
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise ValueError("ไม่พบโครงการใน Master")

    code = (payload.get("code") or "").strip().upper()
    if not code:
        code = _next_rxt_from_list(properties)
    if any((p.get("code") or "").upper() == code for p in properties):
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

    transit = payload.get("transit_tags") or []
    if isinstance(transit, str):
        transit = parse_transit_input(transit)
    location_ref = ", ".join(transit[:6]) if transit else ", ".join(project_transit_display(proj)[:6])

    prefix = (payload.get("code_prefix") or "RXT").strip().upper() or "RXT"
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
    }

    properties.insert(0, prop)
    proj["listing_count"] = int(proj.get("listing_count") or 0) + 1
    projects.sort(key=lambda x: (-int(x.get("listing_count") or 0), x["canonical_name"]))
    persist(projects, properties)
    return prop


def update_property(property_id: str, payload: dict) -> dict:
    """Update an existing listing from the edit form (same fields as save)."""
    from datetime import datetime

    properties = load_properties()
    projects = load_projects()
    prop = next(
        (p for p in properties if p.get("id") == property_id or p.get("code") == property_id),
        None,
    )
    if not prop:
        raise ValueError("ไม่พบทรัพย์")

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

    transit = payload.get("transit_tags")
    if transit is None:
        transit = prop.get("transit_from_sheet") or []
    if isinstance(transit, str):
        transit = parse_transit_input(transit)
    location_ref = (
        ", ".join(transit[:6])
        if transit
        else ", ".join(project_transit_display(proj)[:6])
    )

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
    if "text_th" in payload:
        prop["text_th"] = payload.get("text_th") or ""
    if "text_en" in payload:
        prop["text_en"] = payload.get("text_en") or ""
    if "raw_text" in payload:
        prop["raw_text"] = payload.get("raw_text") or ""

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
    properties = load_properties()
    projects = load_projects()
    prop = next((p for p in properties if p.get("id") == property_id or p.get("code") == property_id), None)
    if not prop:
        raise ValueError("ไม่พบทรัพย์")

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

    persist(projects, properties)
    return prop


def find_project_by_bucket(projects: list[dict], bucket: str) -> dict | None:
    for p in projects:
        if p.get("bucket_key") == bucket:
            return p
    return None


def create_project(canonical_name: str, transit_raw: str | list[str]) -> dict:
    name = (canonical_name or "").strip()
    if not name:
        raise ValueError("กรุณาระบุชื่อโครงการ")
    bucket = project_bucket(name)
    if not bucket:
        raise ValueError("ชื่อโครงการสั้นเกินไป")

    transit = parse_transit_input(transit_raw)
    if not transit:
        raise ValueError("กรุณาระบุทำเล / BTS / MRT อย่างน้อย 1 รายการ")

    projects = load_projects()
    existing = find_project_by_bucket(projects, bucket)
    if existing:
        raise ValueError(
            f"โครงการนี้มีใน Master แล้ว: {existing['canonical_name']}"
        )

    project = {
        "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ptp-project-{bucket}")),
        "bucket_key": bucket,
        "canonical_name": name,
        "aliases": [],
        "transit_unverified": transit,
        "zone_unverified": [],
        "transit_verified": [],
        "zone_verified": [],
        "location_status": "pending_verification",
        "is_thru_thonglor": bucket == "thru_thonglor",
        "listing_count": 0,
    }
    projects.append(project)
    projects.sort(key=lambda x: (-int(x.get("listing_count") or 0), x["canonical_name"]))
    properties = load_properties()
    persist(projects, properties)
    return project


def update_project_transit(project_id: str, transit_raw: str | list[str]) -> tuple[dict, int]:
    pid = (project_id or "").strip()
    if not pid:
        raise ValueError("ไม่พบโครงการ")

    new_tags = parse_transit_input(transit_raw)
    if not new_tags:
        raise ValueError("กรุณาระบุทำเล / BTS / MRT อย่างน้อย 1 รายการ")

    projects = load_projects()
    properties = load_properties()
    proj = next((p for p in projects if p["id"] == pid), None)
    if not proj:
        raise ValueError("ไม่พบโครงการใน Master")

    if proj.get("transit_verified"):
        merged = dedupe_transit((proj.get("transit_verified") or []) + new_tags)
        proj["transit_verified"] = merged
    else:
        proj["transit_unverified"] = new_tags

    listings_updated = sync_project_listings_location_ref(proj, properties)
    persist(projects, properties)
    return proj, listings_updated
