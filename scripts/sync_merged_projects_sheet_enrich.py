#!/usr/bin/env python3
"""After project merge: enrich ทำเล/รถไฟฟ้า/สถานที่ใกล้เคียง from PropertyHub + Livinginsider,
push Hubโครงการ + location masters, refresh listing sheet names/locations, sync Fly data.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env", override=True)
except Exception:
    pass

from src.hub.env_load import load_hub_env  # noqa: E402
from src.hub.location_master_store import ensure_labels  # noqa: E402
from src.hub.project_location_enrich import apply_living_to_project  # noqa: E402
from src.hub.project_store import (  # noqa: E402
    dedupe_stations,
    load_projects,
    load_properties,
    parse_tag_list,
    persist,
    project_transit_display,
    project_zone_display,
    sync_project_listings_location_ref,
    write_preview_js,
)
from src.hub.propertyhub_client import (  # noqa: E402
    fetch_propertyhub_location,
    propertyhub_project_url,
    slugify_project_name,
)

load_hub_env(force=True)

LOG_DIR = ROOT / "logs"
BACKUP_DIR = LOG_DIR / f"backup_sheet_projects_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _uniq(items: list[str], *, limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        label = re.sub(r"\s+", " ", (raw or "").strip())
        if not label:
            continue
        key = re.sub(r"[^a-z0-9ก-๙]", "", label.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(label)
        if limit is not None and len(out) >= limit:
            break
    return out


def _is_living_source(src: str) -> bool:
    return "livinginsider" in (src or "").lower()


def _merge_lists_prefer_first(primary: list[str], secondary: list[str], *, limit: int) -> list[str]:
    return _uniq(list(primary or []) + list(secondary or []), limit=limit)


def apply_propertyhub_to_project(proj: dict, ph) -> tuple[list[str], list[str], list[str]]:
    """Merge PropertyHub location into project (union with existing Living/verified)."""
    existing_zones = list(proj.get("zone_verified") or []) or list(
        proj.get("zone_unverified") or []
    )
    existing_transit = list(proj.get("transit_verified") or []) or list(
        proj.get("transit_unverified") or []
    )
    existing_nearby = list(proj.get("nearby_places") or [])

    ph_zones = list(ph.zones or [])
    ph_transit = dedupe_stations(list(ph.transit or []))
    ph_nearby = list(ph.nearby_places or [])

    # Prefer existing Living-verified chips first, then fill from PropertyHub
    if _is_living_source(str(proj.get("location_source") or "")) and existing_zones:
        zones = _merge_lists_prefer_first(existing_zones, ph_zones, limit=5)
        transit = _merge_lists_prefer_first(existing_transit, ph_transit, limit=3)
        source = f"{proj.get('location_source')}+propertyhub"
    else:
        # Prefer PropertyHub names/chips when Living not verified
        zones = _merge_lists_prefer_first(ph_zones, existing_zones, limit=5)
        transit = _merge_lists_prefer_first(ph_transit, existing_transit, limit=3)
        living_bit = "livinginsider+" if _is_living_source(str(proj.get("location_source") or "")) else ""
        source = f"{living_bit}propertyhub" if ph_zones or ph_transit or ph_nearby else (
            proj.get("location_source") or "propertyhub"
        )

    nearby = _merge_lists_prefer_first(ph_nearby, existing_nearby, limit=8)

    if zones:
        proj["zone_verified"] = parse_tag_list(zones)[:5]
        proj["zone_unverified"] = []
    if transit:
        proj["transit_verified"] = dedupe_stations(transit)[:3]
        proj["transit_unverified"] = []
    if nearby:
        proj["nearby_places"] = nearby
    if ph.url:
        proj["propertyhub_url"] = ph.url
    if ph.name and not proj.get("propertyhub_name"):
        proj["propertyhub_name"] = ph.name
    if zones or transit or nearby:
        proj["location_status"] = "verified"
        proj["location_source"] = source
    return (
        list(proj.get("zone_verified") or []),
        list(proj.get("transit_verified") or []),
        list(proj.get("nearby_places") or []),
    )


def _priority_project_ids() -> tuple[set[str], dict[str, str]]:
    """Merged keep ids + PropertyHub URLs from survey/merge logs."""
    keep_ids: set[str] = set()
    ph_url_by_id: dict[str, str] = {}

    merge_path = LOG_DIR / "project_merge_20260727_result.json"
    if merge_path.exists():
        data = json.loads(merge_path.read_text(encoding="utf-8"))
        for m in data.get("merges") or []:
            kid = m.get("keep_id")
            if kid:
                keep_ids.add(kid)

    dup_path = LOG_DIR / "project_duplicates_20260727.json"
    if dup_path.exists():
        data = json.loads(dup_path.read_text(encoding="utf-8"))
        for c in data.get("clusters") or []:
            kid = c.get("suggested_keep_id") or ""
            url = (c.get("propertyhub_url") or "").strip()
            if kid:
                keep_ids.add(kid)
            if kid and url:
                ph_url_by_id[kid] = url
    return keep_ids, ph_url_by_id


def _needs_location(proj: dict) -> bool:
    zones = proj.get("zone_verified") or proj.get("zone_unverified") or []
    transit = proj.get("transit_verified") or proj.get("transit_unverified") or []
    nearby = proj.get("nearby_places") or []
    return not zones or not transit or not nearby


def _is_fully_enriched(proj: dict) -> bool:
    """Skip when zone+transit+nearby+propertyhub_url already present (resume)."""
    zones = proj.get("zone_verified") or proj.get("zone_unverified") or []
    transit = proj.get("transit_verified") or proj.get("transit_unverified") or []
    nearby = proj.get("nearby_places") or []
    ph = str(proj.get("propertyhub_url") or "").strip()
    return bool(zones) and bool(transit) and bool(nearby) and bool(ph)


def _load_attempted_ids() -> set[str]:
    """IDs already tried this round (failures + attempted logs) — resume without redoing."""
    out: set[str] = set()
    for name in (
        "project_sheet_enrich_20260727_failures.jsonl",
        "project_sheet_enrich_20260727_attempted.jsonl",
    ):
        path = LOG_DIR / name
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                pid = row.get("id")
                if pid:
                    out.add(pid)
        except (OSError, json.JSONDecodeError):
            pass
    return out


def _was_attempted(proj: dict, attempted_ids: set[str]) -> bool:
    """True if already fully done, PH/nearby filled, or logged as a prior attempt/failure."""
    if _is_fully_enriched(proj):
        return True
    if proj.get("id") in attempted_ids:
        return True
    if str(proj.get("propertyhub_url") or "").strip():
        return True
    if proj.get("nearby_places"):
        return True
    return False


def select_targets(
    projects: list[dict],
    *,
    keep_ids: set[str],
    max_projects: int | None,
    include_incomplete: bool,
    include_rest: bool,
    skip_complete: bool = False,
    skip_attempted: bool = False,
) -> list[dict]:
    by_id = {p["id"]: p for p in projects}
    ordered: list[dict] = []
    seen: set[str] = set()
    attempted_ids = _load_attempted_ids() if skip_attempted else set()

    def add(pid: str) -> None:
        if pid in seen:
            return
        proj = by_id.get(pid)
        if not proj:
            return
        if skip_complete and _is_fully_enriched(proj):
            return
        if skip_attempted and _was_attempted(proj, attempted_ids):
            return
        seen.add(pid)
        ordered.append(proj)

    # (a) merged keeps first (by listing count)
    merged = sorted(
        (by_id[i] for i in keep_ids if i in by_id),
        key=lambda p: -int(p.get("listing_count") or 0),
    )
    for p in merged:
        add(p["id"])

    # (b) incomplete
    if include_incomplete:
        incomplete = sorted(
            (p for p in projects if _needs_location(p)),
            key=lambda p: -int(p.get("listing_count") or 0),
        )
        for p in incomplete:
            add(p["id"])

    # (c) rest by listings
    if include_rest:
        rest = sorted(projects, key=lambda p: -int(p.get("listing_count") or 0))
        for p in rest:
            add(p["id"])

    if max_projects is not None and max_projects > 0:
        ordered = ordered[:max_projects]
    return ordered


def _coverage_counts(projects: list[dict]) -> dict:
    total = len(projects) or 1
    zone = sum(
        1 for p in projects if (p.get("zone_verified") or p.get("zone_unverified"))
    )
    transit = sum(
        1
        for p in projects
        if (p.get("transit_verified") or p.get("transit_unverified"))
    )
    nearby = sum(1 for p in projects if p.get("nearby_places"))
    ph = sum(1 for p in projects if str(p.get("propertyhub_url") or "").strip())
    complete = sum(1 for p in projects if _is_fully_enriched(p))
    return {
        "total": len(projects),
        "zone": zone,
        "transit": transit,
        "nearby": nearby,
        "propertyhub_url": ph,
        "already_complete": complete,
        "zone_pct": round(100.0 * zone / total, 1),
        "transit_pct": round(100.0 * transit / total, 1),
        "nearby_pct": round(100.0 * nearby / total, 1),
        "propertyhub_pct": round(100.0 * ph / total, 1),
        "complete_pct": round(100.0 * complete / total, 1),
    }


def write_progress(
    *,
    batch_done: int,
    batch_total: int,
    batch_start_complete: int,
    projects: list[dict],
    remaining_hint: int | None = None,
) -> dict:
    """Write machine-readable + one-line human progress for parent polling."""
    cov = _coverage_counts(projects)
    batch_pct = round(100.0 * batch_done / batch_total, 1) if batch_total else 100.0
    # overall: prior complete + batch progress over prior complete + this batch size
    denom = batch_start_complete + batch_total
    overall_done = batch_start_complete + batch_done
    overall_pct = round(100.0 * overall_done / denom, 1) if denom else 100.0
    # also expose campaign progress vs full catalog
    remaining = remaining_hint
    if remaining is None:
        remaining = max(0, cov["total"] - cov["already_complete"])
    catalog_done = cov["total"] - remaining
    catalog_pct = round(100.0 * catalog_done / cov["total"], 1) if cov["total"] else 100.0
    line = (
        f"PROGRESS overall={overall_pct}% batch={batch_done}/{batch_total} "
        f"({batch_pct}%) nearby={cov['nearby_pct']}% ph={cov['propertyhub_pct']}% "
        f"zone={cov['zone_pct']}% transit={cov['transit_pct']}% "
        f"complete={cov['already_complete']}/{cov['total']}"
    )
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "at": datetime.now().isoformat(timespec="seconds"),
        "total_projects": cov["total"],
        "batch": {
            "done": batch_done,
            "total": batch_total,
            "pct": batch_pct,
        },
        "overall": {
            "done": overall_done,
            "total": denom,
            "pct": overall_pct,
            "batch_start_complete": batch_start_complete,
        },
        "overall_skip_complete": {
            "done": overall_done,
            "total": denom,
            "pct": overall_pct,
        },
        "catalog": {
            "done": catalog_done,
            "total": cov["total"],
            "pct": catalog_pct,
            "remaining": remaining,
        },
        "coverage": {
            "total_projects": cov["total"],
            "zone": cov["zone"],
            "transit": cov["transit"],
            "nearby": cov["nearby"],
            "propertyhub_url": cov["propertyhub_url"],
            "propertyhub": cov["propertyhub_url"],
            "already_complete": cov["already_complete"],
            "zone_pct": cov["zone_pct"],
            "transit_pct": cov["transit_pct"],
            "nearby_pct": cov["nearby_pct"],
            "propertyhub_pct": cov["propertyhub_pct"],
            "complete_pct": cov["complete_pct"],
        },
        "line": line,
    }
    progress_json = LOG_DIR / "project_enrich_progress.json"
    progress_log = LOG_DIR / "project_enrich_progress.log"
    try:
        progress_json.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with progress_log.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
        # also append to main enrich log for parent grepping
        with (LOG_DIR / "project_sheet_enrich_20260727_full.log").open(
            "a", encoding="utf-8"
        ) as fh:
            fh.write(f"  {line}\n")
        print(f"  {line}", flush=True)
    except OSError as exc:
        print(f"  ! progress write failed: {exc}", flush=True)
    return payload


def enrich_targets(
    targets: list[dict],
    *,
    ph_url_by_id: dict[str, str],
    dry_run: bool,
    sleep_s: float,
    use_cache: bool,
    living: bool,
    propertyhub: bool,
    checkpoint_every: int = 50,
) -> dict:
    from collections import defaultdict

    from src.hub.living_client import consensus_location, fetch_living_location

    projects = load_projects()
    properties = load_properties()
    by_id = {p["id"]: p for p in projects}
    urls_by_pid: dict[str, list[str]] = defaultdict(list)
    for prop in properties:
        pid = prop.get("project_id")
        url = str(prop.get("source_url") or "")
        if not pid or "livinginsider" not in url.lower():
            continue
        if url not in urls_by_pid[pid]:
            if "/living_project/" in url.lower():
                urls_by_pid[pid].append(url)
            else:
                urls_by_pid[pid].insert(0, url)
    for proj in projects:
        purl = str(proj.get("living_project_url") or "").strip()
        if purl and "livinginsider" in purl.lower():
            if purl not in urls_by_pid[proj["id"]]:
                urls_by_pid[proj["id"]].append(purl)

    batch_start_complete = sum(1 for p in projects if _is_fully_enriched(p))
    write_progress(
        batch_done=0,
        batch_total=len(targets),
        batch_start_complete=batch_start_complete,
        projects=projects,
    )

    stats: dict = {
        "targets": len(targets),
        "propertyhub_ok": 0,
        "propertyhub_fail": 0,
        "living_ok": 0,
        "living_fail": 0,
        "living_skipped_no_url": 0,
        "projects_updated": 0,
        "listings_synced": 0,
        "nearby_filled": 0,
        "zone_filled": 0,
        "transit_filled": 0,
        "failures": [],
        "samples": [],
        "errors": 0,
    }
    fail_path = LOG_DIR / "project_sheet_enrich_20260727_failures.jsonl"
    attempted_path = LOG_DIR / "project_sheet_enrich_20260727_attempted.jsonl"

    def _mark_attempted(proj: dict) -> None:
        try:
            with attempted_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {"id": proj.get("id"), "name": proj.get("canonical_name")},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        except OSError:
            pass

    def _checkpoint(*, final: bool = False) -> None:
        """Always lightweight projects.json; full persist only at explicit final+full."""
        if dry_run:
            return
        try:
            from src.hub.project_store import PROJECTS_JSON, _atomic_write_text

            _atomic_write_text(
                PROJECTS_JSON,
                json.dumps(projects, ensure_ascii=False, indent=2),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  ! lightweight checkpoint failed: {exc}", flush=True)
            return
        if final:
            # Defer sqlite/preview to sheet-only / post-watchdog — those OOMed mid-run.
            print("  … lightweight final projects.json saved", flush=True)

    def _enrich_one(proj: dict) -> None:
        nonlocal stats
        before = {
            "zones": list(proj.get("zone_verified") or []),
            "transit": list(proj.get("transit_verified") or []),
            "nearby": list(proj.get("nearby_places") or []),
            "source": proj.get("location_source"),
        }
        changed = False

        if living:
            urls = urls_by_pid.get(proj["id"]) or []
            listing_urls = [u for u in urls if "/living_project/" not in u.lower()]
            project_urls = [u for u in urls if "/living_project/" in u.lower()]
            sample_urls = (listing_urls + project_urls)[:1]  # 1 URL — fewer hangs
            if sample_urls:
                samples = []
                for u in sample_urls:
                    from src.hub.living_client import _load_cache

                    had = bool(use_cache and _load_cache(u))
                    loc = fetch_living_location(
                        u, use_cache=use_cache, sleep_s=0 if had else sleep_s
                    )
                    samples.append(loc)
                consensus = consensus_location(samples)
                if consensus and (consensus.zone or consensus.stations):
                    apply_living_to_project(
                        proj,
                        zone=consensus.zone or "",
                        stations=list(consensus.stations or []),
                        living_project_url=consensus.project_url
                        or str(proj.get("living_project_url") or ""),
                    )
                    stats["living_ok"] += 1
                    changed = True
                else:
                    stats["living_fail"] += 1
            else:
                stats["living_skipped_no_url"] += 1

        if propertyhub:
            ph_url = (
                ph_url_by_id.get(proj["id"])
                or str(proj.get("propertyhub_url") or "").strip()
                or propertyhub_project_url(
                    slugify_project_name(proj.get("canonical_name") or "")
                )
            )
            try:
                ph = fetch_propertyhub_location(
                    ph_url, use_cache=use_cache, sleep_s=sleep_s, retries=1
                )
            except Exception as exc:  # noqa: BLE001
                ph = type("X", (), {"ok": False, "error": str(exc), "url": ph_url})()
            if getattr(ph, "ok", False):
                apply_propertyhub_to_project(proj, ph)
                stats["propertyhub_ok"] += 1
                changed = True
            else:
                stats["propertyhub_fail"] += 1
                fail_row = {
                    "name": proj.get("canonical_name"),
                    "id": proj.get("id"),
                    "url": ph_url,
                    "error": getattr(ph, "error", "unknown"),
                }
                if len(stats["failures"]) < 80:
                    stats["failures"].append(fail_row)
                try:
                    with fail_path.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps(fail_row, ensure_ascii=False) + "\n")
                except OSError:
                    pass

        after_zones = project_zone_display(proj)
        after_transit = project_transit_display(proj)
        after_nearby = list(proj.get("nearby_places") or [])
        if after_zones and not before["zones"]:
            stats["zone_filled"] += 1
        if after_transit and not before["transit"]:
            stats["transit_filled"] += 1
        if after_nearby and not before["nearby"]:
            stats["nearby_filled"] += 1

        if (
            changed
            or after_zones != before["zones"]
            or after_transit != before["transit"]
            or after_nearby != before["nearby"]
        ):
            stats["projects_updated"] += 1
            if not dry_run:
                stats["listings_synced"] += sync_project_listings_location_ref(
                    proj, properties
                )
            if len(stats["samples"]) < 12:
                stats["samples"].append(
                    {
                        "name": proj.get("canonical_name"),
                        "zones": after_zones,
                        "transit": after_transit,
                        "nearby": after_nearby[:5],
                        "source": proj.get("location_source"),
                        "ph_url": proj.get("propertyhub_url"),
                    }
                )

    for i, stub in enumerate(targets):
        proj = by_id.get(stub["id"])
        if not proj:
            continue
        # Mark first so a hang/kill won't retry the same URL forever
        _mark_attempted(proj)
        try:
            _enrich_one(proj)
        except Exception as exc:  # noqa: BLE001
            stats["errors"] += 1
            print(
                f"  ! error on {proj.get('canonical_name')}: {exc}",
                flush=True,
            )
            try:
                with fail_path.open("a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "name": proj.get("canonical_name"),
                                "id": proj.get("id"),
                                "error": f"exception:{exc}",
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            except OSError:
                pass

        done = i + 1
        rem_hint = max(0, len(targets) - done)
        # progress every project so parent never sees a stall gap
        write_progress(
            batch_done=done,
            batch_total=len(targets),
            batch_start_complete=batch_start_complete,
            projects=projects,
            remaining_hint=rem_hint,
        )
        if done % 25 == 0:
            print(f"  … enriched {done}/{len(targets)}", flush=True)
        if checkpoint_every > 0 and done % checkpoint_every == 0:
            print(f"  … checkpoint persist @ {done}", flush=True)
            _checkpoint(final=False)

    if not dry_run:
        print("  … final persist", flush=True)
        _checkpoint(final=True)
        write_progress(
            batch_done=len(targets),
            batch_total=len(targets),
            batch_start_complete=batch_start_complete,
            projects=projects,
        )

    stats["projects_total"] = len(projects)
    stats["failures_log"] = str(fail_path)
    stats["attempted_log"] = str(attempted_path)
    return stats


def backup_local() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for name in (
        "projects.json",
        "properties.json",
        "zone_master.json",
        "transit_master.json",
        "preview-data.js",
        "preview-data.meta.json",
    ):
        src = ROOT / "data" / name if not name.startswith("preview") else ROOT / "hub" / name
        if name.startswith("preview"):
            src = ROOT / "hub" / name
        if src.exists():
            shutil.copy2(src, BACKUP_DIR / src.name)
    return BACKUP_DIR


def push_sheet_masters() -> dict:
    from src.hub.hub_state_sheet import (
        push_projects_to_sheet,
        push_transits_to_sheet,
        push_zones_to_sheet,
    )
    from src.hub.location_master_store import list_transits, list_zones

    out = {
        "projects": push_projects_to_sheet(),
        "zones": push_zones_to_sheet(list_zones()),
        "transits": push_transits_to_sheet(list_transits()),
    }
    return out


def refresh_work_sheet_names_and_locations(*, dry_run: bool = False) -> dict:
    """Update「ชีตสำหรับทำงาน」โครงการ + ทำเล + สถานี from merged master."""
    from src.hub.project_identity import soft_norm
    from src.hub.project_store import project_location_label
    from src.hub.sheet_write import _env, _gspread_client

    sheet_id = _env("SOURCE_GOOGLE_SHEETS_ID") or _env("GOOGLE_SHEETS_ID")
    client = _gspread_client()
    ss = client.open_by_key(sheet_id)
    ws = ss.worksheet(_env("MAIN_SHEET_NAME") or "ชีตสำหรับทำงาน")
    values = ws.get_all_values()
    if not values:
        return {"ok": False, "error": "empty"}
    headers = list(values[0])
    for need in ("โครงการ", "ทำเล", "สถานีรถไฟฟ้า"):
        if need not in headers:
            return {"ok": False, "error": f"missing column {need}", "headers": headers}
    col_p = headers.index("โครงการ")
    col_z = headers.index("ทำเล")
    col_t = headers.index("สถานีรถไฟฟ้า")

    projects = load_projects()
    by_name: dict[str, dict] = {}
    for proj in projects:
        for label in [proj.get("canonical_name") or ""] + list(proj.get("aliases") or []):
            k = soft_norm(label)
            if k and k not in by_name:
                by_name[k] = proj

    name_updates: list[tuple[int, str]] = []
    zone_updates: list[tuple[int, str]] = []
    transit_updates: list[tuple[int, str]] = []
    matched = unmatched = 0
    for ridx, row in enumerate(values[1:], start=2):
        while len(row) <= max(col_p, col_z, col_t):
            row.append("")
        pname = (row[col_p] or "").strip()
        if not pname:
            continue
        proj = by_name.get(soft_norm(pname))
        if not proj:
            unmatched += 1
            continue
        matched += 1
        canon = (proj.get("canonical_name") or "").strip()
        zone = project_location_label(proj)
        transit = ", ".join(project_transit_display(proj)[:3])
        if canon and canon != pname:
            name_updates.append((ridx, canon))
        if zone and zone != (row[col_z] or "").strip():
            zone_updates.append((ridx, zone))
        if transit and transit != (row[col_t] or "").strip():
            transit_updates.append((ridx, transit))

    stats = {
        "ok": True,
        "matched": matched,
        "unmatched": unmatched,
        "name_updates": len(name_updates),
        "zone_updates": len(zone_updates),
        "transit_updates": len(transit_updates),
        "dry_run": dry_run,
        "sheet_title": ws.title,
    }
    if dry_run:
        stats["sample_names"] = name_updates[:8]
        return stats

    def _batch(col_idx0: int, items: list[tuple[int, str]]) -> None:
        if not items:
            return
        # group contiguous? just write one-by-one in chunks via update cells
        from gspread.utils import rowcol_to_a1

        data = [
            {
                "range": rowcol_to_a1(r, col_idx0 + 1),
                "values": [[v]],
            }
            for r, v in items
        ]
        chunk = 200
        for i in range(0, len(data), chunk):
            ws.batch_update(data[i : i + chunk], value_input_option="USER_ENTERED")

    _batch(col_p, name_updates)
    _batch(col_z, zone_updates)
    _batch(col_t, transit_updates)
    return stats


def sync_overview() -> dict:
    from src.hub.sheet_write import push_hub_properties_to_sheet

    return push_hub_properties_to_sheet()


def full_persist_local() -> None:
    """Heavy persist (sqlite + preview + masters) — call once before sheet/Fly."""
    projects = load_projects()
    properties = load_properties()
    all_zones: list[str] = []
    all_transit: list[str] = []
    for p in projects:
        all_zones.extend(project_zone_display(p))
        all_transit.extend(project_transit_display(p))
    ensure_labels(zones=_uniq(all_zones), transits=_uniq(all_transit))
    persist(projects, properties)
    write_preview_js(projects, properties)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--max-projects",
        type=int,
        default=220,
        help="Cap targets; use 0 with --include-rest for all projects",
    )
    ap.add_argument("--sleep", type=float, default=0.5)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--skip-living", action="store_true")
    ap.add_argument("--skip-propertyhub", action="store_true")
    ap.add_argument("--skip-incomplete", action="store_true")
    ap.add_argument("--include-rest", action="store_true")
    ap.add_argument(
        "--skip-complete",
        action="store_true",
        help="Resume: skip projects that already have zone+transit+nearby+propertyhub_url",
    )
    ap.add_argument(
        "--skip-attempted",
        action="store_true",
        help="Resume: also skip failures-log IDs and projects that already have PH url/nearby",
    )
    ap.add_argument("--checkpoint-every", type=int, default=50)
    ap.add_argument("--skip-sheet", action="store_true")
    ap.add_argument("--sheet-only", action="store_true", help="Skip enrich; only push sheet")
    ap.add_argument("--skip-backup", action="store_true")
    args = ap.parse_args()

    bdir = None
    if not args.skip_backup:
        print("=== backup ===", flush=True)
        bdir = backup_local()
        print(f"backup → {bdir}", flush=True)

    keep_ids, ph_url_by_id = _priority_project_ids()
    projects = load_projects()
    already = sum(1 for p in projects if _is_fully_enriched(p))
    print(
        f"projects={len(projects)} merged_keeps={len(keep_ids)} ph_urls={len(ph_url_by_id)} "
        f"already_complete={already}",
        flush=True,
    )

    enrich_stats: dict = {}
    if not args.sheet_only:
        targets = select_targets(
            projects,
            keep_ids=keep_ids,
            max_projects=args.max_projects,
            include_incomplete=not args.skip_incomplete,
            include_rest=args.include_rest,
            skip_complete=args.skip_complete,
            skip_attempted=args.skip_attempted,
        )
        print(f"=== enrich {len(targets)} targets ===", flush=True)
        enrich_stats = enrich_targets(
            targets,
            ph_url_by_id=ph_url_by_id,
            dry_run=args.dry_run,
            sleep_s=args.sleep,
            use_cache=not args.no_cache,
            living=not args.skip_living,
            propertyhub=not args.skip_propertyhub,
            checkpoint_every=args.checkpoint_every,
        )
        print(json.dumps({k: v for k, v in enrich_stats.items() if k != "samples"}, ensure_ascii=False, indent=2))

    sheet_stats: dict = {}
    if not args.skip_sheet and not args.dry_run:
        if args.sheet_only:
            print("=== full local persist (sqlite+preview+masters) ===", flush=True)
            full_persist_local()
        print("=== push Hubโครงการ / Hubทำเล / HubBTS ===", flush=True)
        sheet_stats["masters"] = push_sheet_masters()
        print(
            json.dumps(
                {k: {kk: vv for kk, vv in v.items() if kk != "spreadsheet_id"} for k, v in sheet_stats["masters"].items()},
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        print("=== refresh ชีตสำหรับทำงาน names+locations ===", flush=True)
        sheet_stats["work_sheet"] = refresh_work_sheet_names_and_locations(dry_run=False)
        print(json.dumps(sheet_stats["work_sheet"], ensure_ascii=False, indent=2), flush=True)
        print("=== sync ทรัพย์รวม / Hub export ===", flush=True)
        try:
            sheet_stats["overview"] = sync_overview()
            print(
                {k: sheet_stats["overview"].get(k) for k in ("ok", "pushed", "hub_count", "export_csv", "push_warning")},
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            sheet_stats["overview_error"] = str(exc)
            print("overview sync failed:", exc, flush=True)
    elif args.dry_run and not args.skip_sheet:
        sheet_stats["work_sheet_dry"] = refresh_work_sheet_names_and_locations(dry_run=True)
        print(json.dumps(sheet_stats["work_sheet_dry"], ensure_ascii=False, indent=2), flush=True)

    # Niche Pride sanity
    niche = [
        p
        for p in load_projects()
        if "niche pride" in (p.get("canonical_name") or "").lower()
        and "thonglor" in (p.get("canonical_name") or "").lower()
    ]
    result = {
        "backup": str(bdir) if bdir else None,
        "enrich": enrich_stats,
        "sheet": sheet_stats,
        "niche_pride_rows": [
            {
                "name": p.get("canonical_name"),
                "zones": project_zone_display(p),
                "transit": project_transit_display(p),
                "nearby": (p.get("nearby_places") or [])[:5],
                "source": p.get("location_source"),
                "listings": p.get("listing_count"),
            }
            for p in niche
        ],
        "projects_total": len(load_projects()),
        "coverage": _coverage_counts(load_projects()),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_path = LOG_DIR / "project_sheet_enrich_20260727_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
