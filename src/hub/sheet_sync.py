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
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except Exception:
    pass


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

    # Snapshot Hub-owned rows before rebuild wipes properties.json
    preserved: list[dict] = []
    try:
        preserved = [dict(p) for p in load_properties() if is_hub_owned(p)]
    except Exception:
        preserved = []

    downloaded = False
    download_error = ""
    bytes_written = 0
    if url:
        try:
            bytes_written = download_csv(url, MAIN_CSV)
            downloaded = True
        except Exception as exc:  # noqa: BLE001
            download_error = str(exc)

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
        "preserved_hub": 0,
        "spreadsheet_id": sid,
        "csv_url": url or "",
        "sync_role": "pull_source",
    }
    if download_error and not downloaded:
        summary["download_warning"] = download_error

    if sid:
        try:
            summary["sheet_title"] = fetch_spreadsheet_title(sid)
        except Exception:
            summary["sheet_title"] = ""
    if url:
        summary["sheet_gid"] = _gid_from_url(url) or _env("MAIN_SHEET_GID", "HUB_MAIN_SHEET_GID") or ""

    if rebuild:
        build_master = _load_build_master()
        summary["stats"] = build_master.rebuild_from_csv()

        # Re-attach Hub rows (RXT/COA) so refresh does not erase app work
        projects = load_projects()
        properties = load_properties()
        for p in properties:
            p.setdefault("data_source", "sheet")
            p.setdefault("code_prefix", "PTP")

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
        if restored:
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

        # optional: refresh local export of hub tab for visibility
        try:
            from src.hub.sheet_write import write_hub_export_csv

            write_hub_export_csv([p for p in properties if is_hub_owned(p)])
        except Exception:
            pass

    return summary


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
