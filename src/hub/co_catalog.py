"""Read-only Co-Agent catalog — slim listings for public /co site."""

from __future__ import annotations

import re
from typing import Any

from src.hub.customer_match import bed_category, recommend_for_case, score_property_for_case
from src.hub.project_store import (
    load_projects,
    load_properties,
    project_transit_display,
    project_zone_display,
)


def _parse_price(s: Any) -> int:
    digits = re.sub(r"[^\d]", "", str(s or ""))
    return int(digits) if digits else 0


def _has_price(s: Any) -> bool:
    v = str(s or "").strip()
    return bool(v) and v not in {"-", "—", "0"}


def _soft(s: Any) -> str:
    return re.sub(r"[^a-z0-9ก-๙]+", "", str(s or "").lower())


def _as_str_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [x.strip() for x in re.split(r"[,，|/]+", val) if x.strip()]
    if isinstance(val, (list, tuple, set)):
        out: list[str] = []
        for x in val:
            s = str(x or "").strip()
            if s:
                out.append(s)
        return out
    return []


def listing_post_url(prop: dict) -> tuple[str, str]:
    """Prefer Pantip page post; fall back to personal FB post (post_url)."""
    page = (prop.get("post_pages_url") or "").strip()
    if page.startswith("http"):
        return page, "page"
    personal = (prop.get("post_url") or "").strip()
    if personal.startswith("http"):
        return personal, "personal"
    return "", ""


def page_post_url(prop: dict) -> str:
    """Backward-compatible: best open/thumb URL (page, else personal)."""
    url, _kind = listing_post_url(prop)
    return url


def _size_n(s: Any) -> float:
    raw = str(s or "").strip().replace(",", "")
    if not raw or raw in {"-", "—"}:
        return 0.0
    m = re.search(r"[\d.]+", raw)
    if not m:
        return 0.0
    try:
        return float(m.group(0))
    except ValueError:
        return 0.0


def slim_property(
    prop: dict,
    proj: dict,
    *,
    require_page: bool = False,
    include_archived: bool = True,
) -> dict | None:
    """Slim row for Co-Agent.

    Catalog mirrors Hub default (all eras, page optional). Match keeps active-only.
    """
    code = (prop.get("code") or "").strip()
    if not code:
        return None

    url, link_kind = listing_post_url(prop)
    if require_page and not url:
        return None

    status = (prop.get("import_status") or "").strip()
    if not include_archived and status and status not in {"active", "needs_review", ""}:
        return None

    zones = project_zone_display(proj) or []
    transit = project_transit_display(proj) or []
    if not zones and prop.get("location_ref"):
        zones = [z.strip() for z in str(prop["location_ref"]).split(",") if z.strip()][:4]
    if not transit and prop.get("transit_from_sheet"):
        transit = list(prop.get("transit_from_sheet") or [])[:4]

    size_sqm = prop.get("size_sqm") or ""
    return {
        "code": code,
        "project_id": prop.get("project_id") or "",
        "project_name": prop.get("project_name") or proj.get("canonical_name") or "",
        "property_type": prop.get("property_type") or "",
        "bedrooms": prop.get("bedrooms") or "",
        "bed_cat": bed_category(prop.get("bedrooms")),
        "size_sqm": size_sqm,
        "size_n": _size_n(size_sqm),
        "rent_price": prop.get("rent_price") or "",
        "sale_price": prop.get("sale_price") or "",
        "rent_n": _parse_price(prop.get("rent_price")) if _has_price(prop.get("rent_price")) else 0,
        "sale_n": _parse_price(prop.get("sale_price")) if _has_price(prop.get("sale_price")) else 0,
        "zones": zones[:4],
        "transit": transit[:4],
        "page_url": url,
        "link_kind": link_kind,
        "last_listed_at": prop.get("last_listed_at") or "",
    }


_CO_ITEM_KEYS = (
    "code",
    "project_id",
    "project_name",
    "property_type",
    "bedrooms",
    "bed_cat",
    "size_sqm",
    "size_n",
    "rent_price",
    "sale_price",
    "rent_n",
    "sale_n",
    "zones",
    "transit",
    "page_url",
    "link_kind",
    "last_listed_at",
)


def _pack_items(items: list[dict]) -> list[list]:
    """Column-pack rows to shrink JSON (repeated keys dominate payload size)."""
    keys = _CO_ITEM_KEYS
    out: list[list] = []
    for it in items:
        out.append([it.get(k) for k in keys])
    return out


def build_co_catalog(*, limit: int | None = None) -> dict:
    projects = {p.get("id"): p for p in load_projects()}
    props = load_properties()
    items: list[dict] = []
    zone_counts: dict[str, int] = {}
    transit_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    project_opts: dict[str, dict] = {}

    for prop in props:
        proj = projects.get(prop.get("project_id")) or {}
        # Same universe as Hub list (includes archived); page link optional for thumbs.
        slim = slim_property(prop, proj, require_page=False, include_archived=True)
        if not slim:
            continue
        items.append(slim)
        for z in slim.get("zones") or []:
            zone_counts[z] = zone_counts.get(z, 0) + 1
        for t in slim.get("transit") or []:
            transit_counts[t] = transit_counts.get(t, 0) + 1
        ptype = (slim.get("property_type") or "").strip()
        if ptype:
            type_counts[ptype] = type_counts.get(ptype, 0) + 1
        pid = slim.get("project_id") or ""
        pname = slim.get("project_name") or ""
        if pid and pname and pid not in project_opts:
            aliases = [str(a).strip() for a in (proj.get("aliases") or []) if str(a).strip()]
            project_opts[pid] = {
                "id": pid,
                "name": pname,
                "aliases": aliases[:8],
            }

    # Newest first by real date (DD/MM/YYYY), not lexicographic string order.
    def _sort_key(it: dict) -> tuple:
        raw = str(it.get("last_listed_at") or "")
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
        if not m:
            return (0, 0, 0, it.get("code") or "")
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return (y, mo, d, it.get("code") or "")

    items.sort(key=_sort_key, reverse=True)
    if limit:
        items = items[: int(limit)]

    zones = sorted(zone_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    transits = sorted(transit_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    types = sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    projects_list = sorted(project_opts.values(), key=lambda x: x["name"])

    return {
        "ok": True,
        "count": len(items),
        # Packed rows keep payload small enough for mobile browsers.
        "keys": list(_CO_ITEM_KEYS),
        "rows": _pack_items(items),
        "filters": {
            "zones": [{"label": k, "count": v} for k, v in zones],
            "transits": [{"label": k, "count": v} for k, v in transits],
            "property_types": [{"label": k, "count": v} for k, v in types],
            "projects": projects_list,
            "beds": [
                {"value": "studio", "label": "Studio"},
                {"value": "1", "label": "1 นอน"},
                {"value": "2", "label": "2 นอน"},
                {"value": "3", "label": "3+ นอน"},
                {"value": "duplex", "label": "Duplex"},
                {"value": "penthouse", "label": "Penthouse"},
            ],
        },
        "line": {
            "id": "@PTP.CONDO",
            "url": "https://lin.ee/5W00Nwl",
        },
        "brand": "Pantip Property ( Co-Agent Stock )",
    }


def _project_search_blob(slim: dict, proj: dict) -> str:
    parts = [
        slim.get("project_name") or "",
        proj.get("canonical_name") or "",
        slim.get("code") or "",
    ]
    parts.extend(str(a) for a in (proj.get("aliases") or []))
    return _soft(" ".join(parts))


def _parse_project_filters(brief: dict, projects: dict[str, dict]) -> tuple[set[str], list[str]]:
    """Return (project_ids, soft_queries). IDs win; bare names become soft queries."""
    ids: set[str] = set(_as_str_list(brief.get("project_ids")))
    queries: list[str] = []

    for raw in (
        _as_str_list(brief.get("projects"))
        + _as_str_list(brief.get("project"))
        + _as_str_list(brief.get("project_query"))
    ):
        if raw in projects:
            ids.add(raw)
            continue
        # Resolve exact / soft name → id when possible
        soft_q = _soft(raw)
        resolved = False
        if soft_q:
            for pid, proj in projects.items():
                blob = _soft(
                    " ".join(
                        [str(proj.get("canonical_name") or "")]
                        + [str(a) for a in (proj.get("aliases") or [])]
                    )
                )
                if soft_q in blob or blob in soft_q:
                    ids.add(pid)
                    resolved = True
        if not resolved:
            queries.append(raw)

    # de-dupe soft queries
    seen: set[str] = set()
    uniq_q: list[str] = []
    for q in queries:
        k = _soft(q)
        if not k or k in seen:
            continue
        seen.add(k)
        uniq_q.append(q)
    return ids, uniq_q


def _normalize_deal(raw: Any) -> str:
    deal = str(raw or "all").strip().lower() or "all"
    if deal in {"", "all", "any", "ทั้งหมด"}:
        return "both"
    if deal in {"buy", "sale", "sell", "ขาย", "ซื้อ"}:
        return "sale"
    if deal in {"rent", "เช่า"}:
        return "rent"
    if deal == "both":
        return "both"
    return deal


def _locations_to_str(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (list, tuple, set)):
        return ", ".join(str(x).strip() for x in raw if str(x).strip())
    return str(raw).strip()


def _passes_size(slim: dict, size_min: float, size_max: float) -> bool:
    n = float(slim.get("size_n") or 0)
    if size_min and (not n or n < size_min):
        return False
    if size_max and (not n or n > size_max):
        return False
    return True


def match_co_brief(brief: dict, *, limit: int = 30) -> dict:
    """Reuse Hub matcher; active rows; open URL = page post or personal post."""
    projects = {p.get("id"): p for p in load_projects()}
    project_ids, project_queries = _parse_project_filters(brief, projects)

    try:
        size_min = float(brief.get("size_min") or 0)
    except (TypeError, ValueError):
        size_min = 0.0
    try:
        size_max = float(brief.get("size_max") or 0)
    except (TypeError, ValueError):
        size_max = 0.0

    case = {
        "deal_type": _normalize_deal(brief.get("deal_type")),
        "budget_min": brief.get("budget_min") or 0,
        "budget_max": brief.get("budget_max") or 0,
        "locations": _locations_to_str(brief.get("locations")),
        "transits": _as_str_list(brief.get("transits")),
        "bedrooms": brief.get("bedrooms") or [],
        "property_types": _as_str_list(brief.get("property_types")),
        "brief": "",
        "inquiry_codes": [],
        "offered_codes": [],
        "viewing_codes": [],
    }

    # Keep free-text project names in brief for soft boost when not resolved to ids
    if project_queries:
        case["brief"] = " ".join(project_queries).strip()

    lim = max(1, int(limit or 30))

    def _finish(scored_or_items: list) -> dict:
        return {
            "ok": True,
            "count": len(scored_or_items),
            "matched": len(scored_or_items),
            "items": scored_or_items,
        }

    # Selected projects: score all matching listings (don't rely on global top-N).
    if project_ids or project_queries:
        soft_needles = [_soft(q) for q in project_queries if _soft(q)]
        scored: list[tuple[int, list[str], dict]] = []
        for prop in load_properties():
            pid = prop.get("project_id") or ""
            proj = projects.get(pid) or {}
            if project_ids and pid not in project_ids:
                continue
            # Match for co-agents: live stock only (skip archived).
            slim = slim_property(prop, proj, require_page=False, include_archived=False)
            if not slim:
                continue
            if not _passes_size(slim, size_min, size_max):
                continue
            if soft_needles and not project_ids:
                blob = _project_search_blob(slim, proj)
                if not any(n in blob for n in soft_needles):
                    continue
            result = score_property_for_case(prop, case, proj, exclude_codes=set())
            if not result:
                continue
            score, reasons = result
            slim["score"] = score
            slim["reasons"] = reasons
            scored.append((score, reasons, slim))
        scored.sort(key=lambda x: (-x[0], x[2].get("code") or ""))
        return _finish([s[2] for s in scored[:lim]])

    raw = recommend_for_case(case, limit=max(80, lim * 3), exclude_offered=False)
    by_code = {str(p.get("code") or "").upper(): p for p in load_properties()}

    out: list[dict] = []
    for hit in raw.get("items") or []:
        code = str(hit.get("code") or "").upper()
        prop = by_code.get(code)
        if not prop:
            continue
        slim = slim_property(
            prop,
            projects.get(prop.get("project_id")) or {},
            require_page=False,
            include_archived=False,
        )
        if not slim:
            continue
        if not _passes_size(slim, size_min, size_max):
            continue
        slim["score"] = hit.get("score")
        slim["reasons"] = hit.get("reasons") or []
        out.append(slim)
        if len(out) >= lim:
            break

    return _finish(out)
