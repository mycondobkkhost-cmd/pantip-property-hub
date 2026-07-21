#!/usr/bin/env python3
"""Build Project Master + import properties from legacy Google Sheet CSV."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

CSV_PATH = BASE_DIR / "data" / "main_sheet.csv"
DB_PATH = BASE_DIR / "data" / "hub.db"
PROJECTS_JSON = BASE_DIR / "data" / "projects.json"
PROPERTIES_JSON = BASE_DIR / "data" / "properties.json"
PREVIEW_JS = BASE_DIR / "hub" / "preview-data.js"

CUTOFF = datetime(2025, 10, 7)  # 9 months before Jul 7 2026

# Canonical overrides — never auto-merge these
CANONICAL_OVERRIDES: dict[str, str] = {
    "life_asoke_hype": "Life Asoke Hype (ไลฟ์ อโศก ไฮป์)",
    "life_asoke_rama9": "Life Asoke Rama 9 (ไลฟ์ อโศก - พระราม 9)",
    "life_asoke": "Life Asoke (ไลฟ์ อโศก)",
    "thru_thonglor": "Thru Thonglor (ทรู ทองหล่อ)",
}

from src.hub.project_identity import resolve_bucket as _resolve_bucket  # noqa: E402


def norm_key(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"[^a-z0-9ก-๙]", "", n)
    return n


def is_thru_thonglor(name: str) -> bool:
    k = norm_key(name)
    return "thru" in k and "thonglor" in k


def project_bucket(name: str) -> str | None:
    """Prefer persistent alias map + stronger soft-norm identity."""
    return _resolve_bucket(name)

def parse_date(s: str) -> datetime | None:
    s = (s or "").strip()
    if not s or s.lower() == "available":
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2500 if y >= 50 else 2600
            y -= 543
        elif y > 2400:
            y -= 543
        try:
            return datetime(y, mo, d)
        except ValueError:
            return None
    return None


def parse_transit_reference(raw: str) -> list[str]:
    """Sheet transit — explode compounds into atomic station labels when possible."""
    if not raw:
        return []
    try:
        from src.hub.project_location_enrich import extract_stations

        found = extract_stations([raw])
        if found:
            return found[:8]
    except Exception:  # noqa: BLE001
        pass

    # Fallback: split compounds, keep rail-looking fragments
    tags: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,，\n/,|]| และ ", raw):
        p = re.sub(r"\s+", " ", (part or "").strip())
        if not p or len(p) > 80:
            continue
        if not (p.upper().startswith(("BTS ", "MRT ", "ARL ", "AIRPORT", "APL ")) or "BTS" in p or "MRT" in p):
            continue
        k = re.sub(r"[^a-z0-9ก-๙]", "", p.lower())
        if k in seen:
            continue
        seen.add(k)
        tags.append(p[:60])
    return tags[:8]


def is_code_only_row(row: dict[str, str]) -> bool:
    code = row.get("code", "")
    if not code.startswith("PTP"):
        return False
    fields = [
        row.get("project", ""),
        row.get("ptype", ""),
        row.get("beds", ""),
        row.get("size", ""),
        row.get("floor", ""),
        row.get("rent", ""),
        row.get("sale", ""),
        row.get("source", ""),
        row.get("post_link", ""),
        row.get("notes", ""),
        row.get("transit", ""),
    ]
    acquired = row.get("acquired_raw", "")
    avail = row.get("available_raw", "").lower()
    has_date = bool(acquired) and avail != "available"
    return not any(fields) and not has_date


def load_rows() -> list[dict[str, str]]:
    with open(CSV_PATH, encoding="utf-8") as f:
        sheet = list(csv.reader(f))
    cols = {h.strip(): i for i, h in enumerate(sheet[0])}

    def col(r: list[str], name: str) -> str:
        i = cols.get(name)
        return r[i].strip() if i is not None and i < len(r) else ""

    out: list[dict[str, str]] = []
    for idx, r in enumerate(sheet[1:], start=2):
        code = col(r, "รหัสทรัพย์").upper().replace(" ", "")
        out.append(
            {
                "row": str(idx),
                "code": code,
                "acquired_raw": col(r, "วันที่รับเข้า"),
                "available_raw": col(r, "วันที่ว่าง"),
                "project": col(r, "โครงการ"),
                "ptype": col(r, "ประเภท"),
                "beds": col(r, "ห้องนอน/ห้องน้ำ"),
                "size": col(r, "ขนาด"),
                "floor": col(r, "ชั้น"),
                "rent": col(r, "ราคาเช่า"),
                "sale": col(r, "ราคาขาย"),
                "transit": col(r, "สถานีรถไฟฟ้า"),
                "source": col(r, "ลิ้งค์ต้นโพสต์"),
                "post_link": col(r, "ลิ้งค์โพส"),
                "post_pages": col(r, "ลิ้งค์โพส Pages") or col(r, "ลิ้งค์โพส Pages "),
                "notes": col(r, "หมายเหตุ"),
                "owner_fb": col(r, "เฟสเจ้าของ"),
            }
        )
    return out


def build_projects(all_rows: list[dict[str, str]]) -> dict[str, dict]:
    """Aggregate every project name ever seen into Project Master buckets."""
    buckets: dict[str, Counter] = defaultdict(Counter)
    transit_refs: dict[str, Counter] = defaultdict(Counter)

    for row in all_rows:
        name = row.get("project", "").strip()
        if not name:
            continue
        bucket = project_bucket(name)
        if not bucket:
            continue
        buckets[bucket][name] += 1
        for t in parse_transit_reference(row.get("transit", "")):
            transit_refs[bucket][t] += 1

    projects: dict[str, dict] = {}
    for bucket, name_counts in buckets.items():
        pid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ptp-project-{bucket}"))
        if bucket in CANONICAL_OVERRIDES:
            canonical = CANONICAL_OVERRIDES[bucket]
        else:
            canonical = name_counts.most_common(1)[0][0]

        aliases = sorted(name_counts.keys(), key=lambda x: (-name_counts[x], x))
        if aliases and aliases[0] == canonical:
            aliases = aliases[1:]

        unverified_transit = [t for t, _ in transit_refs[bucket].most_common(10)]

        projects[bucket] = {
            "id": pid,
            "bucket_key": bucket,
            "canonical_name": canonical,
            "aliases": aliases,
            "transit_unverified": unverified_transit,
            "zone_unverified": [],
            "transit_verified": [],
            "zone_verified": [],
            "location_status": "pending_verification",
            "is_thru_thonglor": bucket == "thru_thonglor",
            "listing_count": sum(name_counts.values()),
        }
    return projects


def is_google_drive_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return "drive.google.com" in u or "docs.google.com" in u


def has_price(raw: str) -> bool:
    v = (raw or "").strip()
    return bool(v) and v not in {"-", "—", "0"}


def usable_property(row: dict[str, str]) -> bool:
    """Keep complete rows, or partial rows that already have a source link / project."""
    has_project = bool(row.get("project"))
    priced = has_price(row.get("rent", "")) or has_price(row.get("sale", ""))
    has_source = bool(row.get("source"))

    if has_project and priced:
        if not has_source:
            return is_thru_thonglor(row["project"])
        return True

    # แถวที่เริ่มกรอกแล้ว (มีลิงก์ต้นทาง หรือมีชื่อโครงการ) — เก็บเป็น needs_review
    if has_source or has_project:
        return True
    return False


def is_incomplete_property(row: dict[str, str]) -> bool:
    """True when row is importable but missing project or price."""
    has_project = bool(row.get("project"))
    priced = has_price(row.get("rent", "")) or has_price(row.get("sale", ""))
    return not (has_project and priced)


def normalize_source_url(url: str) -> str:
    u = (url or "").strip().lower()
    if not u:
        return ""
    return u.split("?")[0].rstrip("/")


def price_digits(raw: str) -> str:
    return re.sub(r"[^\d]", "", raw or "")


def relist_signature(prop: dict) -> tuple[str, ...]:
    return (
        prop.get("project_id", ""),
        (prop.get("bedrooms") or "").lower().strip(),
        price_digits(prop.get("rent_price", "")),
        price_digits(prop.get("sale_price", "")),
        re.sub(r"[^\d.]", "", prop.get("size_sqm") or "")[:8],
    )


def annotate_duplicates(properties: list[dict]) -> Counter:
    """Mark probable duplicates — still imported, flagged in UI."""
    stats: Counter = Counter()
    by_code: dict[str, list[str]] = defaultdict(list)
    by_url: dict[str, list[str]] = defaultdict(list)
    by_relist: dict[tuple[str, ...], list[str]] = defaultdict(list)

    for prop in properties:
        by_code[prop["code"]].append(prop["id"])
        url = normalize_source_url(prop.get("source_url", ""))
        if url:
            by_url[url].append(prop["id"])
        sig = relist_signature(prop)
        if sig[0]:
            by_relist[sig].append(prop["id"])

    dup_code = {pid for ids in by_code.values() if len(ids) > 1 for pid in ids}
    dup_url = {pid for ids in by_url.values() if len(ids) > 1 for pid in ids}
    dup_relist = {pid for ids in by_relist.values() if len(ids) > 1 for pid in ids}

    for prop in properties:
        flags: list[str] = []
        pid = prop["id"]
        if pid in dup_code:
            flags.append("code")
        if pid in dup_url:
            flags.append("url")
        if pid in dup_relist:
            flags.append("relist")

        prop["duplicate_flags"] = flags
        transit = prop.get("transit_from_sheet") or []
        prop["location_ref"] = ", ".join(transit) if transit else ""

        if flags:
            stats["properties_flagged"] += 1
        if "code" in flags:
            stats["dup_code_rows"] += 1
        if "url" in flags:
            stats["dup_url_rows"] += 1
        if "relist" in flags:
            stats["dup_relist_rows"] += 1

    return stats


def build_properties(
    rows: list[dict[str, str]], projects: dict[str, dict]
) -> tuple[list[dict], dict]:
    bucket_to_id = {p["bucket_key"]: p["id"] for p in projects.values()}
    properties: list[dict] = []
    stats = Counter()

    for row in rows:
        if is_code_only_row(row):
            stats["code_only_dropped"] += 1
            continue

        code = row.get("code", "")
        if not code.startswith("PTP"):
            stats["non_ptp_skipped"] += 1
            continue

        if not usable_property(row):
            stats["incomplete_skipped"] += 1
            continue

        if is_google_drive_url(row.get("post_link", "")) or is_google_drive_url(
            row.get("source", "")
        ):
            stats["drive_dropped"] += 1
            continue

        acquired = parse_date(row.get("acquired_raw", ""))
        bucket = project_bucket(row["project"])
        project_id = bucket_to_id.get(bucket or "", "")
        incomplete = is_incomplete_property(row)

        if incomplete:
            import_status = "needs_review"
            stats["import_needs_review"] += 1
            stats["partial_imported"] += 1
        elif acquired and acquired >= CUTOFF:
            import_status = "active"
            stats["import_active"] += 1
        elif acquired:
            import_status = "archived"
            stats["import_archived"] += 1
        else:
            import_status = "needs_review"
            stats["import_needs_review"] += 1

        post = row.get("post_link", "")
        post_pages = row.get("post_pages", "")
        media_status = "has_link" if post.startswith("http") else "none"

        properties.append(
            {
                "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ptp-{code}-{row['row']}")),
                "code": code,
                "code_prefix": "PTP",
                "data_source": "sheet",
                "listing_kind": "direct",
                "project_id": project_id,
                "project_name": row["project"],
                "last_listed_at": acquired.strftime("%d/%m/%Y") if acquired else "",
                "property_type": row.get("ptype", ""),
                "bedrooms": row.get("beds", ""),
                "size_sqm": row.get("size", ""),
                "floor": row.get("floor", ""),
                "rent_price": row.get("rent", ""),
                "sale_price": row.get("sale", ""),
                "source_url": row.get("source", ""),
                "post_url": post,
                "post_pages_url": post_pages,
                "notes": row.get("notes", ""),
                "import_status": import_status,
                "media_status": media_status,
                "sheet_row": row["row"],
                "transit_from_sheet": parse_transit_reference(row.get("transit", "")),
            }
        )

    return properties, stats


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
        CREATE INDEX idx_properties_status ON properties(import_status);
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
                json.dumps(p["aliases"], ensure_ascii=False),
                json.dumps(p["transit_unverified"], ensure_ascii=False),
                json.dumps(p["transit_verified"], ensure_ascii=False),
                json.dumps(p["zone_verified"], ensure_ascii=False),
                p["location_status"],
                1 if p["is_thru_thonglor"] else 0,
                p["listing_count"],
            ),
        )

    for prop in properties:
        conn.execute(
            """
            INSERT INTO properties VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                prop["id"],
                prop["code"],
                prop["code_prefix"],
                prop["listing_kind"],
                prop["project_id"],
                prop["last_listed_at"],
                prop["property_type"],
                prop["bedrooms"],
                prop["size_sqm"],
                prop["floor"],
                prop["rent_price"],
                prop["sale_price"],
                prop["source_url"],
                prop["post_url"],
                prop["post_pages_url"],
                prop["notes"],
                prop["import_status"],
                prop["media_status"],
                int(prop["sheet_row"]),
            ),
        )

    conn.commit()
    conn.close()


def write_preview_js(projects: list[dict], properties: list[dict]) -> None:
    project_map = {p["id"]: p for p in projects}
    flagged = sum(1 for p in properties if p.get("duplicate_flags"))

    PREVIEW_JS.write_text(
        "// Auto-generated by scripts/build_master.py — do not edit\n"
        f"window.PTP_DATA = {json.dumps({'projects': projects, 'properties': properties, 'project_map': project_map, 'stats': {'projects': len(projects), 'properties_total': len(properties), 'properties_active': sum(1 for p in properties if p['import_status'] == 'active'), 'properties_archived': sum(1 for p in properties if p['import_status'] == 'archived'), 'properties_needs_review': sum(1 for p in properties if p['import_status'] == 'needs_review'), 'properties_flagged_duplicate': flagged}}, ensure_ascii=False, indent=2)};\n",
        encoding="utf-8",
    )


def rebuild_from_csv() -> dict:
    """Rebuild projects/properties/preview from data/main_sheet.csv. Returns summary stats."""
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Missing {CSV_PATH} — download sheet CSV first")

    rows = load_rows()
    project_dict = build_projects(rows)
    projects = sorted(project_dict.values(), key=lambda x: -x["listing_count"])
    properties, stats = build_properties(rows, project_dict)
    dup_stats = annotate_duplicates(properties)

    PROJECTS_JSON.write_text(
        json.dumps(projects, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    PROPERTIES_JSON.write_text(
        json.dumps(properties, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_sqlite(projects, properties)
    write_preview_js(projects, properties)

    active = sum(1 for p in properties if p["import_status"] == "active")
    codes = []
    for p in properties:
        m = re.search(r"PTP(\d+)", (p.get("code") or "").upper())
        if m:
            codes.append(int(m.group(1)))
    sheet_codes = []
    for row in rows:
        m = re.search(r"PTP(\d+)", (row.get("code") or "").upper())
        if m:
            sheet_codes.append(int(m.group(1)))
    return {
        "projects": len(projects),
        "properties_total": len(properties),
        "properties_active": active,
        "properties_archived": stats["import_archived"],
        "properties_needs_review": stats["import_needs_review"],
        "properties_flagged_duplicate": dup_stats["properties_flagged"],
        "drive_dropped": stats["drive_dropped"],
        "code_only_dropped": stats["code_only_dropped"],
        "incomplete_skipped": stats["incomplete_skipped"],
        "partial_imported": stats["partial_imported"],
        "newest_imported_code": f"PTP{max(codes)}" if codes else "",
        "newest_sheet_code": f"PTP{max(sheet_codes)}" if sheet_codes else "",
    }


def main() -> None:
    summary = rebuild_from_csv()
    print("=== build_master.py complete ===")
    print(f"Projects in master: {summary['projects']}")
    print(f"Properties total (after filters): {summary['properties_total']}")
    print(f"  active (9 mo): {summary['properties_active']}")
    print(f"  archived: {summary['properties_archived']}")
    print(f"  needs_review: {summary['properties_needs_review']}")
    print(f"  flagged duplicate: {summary['properties_flagged_duplicate']}")
    print(f"  drive dropped: {summary['drive_dropped']}")
    print(f"  code_only dropped: {summary['code_only_dropped']}")
    print(f"  incomplete skipped: {summary['incomplete_skipped']}")
    print(f"Written: {DB_PATH}")
    print(f"Written: {PREVIEW_JS}")


if __name__ == "__main__":
    main()
