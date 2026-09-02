#!/usr/bin/env python3
"""Read-only backup/restore helpers for Hub DATA_DIR (synthetic/local use in Phase B)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKUP_SCHEMA = "pantip-data-backup/v1"

# Authoritative SoT — backup must fail if unreadable when present and required.
AUTHORITATIVE_FILES: tuple[str, ...] = (
    "properties.json",
    "projects.json",
)

# Important runtime JSON — included when present; missing is OK.
RUNTIME_OPTIONAL_FILES: tuple[str, ...] = (
    "customer_cases.json",
    "current_tenants.json",
    "focus_properties.json",
    "wait_post_queue.json",
    "group_publish_jobs.json",
    "group_post_links.json",
    "group_post_codes.json",
    "fetch_post_jobs.json",
    "auto_follow.json",
    "post_footer_snippets.json",
    "facebook_groups.json",
    "project_aliases.json",
    "zone_master.json",
    "transit_master.json",
)

# Derived/regenerable — excluded by default.
DERIVED_SKIP_FILES: tuple[str, ...] = (
    "preview-data.js",
    "preview-data.meta.json",
    "hub_overview_export.csv",
    "main_sheet.csv",
    "hub_sheet_export.csv",
    "wait_post_sheet.csv",
    "customer_followup_export.csv",
    "caption_copy_history.json",
    "hub.db",
)

# Never include secrets/tokens in ordinary data backup.
SECRET_SKIP_FILES: tuple[str, ...] = (
    "fb_agent.json",
    ".env",
)

CACHE_DIR_NAMES: tuple[str, ...] = (
    "propertyhub_cache",
    "thumb_cache",
    "living_cache",
    "publish_uploads",
    "co_traffic",
)

_TRAVERSAL = re.compile(r"(^|[/\\])\.\.([/\\]|$)")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_in_data_dir(data_dir: Path, rel: str) -> Path:
    if _TRAVERSAL.search(rel.replace("\\", "/")):
        raise ValueError(f"path traversal rejected: {rel}")
    base = data_dir.resolve()
    target = (base / rel).resolve()
    if base not in target.parents and target != base:
        raise ValueError(f"path escapes DATA_DIR: {rel}")
    return target


def classify_relative_path(rel: str) -> str:
    name = Path(rel).name
    if name in SECRET_SKIP_FILES or name.startswith(".env"):
        return "secret"
    parts = Path(rel).parts
    if parts and parts[0] in CACHE_DIR_NAMES:
        return "cache"
    if name in DERIVED_SKIP_FILES:
        return "derived"
    if name in AUTHORITATIVE_FILES:
        return "authoritative"
    if name in RUNTIME_OPTIONAL_FILES:
        return "runtime"
    return "other"


def backup_entries(data_dir: Path) -> list[str]:
    """Relative paths eligible for backup (files only, no cache dirs)."""
    base = data_dir.resolve()
    if not base.is_dir():
        raise ValueError(f"DATA_DIR not found: {base}")
    out: list[str] = []
    for rel in (*AUTHORITATIVE_FILES, *RUNTIME_OPTIONAL_FILES):
        p = base / rel
        if p.is_file():
            out.append(rel)
    return sorted(set(out))


def backup_data_dir(data_dir: Path, *, dest: Path | None = None) -> dict[str, Any]:
    """Copy eligible files into timestamped backup directory with manifest."""
    base = data_dir.resolve()
    if not base.is_dir():
        raise ValueError(f"DATA_DIR not found: {base}")

    created_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = (dest or (base.parent / "backups" / f"data-backup-{stamp}")).resolve()
    if base in out_dir.parents or out_dir == base:
        raise ValueError("backup destination must not be inside DATA_DIR")
    out_dir.mkdir(parents=True, exist_ok=False)

    files_meta: list[dict[str, Any]] = []
    for rel in backup_entries(base):
        classification = classify_relative_path(rel)
        if classification in {"secret", "cache", "derived"}:
            continue
        src = _resolve_in_data_dir(base, rel)
        if not src.is_file():
            continue
        try:
            raw = src.read_bytes()
        except OSError as exc:
            if rel in AUTHORITATIVE_FILES:
                raise ValueError(f"unreadable authoritative file: {rel}") from exc
            continue
        if rel in AUTHORITATIVE_FILES:
            try:
                json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid JSON in authoritative file: {rel}") from exc
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
        files_meta.append(
            {
                "path": rel,
                "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "classification": classification,
            }
        )

    for req in AUTHORITATIVE_FILES:
        if not any(x["path"] == req for x in files_meta):
            raise ValueError(f"missing critical authoritative file: {req}")

    manifest = {
        "schema": BACKUP_SCHEMA,
        "created_at": created_at,
        "data_dir": str(base),
        "files": files_meta,
        "excluded_policy": {
            "derived": list(DERIVED_SKIP_FILES),
            "secret": list(SECRET_SKIP_FILES),
            "cache_dirs": list(CACHE_DIR_NAMES),
        },
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "backup_dir": str(out_dir), "manifest": str(manifest_path), "file_count": len(files_meta)}


def load_manifest(backup_dir: Path) -> dict[str, Any]:
    path = backup_dir / "manifest.json"
    if not path.is_file():
        raise ValueError("manifest.json missing")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("manifest.json corrupt") from exc
    if data.get("schema") != BACKUP_SCHEMA:
        raise ValueError("unsupported backup schema")
    return data


def verify_backup(backup_dir: Path) -> dict[str, Any]:
    manifest = load_manifest(backup_dir)
    errors: list[str] = []
    for entry in manifest.get("files") or []:
        rel = str(entry.get("path") or "")
        if not rel or _TRAVERSAL.search(rel.replace("\\", "/")):
            errors.append(f"invalid manifest path: {rel}")
            continue
        target = backup_dir / rel
        if not target.is_file():
            errors.append(f"missing file: {rel}")
            continue
        digest = _sha256_file(target)
        if digest != entry.get("sha256"):
            errors.append(f"checksum mismatch: {rel}")
    return {"ok": not errors, "errors": errors, "file_count": len(manifest.get("files") or [])}


def restore_data_dir(
    backup_dir: Path,
    dest_dir: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Restore into a NEW destination directory (never overwrite source by default)."""
    backup_dir = backup_dir.resolve()
    dest_dir = dest_dir.resolve()
    if backup_dir == dest_dir:
        raise ValueError("restore destination must differ from backup directory")
    manifest = load_manifest(backup_dir)
    verify = verify_backup(backup_dir)
    if not verify.get("ok"):
        raise ValueError("backup verification failed: " + "; ".join(verify.get("errors") or []))

    planned: list[str] = []
    for entry in manifest.get("files") or []:
        rel = str(entry.get("path") or "")
        src = backup_dir / rel
        dst = dest_dir / rel
        if dest_dir not in dst.resolve().parents:
            raise ValueError(f"path traversal on restore: {rel}")
        planned.append(rel)
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    return {
        "ok": True,
        "dry_run": dry_run,
        "dest_dir": str(dest_dir),
        "restored_files": planned,
        "file_count": len(planned),
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Backup Hub DATA_DIR (read-only)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_backup = sub.add_parser("backup", help="Create timestamped backup")
    p_backup.add_argument("data_dir", type=Path)
    p_backup.add_argument("--dest", type=Path, default=None)

    p_verify = sub.add_parser("verify", help="Verify backup checksums")
    p_verify.add_argument("backup_dir", type=Path)

    p_restore = sub.add_parser("restore", help="Restore backup into new directory")
    p_restore.add_argument("backup_dir", type=Path)
    p_restore.add_argument("dest_dir", type=Path)
    p_restore.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    try:
        if args.cmd == "backup":
            result = backup_data_dir(args.data_dir, dest=args.dest)
        elif args.cmd == "verify":
            result = verify_backup(args.backup_dir)
        else:
            result = restore_data_dir(args.backup_dir, args.dest_dir, dry_run=args.dry_run)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
