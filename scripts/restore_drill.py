#!/usr/bin/env python3
"""Source-immutable restore drill — never mutates the source backup directory.

SOURCE BACKUP DIRECTORY
        |
        | READ ONLY
        v
ISOLATED TEMP / RESTORE DIRECTORY
        |
        v
VALIDATION / optional smoke hooks
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.backup_data_dir import backup_data_dir, restore_data_dir, verify_backup

BACKUP_SCHEMA = "pantip-data-backup/v1"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out.append(p)
    return out


def snapshot_directory(root: Path) -> dict[str, str]:
    """Relative path → SHA-256 for every file under root."""
    root = root.resolve()
    snap: dict[str, str] = {}
    for path in _iter_files(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        snap[rel] = _sha256_file(path)
    return snap


def _reject_path_relationship(*, source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise ValueError("restore destination must differ from source backup")
    if source in destination.parents or destination == source:
        raise ValueError("restore destination must not be nested inside source backup")
    if destination in source.parents:
        # destination is an ancestor of source — also unsafe contamination risk
        raise ValueError("restore destination must not be an ancestor of source backup")


def _ensure_destination_absent_or_empty(destination: Path) -> None:
    if not destination.exists():
        return
    if not destination.is_dir():
        raise ValueError("restore destination exists and is not a directory")
    if any(destination.iterdir()):
        raise ValueError("restore destination must be absent or an empty directory")


def validate_restored_catalog(restore_dir: Path) -> dict[str, Any]:
    """Structural integrity checks on an isolated restored catalog (no PII dump)."""
    restore_dir = restore_dir.resolve()
    props_path = restore_dir / "properties.json"
    projs_path = restore_dir / "projects.json"
    if not props_path.is_file() or not projs_path.is_file():
        raise ValueError("restored catalog missing properties.json or projects.json")

    try:
        props = json.loads(props_path.read_text(encoding="utf-8"))
        projs = json.loads(projs_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"restored catalog JSON invalid: {exc}") from exc

    if not isinstance(props, list) or not props:
        raise ValueError("restored properties.json empty or not a list")
    if not isinstance(projs, list) or not projs:
        raise ValueError("restored projects.json empty or not a list")

    prop_ids = [str(p.get("id") or "").strip() for p in props if isinstance(p, dict)]
    proj_ids = [str(p.get("id") or "").strip() for p in projs if isinstance(p, dict)]
    prop_id_counts = Counter(x for x in prop_ids if x)
    proj_id_counts = Counter(x for x in proj_ids if x)
    dup_prop_ids = sorted(k for k, n in prop_id_counts.items() if n > 1)
    dup_proj_ids = sorted(k for k, n in proj_id_counts.items() if n > 1)

    missing_project_id = sum(
        1
        for p in props
        if isinstance(p, dict) and not str(p.get("project_id") or "").strip()
    )
    proj_set = {x for x in proj_ids if x}
    orphan_project_refs = 0
    for p in props:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("project_id") or "").strip()
        if pid and pid not in proj_set:
            orphan_project_refs += 1

    codes = [
        str(p.get("code") or "").strip().upper()
        for p in props
        if isinstance(p, dict)
    ]
    code_counts = Counter(c for c in codes if c)
    duplicate_property_code_groups = sum(1 for _, n in code_counts.items() if n > 1)

    identity_ok = not dup_prop_ids and not dup_proj_ids
    out = {
        "ok": identity_ok,
        "property_count": len(props),
        "project_count": len(projs),
        "duplicate_property_id_count": len(dup_prop_ids),
        "duplicate_project_id_count": len(dup_proj_ids),
        "missing_project_id_count": missing_project_id,
        "orphan_project_ref_count": orphan_project_refs,
        "duplicate_property_code_group_count": duplicate_property_code_groups,
        "identity_corruption": bool(dup_prop_ids or dup_proj_ids),
        # duplicate property_code is allowed and is NOT identity corruption
        "duplicate_property_code_is_corruption": False,
    }
    if dup_prop_ids:
        out["error"] = "duplicate property_id detected"
    elif dup_proj_ids:
        out["error"] = "duplicate project_id detected"
    return out


def run_restore_drill(
    source_backup: Path | None = None,
    restore_destination: Path | None = None,
    *,
    data_dir: Path | None = None,
) -> dict[str, Any]:
    """Run a source-immutable restore drill.

    Parameters
    ----------
    source_backup:
        Directory containing authoritative JSON to back up (READ-ONLY).
    restore_destination:
        Optional empty/absent destination for restored files.
        If omitted, an isolated temporary directory is used.
    data_dir:
        Deprecated alias for ``source_backup`` (kept for Phase C callers).
    """
    if source_backup is None and data_dir is not None:
        source_backup = data_dir
    if source_backup is None:
        raise ValueError("source_backup is required")

    source = Path(source_backup).resolve()
    if not source.is_dir():
        raise ValueError(f"source backup not found: {source}")
    if not (source / "properties.json").is_file():
        raise ValueError(f"properties.json missing in {source}")
    if not (source / "projects.json").is_file():
        raise ValueError(f"projects.json missing in {source}")

    source_before = snapshot_directory(source)
    source_file_list_before = sorted(source_before.keys())

    external_dest = Path(restore_destination).resolve() if restore_destination else None
    if external_dest is not None:
        _reject_path_relationship(source=source, destination=external_dest)
        _ensure_destination_absent_or_empty(external_dest)

    with tempfile.TemporaryDirectory(prefix="ptp-restore-drill-") as td:
        root = Path(td)
        backup_out = backup_data_dir(source, dest=root / "backup")
        backup_dir = Path(backup_out["backup_dir"]).resolve()
        verify = verify_backup(backup_dir)
        if not verify.get("ok"):
            raise ValueError("backup verify failed: " + "; ".join(verify.get("errors") or []))

        if external_dest is not None:
            restore_dir = external_dest
            restore_dir.mkdir(parents=True, exist_ok=True)
        else:
            restore_dir = (root / "restored").resolve()

        _reject_path_relationship(source=source, destination=restore_dir)
        _ensure_destination_absent_or_empty(restore_dir)
        restore_dir.mkdir(parents=True, exist_ok=True)

        result = restore_data_dir(backup_dir, restore_dir, dry_run=False)
        integrity = validate_restored_catalog(restore_dir)
        if not integrity.get("ok"):
            raise ValueError(integrity.get("error") or "restored catalog identity check failed")

        # Corruption simulation ONLY on an isolated copy — never on source.
        corrupt_dir = root / "corrupt-check"
        shutil.copytree(restore_dir, corrupt_dir)
        (corrupt_dir / "properties.json").write_text("[]", encoding="utf-8")
        corrupt_detected = False
        try:
            validate_restored_catalog(corrupt_dir)
        except ValueError:
            corrupt_detected = True
        if not corrupt_detected:
            raise ValueError("corruption simulation did not detect empty properties.json")

        source_after = snapshot_directory(source)
        if source_after != source_before:
            raise ValueError("source backup was mutated during restore drill — abort")
        if sorted(source_after.keys()) != source_file_list_before:
            raise ValueError("source backup file list changed during restore drill — abort")

        # Persist restored tree outside temp if external destination was requested;
        # temp restore_dir is already under TemporaryDirectory and will be removed.
        restored_property_count = integrity["property_count"]
        out: dict[str, Any] = {
            "ok": True,
            "source_backup": str(source),
            "restore_destination": str(restore_dir) if external_dest is not None else str(restore_dir),
            "restore_is_ephemeral": external_dest is None,
            "backup_dir": str(backup_dir),
            "restored_property_count": restored_property_count,
            "restored_project_count": integrity["project_count"],
            "source_immutable": True,
            "source_file_count": len(source_before),
            "corruption_simulation_detected": True,
            "integrity": integrity,
            "verify": verify,
            "restore": result,
            "schema_note": BACKUP_SCHEMA,
        }
        if external_dest is None:
            # Copy restored catalog summary only — files vanish with temp dir;
            # Phase C only needs counts. For durable restore, pass restore_destination.
            out["note"] = (
                "restore_destination was ephemeral; "
                "pass --restore-destination for a durable isolated restore"
            )
        return out


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Source-immutable restore drill. "
            "Never writes to --source-backup. No production/in-place mode."
        )
    )
    parser.add_argument(
        "--source-backup",
        type=Path,
        required=True,
        help="Read-only source directory (e.g. a backup or synthetic seed copy)",
    )
    parser.add_argument(
        "--restore-destination",
        type=Path,
        default=None,
        help="Empty/absent isolated destination (optional; defaults to temp dir)",
    )
    args = parser.parse_args()
    try:
        result = run_restore_drill(
            source_backup=args.source_backup,
            restore_destination=args.restore_destination,
        )
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
