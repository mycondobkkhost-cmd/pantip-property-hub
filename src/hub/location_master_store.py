"""Hub master lists for ทำเล/โซน and BTS/MRT.

Stores:
  data/zone_master.json
  data/transit_master.json

Sheet tabs (optional SoT, same spreadsheet as Hubโฟกัส):
  Hubทำเล / HubBTS
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ZONE_PATH = BASE_DIR / "data" / "zone_master.json"
TRANSIT_PATH = BASE_DIR / "data" / "transit_master.json"

_STATION_PREFIX_RE = re.compile(
    r"^(BTS|MRT|ARL|APL|Airport\s*Link)\b",
    re.I,
)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _norm_key(label: str) -> str:
    return re.sub(r"\s+", "", (label or "").strip().lower())


def _sheet_sync_flag(env_key: str) -> bool:
    flag = (os.environ.get(env_key) or "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _normalize_item(item: dict, *, kind: str) -> dict | None:
    label = str(item.get("label") or item.get("name") or "").strip()
    if not label:
        return None
    if kind == "transit" and not _STATION_PREFIX_RE.search(label):
        # Keep free-form but prefer station-looking labels
        pass
    if kind == "zone" and _STATION_PREFIX_RE.search(label):
        return None
    aliases_raw = item.get("aliases") or []
    if isinstance(aliases_raw, str):
        aliases = [a.strip() for a in re.split(r"[,，;/|]", aliases_raw) if a.strip()]
    else:
        aliases = [str(a).strip() for a in aliases_raw if str(a).strip()]
    seen_a: set[str] = set()
    clean_aliases: list[str] = []
    label_key = _norm_key(label)
    for a in aliases:
        k = _norm_key(a)
        if not k or k == label_key or k in seen_a:
            continue
        seen_a.add(k)
        clean_aliases.append(a)
    return {
        "id": str(item.get("id") or "").strip() or ("zm_" + uuid.uuid4().hex[:10]),
        "label": label,
        "aliases": clean_aliases,
        "created_at": str(item.get("created_at") or "").strip() or _now(),
        "updated_at": str(item.get("updated_at") or "").strip() or _now(),
    }


def _load(path: Path, *, kind: str) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        raw = data.get("items") or data.get("labels") or []
    elif isinstance(data, list):
        raw = data
    else:
        raw = []
    out: list[dict] = []
    seen: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            entry = {"label": entry}
        if not isinstance(entry, dict):
            continue
        item = _normalize_item(entry, kind=kind)
        if not item:
            continue
        key = _norm_key(item["label"])
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _save(path: Path, items: list[dict], *, kind: str, sync_sheet: bool) -> list[dict]:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized: list[dict] = []
    seen: set[str] = set()
    for entry in items:
        item = _normalize_item(dict(entry), kind=kind)
        if not item:
            continue
        key = _norm_key(item["label"])
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    normalized.sort(key=lambda x: (x.get("label") or "").casefold())
    path.write_text(
        json.dumps(
            {"items": normalized, "updated_at": _now()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if sync_sheet:
        _push_sheet(kind, normalized)
    return normalized


def _push_sheet(kind: str, items: list[dict]) -> None:
    env_key = "HUB_ZONES_SHEET_SYNC" if kind == "zone" else "HUB_TRANSITS_SHEET_SYNC"
    if not _sheet_sync_flag(env_key):
        return
    try:
        from src.hub.hub_state_sheet import (
            push_transits_to_sheet,
            push_zones_to_sheet,
        )

        if kind == "zone":
            push_zones_to_sheet(items)
        else:
            push_transits_to_sheet(items)
    except Exception as exc:  # noqa: BLE001
        print(f"[hub] {kind} master sheet push failed: {exc}")


def load_zones() -> list[dict]:
    return _load(ZONE_PATH, kind="zone")


def load_transits() -> list[dict]:
    return _load(TRANSIT_PATH, kind="transit")


def save_zones(items: list[dict], *, sync_sheet: bool = True) -> list[dict]:
    return _save(ZONE_PATH, items, kind="zone", sync_sheet=sync_sheet)


def save_transits(items: list[dict], *, sync_sheet: bool = True) -> list[dict]:
    return _save(TRANSIT_PATH, items, kind="transit", sync_sheet=sync_sheet)


def list_zones() -> list[dict]:
    return sorted(load_zones(), key=lambda x: (x.get("label") or "").casefold())


def list_transits() -> list[dict]:
    return sorted(load_transits(), key=lambda x: (x.get("label") or "").casefold())


def zone_labels() -> list[str]:
    return [z["label"] for z in list_zones()]


def transit_labels() -> list[str]:
    return [t["label"] for t in list_transits()]


def find_by_label(items: list[dict], label: str) -> dict | None:
    want = _norm_key(label)
    if not want:
        return None
    for it in items:
        if _norm_key(it.get("label") or "") == want:
            return it
        for a in it.get("aliases") or []:
            if _norm_key(a) == want:
                return it
    return None


def ensure_zone(label: str) -> dict:
    label = (label or "").strip()
    if not label:
        raise ValueError("กรุณาระบุชื่อทำเล / โซน")
    if _STATION_PREFIX_RE.search(label):
        raise ValueError("ทำเลไม่ควรขึ้นต้นด้วย BTS/MRT — ใส่ในมาสเตอร์สถานีแทน")
    items = load_zones()
    existing = find_by_label(items, label)
    if existing:
        return existing
    item = _normalize_item({"label": label}, kind="zone")
    assert item is not None
    items.append(item)
    save_zones(items)
    return item


def ensure_transit(label: str) -> dict:
    label = (label or "").strip()
    if not label:
        raise ValueError("กรุณาระบุชื่อสถานี BTS / MRT")
    try:
        from src.hub.project_store import parse_station_tags

        parsed = parse_station_tags(label)
        if parsed:
            label = parsed[0]
    except Exception:  # noqa: BLE001
        pass
    items = load_transits()
    existing = find_by_label(items, label)
    if existing:
        return existing
    item = _normalize_item({"label": label}, kind="transit")
    assert item is not None
    items.append(item)
    save_transits(items)
    return item


def ensure_labels(*, zones: list[str] | None = None, transits: list[str] | None = None) -> dict:
    """Ensure many labels exist (used when saving project standard form)."""
    z_out: list[dict] = []
    t_out: list[dict] = []
    for z in zones or []:
        z = str(z or "").strip()
        if not z or _STATION_PREFIX_RE.search(z):
            continue
        try:
            z_out.append(ensure_zone(z))
        except ValueError:
            continue
    for t in transits or []:
        t = str(t or "").strip()
        if not t:
            continue
        try:
            t_out.append(ensure_transit(t))
        except ValueError:
            continue
    return {"zones": z_out, "transits": t_out}


def update_zone(item_id: str, *, label: str | None = None, aliases: list[str] | None = None) -> dict:
    items = load_zones()
    target = next((x for x in items if x.get("id") == item_id), None)
    if not target:
        raise ValueError("ไม่พบทำเลในมาสเตอร์")
    if label is not None:
        label = label.strip()
        if not label:
            raise ValueError("ชื่อทำเลว่างไม่ได้")
        if _STATION_PREFIX_RE.search(label):
            raise ValueError("ทำเลไม่ควรขึ้นต้นด้วย BTS/MRT")
        clash = find_by_label(items, label)
        if clash and clash.get("id") != item_id:
            raise ValueError(f"มี「{clash['label']}」อยู่แล้ว")
        target["label"] = label
    if aliases is not None:
        target["aliases"] = aliases
    target["updated_at"] = _now()
    save_zones(items)
    return target


def update_transit(item_id: str, *, label: str | None = None, aliases: list[str] | None = None) -> dict:
    items = load_transits()
    target = next((x for x in items if x.get("id") == item_id), None)
    if not target:
        raise ValueError("ไม่พบสถานีในมาสเตอร์")
    if label is not None:
        label = label.strip()
        if not label:
            raise ValueError("ชื่อสถานีว่างไม่ได้")
        try:
            from src.hub.project_store import parse_station_tags

            parsed = parse_station_tags(label)
            if parsed:
                label = parsed[0]
        except Exception:  # noqa: BLE001
            pass
        clash = find_by_label(items, label)
        if clash and clash.get("id") != item_id:
            raise ValueError(f"มี「{clash['label']}」อยู่แล้ว")
        target["label"] = label
    if aliases is not None:
        target["aliases"] = aliases
    target["updated_at"] = _now()
    save_transits(items)
    return target


def delete_zone(item_id: str) -> dict:
    items = load_zones()
    keep = [x for x in items if x.get("id") != item_id]
    if len(keep) == len(items):
        raise ValueError("ไม่พบทำเลในมาสเตอร์")
    save_zones(keep)
    return {"ok": True, "deleted": item_id}


def delete_transit(item_id: str) -> dict:
    items = load_transits()
    keep = [x for x in items if x.get("id") != item_id]
    if len(keep) == len(items):
        raise ValueError("ไม่พบสถานีในมาสเตอร์")
    save_transits(keep)
    return {"ok": True, "deleted": item_id}


def collect_labels_from_dataset() -> tuple[list[str], list[str]]:
    """Unique zone / transit labels from projects (+ property fallbacks)."""
    from src.hub.project_store import (
        load_projects,
        load_properties,
        parse_station_tags,
        parse_tag_list,
        project_transit_display,
        project_zone_display,
    )

    zones: dict[str, str] = {}
    transits: dict[str, str] = {}

    def add_zone(raw: str) -> None:
        for z in parse_tag_list(raw):
            if _STATION_PREFIX_RE.search(z):
                continue
            if len(z) > 40:
                continue
            k = _norm_key(z)
            if k and k not in zones:
                zones[k] = z

    def add_transit(raw: str) -> None:
        for t in parse_station_tags(raw) or parse_tag_list(raw):
            if not _STATION_PREFIX_RE.search(t):
                continue
            if len(t) > 60:
                continue
            k = _norm_key(t)
            if k and k not in transits:
                transits[k] = t

    for proj in load_projects():
        for z in project_zone_display(proj):
            add_zone(z)
        for t in project_transit_display(proj):
            add_transit(t)

    for prop in load_properties():
        loc = str(prop.get("location_ref") or "").strip()
        if loc:
            for part in parse_tag_list(loc):
                if _STATION_PREFIX_RE.search(part):
                    add_transit(part)
                else:
                    add_zone(part)
        for t in prop.get("transit_from_sheet") or []:
            add_transit(str(t))

    # Built-in popular corridor chips
    for label in (
        "ทองหล่อ",
        "เอกมัย",
        "พร้อมพงษ์",
        "อโศก",
        "เพชรบุรี",
        "พระราม 9",
        "รัชดา",
        "สุขุมวิท",
        "อ่อนนุช",
        "บางนา",
        "ลาดพร้าว",
        "อารีย์",
        "สาทร",
        "สีลม",
        "รามคำแหง",
    ):
        add_zone(label)

    return (
        sorted(zones.values(), key=lambda x: x.casefold()),
        sorted(transits.values(), key=lambda x: x.casefold()),
    )


def seed_from_dataset(*, force: bool = False) -> dict:
    """Fill empty masters from projects/properties. force=True merges missing labels."""
    z_labels, t_labels = collect_labels_from_dataset()
    existing_z = load_zones()
    existing_t = load_transits()

    if not force and existing_z and existing_t:
        return {
            "ok": True,
            "seeded": False,
            "zones": len(existing_z),
            "transits": len(existing_t),
        }

    z_map = {_norm_key(x["label"]): x for x in existing_z}
    for label in z_labels:
        k = _norm_key(label)
        if k and k not in z_map:
            item = _normalize_item({"label": label}, kind="zone")
            if item:
                z_map[k] = item
    t_map = {_norm_key(x["label"]): x for x in existing_t}
    for label in t_labels:
        k = _norm_key(label)
        if k and k not in t_map:
            item = _normalize_item({"label": label}, kind="transit")
            if item:
                t_map[k] = item

    zones = save_zones(list(z_map.values()), sync_sheet=True)
    transits = save_transits(list(t_map.values()), sync_sheet=True)
    return {
        "ok": True,
        "seeded": True,
        "zones": len(zones),
        "transits": len(transits),
    }


def ensure_masters_ready() -> dict:
    """Boot helper: seed if empty, then return counts."""
    z = load_zones()
    t = load_transits()
    if not z or not t:
        return seed_from_dataset(force=True)
    return {"ok": True, "seeded": False, "zones": len(z), "transits": len(t)}


def replace_zones_from_sheet() -> dict:
    from src.hub.hub_state_sheet import pull_zones_from_sheet

    items = pull_zones_from_sheet()
    save_zones(items, sync_sheet=False)
    return {"ok": True, "count": len(items), "source": "sheet"}


def replace_transits_from_sheet() -> dict:
    from src.hub.hub_state_sheet import pull_transits_from_sheet

    items = pull_transits_from_sheet()
    save_transits(items, sync_sheet=False)
    return {"ok": True, "count": len(items), "source": "sheet"}
