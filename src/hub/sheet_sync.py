"""Download Google Sheet CSV + rebuild Property Hub master data."""

from __future__ import annotations

import importlib.util
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MAIN_CSV = BASE_DIR / "data" / "main_sheet.csv"
WAIT_CSV = BASE_DIR / "data" / "wait_post_sheet.csv"

try:
    from src.hub.env_load import load_hub_env

    load_hub_env()
except Exception:
    pass


def _build_overlay_snapshots(properties: list[dict]) -> tuple[dict[str, dict], dict[str, dict], set[str]]:
    """Build id-keyed and code-keyed Hub overlay maps; skip ambiguous codes for code-only."""
    from src.hub.project_store import HUB_OVERLAY_FIELDS
    from src.hub.property_resolve import overlay_blocked_codes

    overlay_by_id: dict[str, dict] = {}
    overlay_by_code: dict[str, dict] = {}
    blocked = overlay_blocked_codes(properties)
    for p in properties:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "").strip()
        code = (p.get("code") or "").strip().upper()
        snap = {k: p.get(k) for k in HUB_OVERLAY_FIELDS if k in p}
        if not (
            snap.get("hub_edited_at")
            or any(
                snap.get(k) not in ("", None, [], {})
                for k in HUB_OVERLAY_FIELDS
                if k != "hub_edited_at"
            )
        ):
            continue
        if pid:
            overlay_by_id[pid] = snap
        if code and code not in blocked:
            overlay_by_code[code] = snap
    return overlay_by_id, overlay_by_code, blocked


def _apply_overlay_snapshots(
    properties: list[dict],
    *,
    overlay_by_id: dict[str, dict],
    overlay_by_code: dict[str, dict],
    blocked_codes: set[str],
) -> int:
    """Re-apply Hub edits after sheet rebuild — prefer property_id, never ambiguous code-only."""
    from src.hub.project_store import HUB_OVERLAY_FIELDS

    restored_overlay = 0

    def _blank(val) -> bool:
        return val in ("", None, [], {})

    for p in properties:
        pid = str(p.get("id") or "").strip()
        code = (p.get("code") or "").strip().upper()
        snap = overlay_by_id.get(pid)
        if not snap and code and code not in blocked_codes:
            snap = overlay_by_code.get(code)
        if not snap:
            continue
        changed = False
        stamped = bool(snap.get("hub_edited_at"))
        for key in HUB_OVERLAY_FIELDS:
            if key not in snap:
                continue
            old = snap.get(key)
            new = p.get(key)
            if stamped:
                if new != old:
                    p[key] = old
                    changed = True
            elif _blank(new) and not _blank(old):
                p[key] = old
                changed = True
        if changed:
            restored_overlay += 1
    return restored_overlay


def _load_build_master():
    path = BASE_DIR / "scripts" / "build_master.py"
    spec = importlib.util.spec_from_file_location("build_master", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("โหลด build_master.py ไม่ได้")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sheet_id_from_url(url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url or "")
    return m.group(1) if m else None


def _gid_from_url(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "gid" in qs and qs["gid"]:
        return qs["gid"][0]
    m = re.search(r"[#&]gid=([0-9]+)", url)
    return m.group(1) if m else None


def resolve_csv_export_url(
    *,
    explicit_url: str = "",
    spreadsheet_id: str = "",
    sheet_name: str = "",
    gid: str = "",
) -> str | None:
    """Prefer an explicit export/share URL; otherwise build from sheet id + gid/name."""
    explicit = (explicit_url or "").strip()
    if explicit:
        if "export?format=csv" in explicit or "tqx=out:csv" in explicit:
            return explicit
        sid = _sheet_id_from_url(explicit) or spreadsheet_id
        if not sid:
            return explicit
        found_gid = _gid_from_url(explicit) or gid
        if found_gid:
            return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={found_gid}"
        if sheet_name:
            return (
                f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq"
                f"?tqx=out:csv&sheet={quote(sheet_name)}"
            )
        return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv"

    sid = (spreadsheet_id or "").strip()
    if not sid or sid.startswith("your_"):
        return None
    if gid:
        return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"
    if sheet_name:
        return (
            f"https://docs.google.com/spreadsheets/d/{sid}/gviz/tq"
            f"?tqx=out:csv&sheet={quote(sheet_name)}"
        )
    return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv"


def download_csv(url: str, dest: Path, timeout: int = 90) -> int:
    """Download CSV bytes to dest. Returns byte size written."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "PropertyHubSheetSync/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read()
    except urllib.error.HTTPError as exc:
        raise ValueError(f"ดึงชีทไม่สำเร็จ (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"เชื่อมต่อ Google Sheets ไม่ได้: {exc.reason}") from exc

    head = text[:200].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        raise ValueError(
            "ดึงชีทไม่ได้ — ชีทอาจเป็นส่วนตัว "
            "ให้แชร์「Anyone with the link can view」หรือใส่ลิงก์ Export CSV ใน env"
        )
    if b"," not in text[:4000] and "รหัส".encode("utf-8") not in text[:4000]:
        sample = text[:800].decode("utf-8", errors="ignore")
        if "http" not in sample.lower():
            raise ValueError("ไฟล์ที่ดาวน์โหลดไม่ใช่ CSV ของชีท")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(text)
    return len(text)


def download_sheet_via_service_account(
    *,
    spreadsheet_id: str,
    dest: Path,
    sheet_name: str = "",
    gid: str = "",
) -> int:
    """Pull a worksheet via Service Account (private sheets). Returns bytes written.

    Merges FORMULA + FORMATTED renders so ``=HYPERLINK("url","label")`` cells
    keep the real URL instead of only the short display label.
    """
    import csv
    import io

    from src.hub.sheet_links import merge_formula_and_formatted
    from src.hub.sheet_write import _gspread_client

    sid = (spreadsheet_id or "").strip()
    if not sid:
        raise ValueError("ไม่มี spreadsheet_id สำหรับดึงด้วย Service Account")

    client = _gspread_client()
    ss = client.open_by_key(sid)
    ws = None
    if gid:
        try:
            ws = ss.get_worksheet_by_id(int(gid))
        except Exception:
            ws = None
    if ws is None and sheet_name:
        ws = ss.worksheet(sheet_name)
    if ws is None:
        ws = ss.get_worksheet(0)

    try:
        formula_rows = ws.get_all_values(value_render_option="FORMULA")
        formatted_rows = ws.get_all_values(value_render_option="FORMATTED_VALUE")
        values = merge_formula_and_formatted(formula_rows, formatted_rows)
    except TypeError:
        # Older gspread without value_render_option kw
        values = ws.get_all_values()
    buf = io.StringIO()
    csv.writer(buf).writerows(values)
    text = buf.getvalue().encode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(text)
    return len(text)


def fetch_spreadsheet_title(spreadsheet_id: str, timeout: int = 20) -> str:
    """Best-effort public title from htmlview (no auth)."""
    sid = (spreadsheet_id or "").strip()
    if not sid:
        return ""
    url = f"https://docs.google.com/spreadsheets/d/{sid}/htmlview"
    req = urllib.request.Request(url, headers={"User-Agent": "PropertyHubSheetSync/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""
    m = re.search(r"<title>([^<]+)</title>", html, re.I)
    if not m:
        return ""
    title = m.group(1).replace(" - Google ไดรฟ์", "").replace(" - Google Drive", "").strip()
    return title


def _env(*keys: str) -> str:
    for k in keys:
        v = (os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def remote_sheet_source_configured() -> bool:
    """True when MAIN_SHEET_CSV_URL / SOURCE sheet id can resolve to a download URL."""
    source_id = _env(
        "SOURCE_GOOGLE_SHEETS_ID",
        "MAIN_GOOGLE_SHEETS_ID",
        "HUB_SOURCE_GOOGLE_SHEETS_ID",
    )
    url = resolve_csv_export_url(
        explicit_url=_env("MAIN_SHEET_CSV_URL", "HUB_MAIN_SHEET_CSV_URL"),
        spreadsheet_id=source_id,
        sheet_name=_env("MAIN_SHEET_NAME", "HUB_MAIN_SHEET_NAME") or "ชีตสำหรับทำงาน",
        gid=_env("MAIN_SHEET_GID", "HUB_MAIN_SHEET_GID") or "0",
    )
    return bool(url)


def refresh_main_sheet(*, csv_url: str = "", rebuild: bool = True) -> dict:
    """Download main sheet CSV, rebuild PTP master, preserve Hub-owned (RXT/COA) rows."""
    import json

    from src.hub.codes import is_hub_owned
    from src.hub.project_store import load_projects, load_properties, persist

    # ดึงเข้าแอป = ชีทจริง (SOURCE_*) · อย่าใช้ GOOGLE_SHEETS_ID ที่ไว้ซิงค์กลับทดลอง
    source_id = _env(
        "SOURCE_GOOGLE_SHEETS_ID",
        "MAIN_GOOGLE_SHEETS_ID",
        "HUB_SOURCE_GOOGLE_SHEETS_ID",
    )
    url = resolve_csv_export_url(
        explicit_url=csv_url or _env("MAIN_SHEET_CSV_URL", "HUB_MAIN_SHEET_CSV_URL"),
        spreadsheet_id=source_id,
        sheet_name=_env("MAIN_SHEET_NAME", "HUB_MAIN_SHEET_NAME") or "ชีตสำหรับทำงาน",
        gid=_env("MAIN_SHEET_GID", "HUB_MAIN_SHEET_GID") or "0",
    )

    # Snapshot Hub-owned rows / verified locations before rebuild.
    # Fresh snapshot is taken again under the store lock immediately before
    # rebuild so adds that landed during the (slow) CSV download are kept.
    preserved: list[dict] = []
    preserved_loc_by_bucket: dict[str, dict] = {}
    overlay_by_id: dict[str, dict] = {}
    overlay_by_code: dict[str, dict] = {}
    overlay_blocked: set[str] = set()
    try:
        props_snapshot = load_properties()
        preserved = [dict(p) for p in props_snapshot if is_hub_owned(p)]
        overlay_by_id, overlay_by_code, overlay_blocked = _build_overlay_snapshots(props_snapshot)
    except Exception:
        preserved = []
        overlay_by_id = {}
        overlay_by_code = {}
        overlay_blocked = set()
    try:
        for proj in load_projects():
            bucket = proj.get("bucket_key") or ""
            if not bucket:
                continue
            src = proj.get("location_source") or ""
            if src == "livinginsider" or src.startswith("livinginsider+") or (
                proj.get("transit_verified") or proj.get("zone_verified")
            ):
                preserved_loc_by_bucket[bucket] = {
                    "transit_verified": list(proj.get("transit_verified") or []),
                    "zone_verified": list(proj.get("zone_verified") or []),
                    "transit_unverified": list(proj.get("transit_unverified") or []),
                    "zone_unverified": list(proj.get("zone_unverified") or []),
                    "location_status": proj.get("location_status") or "pending_verification",
                    "location_source": proj.get("location_source") or "",
                    "living_zone": proj.get("living_zone") or "",
                    "living_project_url": proj.get("living_project_url") or "",
                }
    except Exception:
        preserved_loc_by_bucket = {}

    downloaded = False
    download_error = ""
    bytes_written = 0
    download_via = ""
    sheet_name = _env("MAIN_SHEET_NAME", "HUB_MAIN_SHEET_NAME") or "ชีตสำหรับทำงาน"
    sheet_gid = _env("MAIN_SHEET_GID", "HUB_MAIN_SHEET_GID") or "0"
    if url:
        try:
            bytes_written = download_csv(url, MAIN_CSV)
            downloaded = True
            download_via = "public_csv"
        except Exception as exc:  # noqa: BLE001
            download_error = str(exc)

    # Private sheets (shared only with SA) cannot use export CSV URLs.
    if not downloaded and source_id and not source_id.startswith("your_"):
        try:
            bytes_written = download_sheet_via_service_account(
                spreadsheet_id=source_id,
                dest=MAIN_CSV,
                sheet_name=sheet_name,
                gid=sheet_gid,
            )
            downloaded = True
            download_via = "service_account"
            if download_error:
                download_error = f"{download_error} → fallback SA ok"
        except Exception as exc:  # noqa: BLE001
            sa_err = f"Service Account pull: {exc}"
            download_error = f"{download_error} · {sa_err}" if download_error else sa_err

    if not MAIN_CSV.exists():
        raise ValueError(
            download_error
            or "ไม่พบ data/main_sheet.csv และยังไม่ได้ตั้ง MAIN_SHEET_CSV_URL"
        )

    sid = _sheet_id_from_url(url or "") or source_id
    summary: dict = {
        "ok": True,
        "downloaded": downloaded,
        "bytes": bytes_written,
        "source": "google_sheet" if downloaded else "local_csv",
        "download_via": download_via or ("local_csv" if not downloaded else ""),
        "preserved_hub": 0,
        "spreadsheet_id": sid,
        "csv_url": url or "",
        "sync_role": "pull_source",
    }
    if download_error and download_via != "public_csv":
        summary["download_warning"] = download_error

    if sid:
        try:
            summary["sheet_title"] = fetch_spreadsheet_title(sid)
        except Exception:
            summary["sheet_title"] = ""
    if url:
        summary["sheet_gid"] = _gid_from_url(url) or _env("MAIN_SHEET_GID", "HUB_MAIN_SHEET_GID") or ""

    if rebuild:
        from src.hub.project_store import _STORE_LOCK

        build_master = _load_build_master()

        # Hold the store lock across fresh-snapshot → rebuild → re-attach so
        # concurrent Hub saves cannot land mid-wipe and then be lost.
        with _STORE_LOCK:
            try:
                preserved = [dict(p) for p in load_properties() if is_hub_owned(p)]
                overlay_by_id, overlay_by_code, overlay_blocked = _build_overlay_snapshots(
                    load_properties()
                )
            except Exception:
                pass  # keep earlier snapshot

            summary["stats"] = build_master.rebuild_from_csv()

            # Re-attach Hub rows (RXT/COA) so refresh does not erase app work
            projects = load_projects()
            properties = load_properties()
            for p in properties:
                p.setdefault("data_source", "sheet")
                p.setdefault("code_prefix", "PTP")

            # Restore Living / verified location fields wiped by rebuild_from_csv
            restored_loc = 0
            for proj in projects:
                bucket = proj.get("bucket_key") or ""
                snap = preserved_loc_by_bucket.get(bucket)
                if not snap:
                    continue
                for key, val in snap.items():
                    if val not in ("", None, [], {}):
                        proj[key] = val
                if snap.get("transit_verified") or snap.get("zone_verified"):
                    from src.hub.project_store import sync_project_listings_location_ref

                    sync_project_listings_location_ref(proj, properties)
                    restored_loc += 1
            summary["preserved_locations"] = restored_loc

            existing = {(p.get("code") or "").upper() for p in properties}
            restored = 0
            for hp in preserved:
                code = (hp.get("code") or "").upper()
                if not code:
                    continue
                hp = dict(hp)
                hp["data_source"] = "hub"
                if code in existing:
                    # Prefer keeping Hub version for same code
                    properties = [p for p in properties if (p.get("code") or "").upper() != code]
                properties.insert(0, hp)
                existing.add(code)
                restored += 1
                # bump project listing_count lightly is skipped — rebuild already set counts

            # Re-apply Hub edits on PTP (and others): links/notes/captions that the
            # main-sheet CSV rebuild blanks. Without this, mobile「รีเฟรช」wipes work.
            restored_overlay = 0
            if overlay_by_id or overlay_by_code:
                restored_overlay = _apply_overlay_snapshots(
                    properties,
                    overlay_by_id=overlay_by_id,
                    overlay_by_code=overlay_by_code,
                    blocked_codes=overlay_blocked,
                )
            summary["preserved_hub_edits"] = restored_overlay
            if overlay_blocked:
                summary["overlay_blocked_ambiguous_codes"] = len(overlay_blocked)

            if restored or restored_loc or restored_overlay:
                # recount listing_count from merged properties
                counts: dict[str, int] = {}
                for p in properties:
                    pid = p.get("project_id") or ""
                    if pid:
                        counts[pid] = counts.get(pid, 0) + 1
                for proj in projects:
                    proj["listing_count"] = counts.get(proj["id"], 0)
                projects.sort(
                    key=lambda x: (-int(x.get("listing_count") or 0), x["canonical_name"])
                )
                persist(projects, properties)
            summary["preserved_hub"] = restored
            summary["stats"]["properties_total"] = len(properties)
            summary["stats"]["properties_hub"] = restored

            # Safety net: merge「ทรัพย์ Hub」tab so RXT/COA survive if memory snapshot
            # was empty, and pick up blank notes from that tab (never clobber local).
            try:
                sheet_hub = _merge_hub_tab_into_properties(projects, properties)
                if sheet_hub.get("merged") or sheet_hub.get("notes_updated"):
                    properties = sheet_hub["properties"]
                    projects = sheet_hub["projects"]
                    persist(projects, properties)
                    summary["hub_tab_merged"] = sheet_hub.get("merged", 0)
                    summary["hub_tab_notes_updated"] = sheet_hub.get("notes_updated", 0)
                    summary["preserved_hub"] = sum(
                        1 for p in properties if is_hub_owned(p)
                    )
                    summary["stats"]["properties_total"] = len(properties)
                    summary["stats"]["properties_hub"] = summary["preserved_hub"]
            except Exception as hub_exc:  # noqa: BLE001
                summary["hub_tab_warning"] = str(hub_exc)

            # Extra safety: local overview export still has RXT/COA after a bad wipe.
            try:
                ov = _merge_overview_export_hub_rows(projects, properties)
                if ov.get("merged"):
                    properties = ov["properties"]
                    projects = ov["projects"]
                    persist(projects, properties)
                    summary["overview_export_merged"] = ov.get("merged", 0)
                    summary["preserved_hub"] = sum(
                        1 for p in properties if is_hub_owned(p)
                    )
                    summary["stats"]["properties_total"] = len(properties)
                    summary["stats"]["properties_hub"] = summary["preserved_hub"]
            except Exception as ov_exc:  # noqa: BLE001
                summary["overview_export_warning"] = str(ov_exc)

            # optional: refresh local export of hub tab for visibility
            try:
                from src.hub.sheet_write import write_hub_export_csv

                write_hub_export_csv([p for p in properties if is_hub_owned(p)])
            except Exception:
                pass

    return summary


def _merge_overview_export_hub_rows(projects: list[dict], properties: list[dict]) -> dict:
    """Re-attach RXT/COA rows from hub_overview_export.csv if missing after sheet rebuild."""
    import csv
    import uuid
    from datetime import datetime, timezone

    from src.hub.project_identity import project_bucket
    from src.hub.project_store import find_project_by_bucket

    path = BASE_DIR / "data" / "hub_overview_export.csv"
    if not path.is_file():
        return {"merged": 0, "properties": properties, "projects": projects}

    existing = {(p.get("code") or "").strip().upper() for p in properties}
    merged = 0
    out = list(properties)
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return {"merged": 0, "properties": properties, "projects": projects}

    for row in rows:
        code = (row.get("รหัส") or "").strip().upper()
        if not code.startswith(("RXT", "COA")) or code in existing:
            continue
        name = (row.get("โครงการ") or "").strip()
        bucket = project_bucket(name) if name else ""
        proj = find_project_by_bucket(projects, bucket) if bucket else None
        owner = (row.get("เจ้าของ") or "").strip()
        post = (row.get("ที่โพสต์") or "").strip()
        page = (row.get("เพจ") or "").strip()
        source = (row.get("ต้นทาง") or "").strip()
        prop = {
            "id": str(uuid.uuid4()),
            "code": code,
            "code_prefix": code[:3],
            "listing_kind": "co_agent" if code.startswith("COA") else "direct",
            "project_id": (proj or {}).get("id") or "",
            "project_name": (proj or {}).get("canonical_name") or name,
            "property_type": (row.get("ประเภท") or "Condo").strip() or "Condo",
            "bedrooms": (row.get("ห้อง") or "").strip(),
            "size_sqm": (row.get("ตรม.") or "").strip(),
            "floor": (row.get("ชั้น") or "").strip(),
            "rent_price": (row.get("เช่า") or "").strip(),
            "sale_price": (row.get("ขาย") or "").strip(),
            "source_url": source,
            "post_url": post,
            "post_pages_url": page,
            "owner_facebook": [owner] if owner.startswith("http") else [],
            "owner_phones": [],
            "owner_lines": [],
            "notes": (row.get("หมายเหตุ") or "").strip(),
            "data_source": "hub",
            "import_status": "active",
            "media_status": "has_link" if post else "pending",
            "last_listed_at": (row.get("วันที่") or "").strip()
            or datetime.now().strftime("%d/%m/%Y"),
            "hub_edited_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "location_ref": ", ".join(
                x
                for x in [
                    (row.get("ทำเล") or "").strip(),
                    (row.get("สถานี") or "").strip(),
                ]
                if x
            ),
            "transit_from_sheet": [
                x.strip() for x in (row.get("สถานี") or "").split(",") if x.strip()
            ],
        }
        out.insert(0, prop)
        existing.add(code)
        merged += 1

    return {"merged": merged, "properties": out, "projects": projects}


def _merge_hub_tab_into_properties(projects: list[dict], properties: list[dict]) -> dict:
    """Pull Hub-owned rows / notes from「ทรัพย์ Hub」when credentials are available."""
    import uuid
    from datetime import datetime

    from src.hub.project_store import project_location_label, project_transit_display

    sheet_id = _env("HUB_GOOGLE_SHEETS_ID") or _env("GOOGLE_SHEETS_ID")
    hub_name = _env("HUB_SHEET_NAME") or "ทรัพย์ Hub"
    hub_gid = _env("HUB_SHEET_GID")
    if not sheet_id or sheet_id.startswith("your_"):
        return {"merged": 0, "notes_updated": 0, "properties": properties, "projects": projects}

    try:
        from src.hub.sheet_write import _gspread_client
    except Exception:
        return {"merged": 0, "notes_updated": 0, "properties": properties, "projects": projects}

    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    ws = None
    if hub_gid:
        try:
            ws = ss.get_worksheet_by_id(int(hub_gid))
        except Exception:
            ws = None
    if ws is None:
        ws = ss.worksheet(hub_name)

    values = ws.get_all_values()
    if len(values) < 2:
        return {"merged": 0, "notes_updated": 0, "properties": properties, "projects": projects}

    headers = [str(h or "").strip() for h in values[0]]

    def col(name: str) -> int | None:
        try:
            return headers.index(name)
        except ValueError:
            return None

    code_i = col("รหัสทรัพย์")
    if code_i is None:
        return {"merged": 0, "notes_updated": 0, "properties": properties, "projects": projects}
    notes_i = col("หมายเหตุ")
    proj_i = col("โครงการ")
    type_i = col("ประเภท")
    beds_i = col("ห้องนอน/ห้องน้ำ")
    size_i = col("ขนาด")
    floor_i = col("ชั้น")
    rent_i = col("ราคาเช่า")
    sale_i = col("ราคาขาย")
    date_i = col("วันที่รับเข้า")
    owner_i = col("เฟสเจ้าของ")

    by_code = {(p.get("code") or "").upper(): p for p in properties}
    projects_by_name = {
        (p.get("canonical_name") or "").strip().lower(): p for p in projects
    }
    merged = 0
    notes_updated = 0

    def cell(row: list[str], idx: int | None) -> str:
        if idx is None or idx >= len(row):
            return ""
        return str(row[idx] or "").strip()

    for row in values[1:]:
        code = cell(row, code_i).upper().replace(" ", "")
        if not (code.startswith("RXT") or code.startswith("COA")):
            continue
        notes = cell(row, notes_i)
        existing = by_code.get(code)
        if existing:
            # Prefer non-empty local notes — sheet merge must not clobber Hub edits
            # that have not been sync-to-sheet yet. Only fill blanks from the tab.
            local_notes = (existing.get("notes") or "").strip()
            if notes and not local_notes:
                existing["notes"] = notes
                notes_updated += 1
            elif notes and notes != local_notes:
                # Sheet has different notes while local already has text — keep local.
                pass
            existing["data_source"] = "hub"
            continue

        proj_name = cell(row, proj_i)
        proj = projects_by_name.get(proj_name.lower()) if proj_name else None
        if not proj and proj_name:
            # soft match contains
            for name, p in projects_by_name.items():
                if proj_name.lower() in name or name in proj_name.lower():
                    proj = p
                    break
        if not proj:
            continue

        beds_raw = cell(row, beds_i)
        beds = beds_raw.split("/")[0].strip() if beds_raw else ""
        owner_raw = cell(row, owner_i)
        owner_fb = [owner_raw] if owner_raw.startswith("http") else []
        prefix = "COA" if code.startswith("COA") else "RXT"
        prop = {
            "id": str(uuid.uuid4()),
            "code": code,
            "code_prefix": prefix,
            "data_source": "hub",
            "listing_kind": "co_agent" if prefix == "COA" else "direct",
            "project_id": proj["id"],
            "project_name": proj["canonical_name"],
            "last_listed_at": cell(row, date_i) or datetime.now().strftime("%d/%m/%Y"),
            "property_type": cell(row, type_i) or "Condo",
            "bedrooms": beds,
            "size_sqm": cell(row, size_i),
            "floor": cell(row, floor_i),
            "rent_price": cell(row, rent_i),
            "sale_price": cell(row, sale_i),
            "source_url": "",
            "post_url": "",
            "post_pages_url": "",
            "notes": notes,
            "import_status": "active",
            "media_status": "pending",
            "sheet_row": "",
            "transit_from_sheet": project_transit_display(proj),
            "duplicate_flags": [],
            "location_ref": project_location_label(proj),
            "owner_phones": [],
            "owner_lines": [],
            "owner_facebook": owner_fb,
            "text_th": "",
            "text_en": "",
            "raw_text": "",
            "linked_ptp_code": "",
        }
        properties.insert(0, prop)
        by_code[code] = prop
        merged += 1

    if merged:
        counts: dict[str, int] = {}
        for p in properties:
            pid = p.get("project_id") or ""
            if pid:
                counts[pid] = counts.get(pid, 0) + 1
        for proj in projects:
            proj["listing_count"] = counts.get(proj["id"], 0)
        projects.sort(
            key=lambda x: (-int(x.get("listing_count") or 0), x["canonical_name"])
        )

    return {
        "merged": merged,
        "notes_updated": notes_updated,
        "properties": properties,
        "projects": projects,
    }


def refresh_wait_post_sheet(*, csv_url: str = "") -> dict:
    """Download wait-post sheet CSV if URL configured; otherwise keep local file."""
    source_id = _env(
        "SOURCE_GOOGLE_SHEETS_ID",
        "MAIN_GOOGLE_SHEETS_ID",
        "HUB_SOURCE_GOOGLE_SHEETS_ID",
    )
    url = resolve_csv_export_url(
        explicit_url=csv_url or _env("WAIT_POST_SHEET_CSV_URL", "HUB_WAIT_POST_SHEET_CSV_URL"),
        spreadsheet_id=source_id,
        sheet_name=_env("WAIT_POST_SHEET_NAME", "HUB_WAIT_SHEET_NAME") or "รอโพสต์",
        gid=_env("WAIT_POST_SHEET_GID", "HUB_WAIT_SHEET_GID") or "",
    )
    if not url:
        if not WAIT_CSV.exists():
            raise ValueError("ไม่พบ wait_post_sheet.csv และยังไม่ได้ตั้ง WAIT_POST_SHEET_CSV_URL")
        return {"ok": True, "downloaded": False, "source": "local_csv"}

    try:
        n = download_csv(url, WAIT_CSV)
        return {"ok": True, "downloaded": True, "bytes": n, "source": "google_sheet"}
    except Exception as exc:  # noqa: BLE001
        if WAIT_CSV.exists():
            return {
                "ok": True,
                "downloaded": False,
                "source": "local_csv",
                "download_warning": str(exc),
            }
        raise ValueError(str(exc)) from exc
