"""Capacity-controlled recheck backlog vs active queue — Phase Z8 (TEST_ONLY)."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.hub.legacy_entry_date import (
    LEGACY_RECORD_ENTERED_AT_FIELD,
    RECHECK_THRESHOLD_CANDIDATES,
    parse_legacy_record_entered_at,
    record_age_days,
)
from src.hub.lease_record import list_lease_records
from src.hub.project_store import load_properties

BASE_DIR = Path(__file__).resolve().parent.parent.parent
LOCAL_DIR = BASE_DIR / ".local" / "recheck_capacity_phase_z8"
BACKLOG_PATH = LOCAL_DIR / "backlog.json"
QUEUE_PATH = LOCAL_DIR / "active_queue.json"
CONFIG_PATH = LOCAL_DIR / "capacity_config.json"
AUDIT_PATH = LOCAL_DIR / "override_audit.json"
DAILY_RELEASE_PATH = LOCAL_DIR / "daily_release.json"

# Backlog / queue lifecycle states
RECHECK_NOT_ELIGIBLE = "RECHECK_NOT_ELIGIBLE"
RECHECK_ELIGIBLE_BACKLOG = "RECHECK_ELIGIBLE_BACKLOG"
RECHECK_QUEUED = "RECHECK_QUEUED"
RECHECK_ASSIGNED = "RECHECK_ASSIGNED"
RECHECK_IN_PROGRESS = "RECHECK_IN_PROGRESS"
RECHECK_WAITING_OWNER = "RECHECK_WAITING_OWNER"
RECHECK_FOLLOWUP_SCHEDULED = "RECHECK_FOLLOWUP_SCHEDULED"
RECHECK_COMPLETED = "RECHECK_COMPLETED"
RECHECK_DEFERRED = "RECHECK_DEFERRED"

ACTIVE_QUEUE_STATES = frozenset(
    {
        RECHECK_QUEUED,
        RECHECK_ASSIGNED,
        RECHECK_IN_PROGRESS,
        RECHECK_WAITING_OWNER,
        RECHECK_FOLLOWUP_SCHEDULED,
    }
)

DEFAULT_CAPACITY = {
    "max_new_rechecks_per_day": 25,
    "max_active_rechecks_per_operator": 15,
    "max_total_active_rechecks": 50,
    "minimum_days_between_owner_contacts": 14,
    "overdue_followup_limit": 30,
    "rent_recheck_threshold_days": 180,
    "sale_recheck_threshold_days": 365,
    "policy_status": "POLICY_CANDIDATE",
    "test_only": True,
}

BATCH_STRATEGIES = ("oldest_first", "random_sample", "rent_first", "freshness_risk")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> date:
    return date.today()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _save_json(path: Path, data: Any) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_capacity_config() -> dict[str, Any]:
    cfg = _load_json(CONFIG_PATH, {})
    out = dict(DEFAULT_CAPACITY)
    out.update(cfg)
    out["test_only"] = True
    out["policy_status"] = "POLICY_CANDIDATE"
    return out


def save_capacity_config(**fields: Any) -> dict[str, Any]:
    cfg = load_capacity_config()
    cfg.update({k: v for k, v in fields.items() if v is not None})
    _save_json(CONFIG_PATH, cfg)
    return cfg


def _listing_kind(prop: dict[str, Any]) -> str:
    rent = bool((prop.get("rent_price") or "").strip())
    sale = bool((prop.get("sale_price") or "").strip())
    if rent and sale:
        return "both"
    if rent:
        return "rent"
    if sale:
        return "sale"
    return "unknown"


def _property_indexes() -> tuple[dict[str, dict], dict[str, list[dict]]]:
    by_id: dict[str, dict] = {}
    by_code: dict[str, list[dict]] = defaultdict(list)
    for p in load_properties():
        pid = str(p.get("id") or "")
        if pid:
            by_id[pid] = p
        code = str(p.get("code") or "").strip().upper()
        if code:
            by_code[code].append(p)
    return by_id, by_code


def _active_lease_property_ids() -> set[str]:
    active_statuses = {"ACTIVE", "PENDING_START", "STATUS_CONFIRMATION_DUE"}
    return {str(r.get("property_id") or "") for r in list_lease_records() if r.get("lease_status") in active_statuses}


def _last_contact_days_ago(item: dict[str, Any], *, today: date) -> int | None:
    raw = (item.get("last_contacted_at") or "")[:10]
    if not raw:
        return None
    try:
        d = date.fromisoformat(raw)
        return (today - d).days
    except ValueError:
        return None


def compute_priority_score(
    *,
    record_age_days: int,
    listing_kind: str,
    has_active_lease: bool,
    days_since_contact: int | None,
    waiting_owner: bool,
    has_followup_scheduled: bool,
) -> tuple[int, list[str]]:
    """Deterministic priority — higher score = higher priority. Legacy วันที่ว่าง excluded."""
    signals: list[str] = []
    if has_active_lease:
        return (-1, ["active_lease_excluded"])
    if waiting_owner or has_followup_scheduled:
        return (-2, ["waiting_or_followup_excluded"])
    score = record_age_days
    signals.append(f"age_{record_age_days}")
    if listing_kind == "rent":
        score += 50
        signals.append("rent_boost")
    elif listing_kind == "sale":
        score += 10
        signals.append("sale_boost")
    if days_since_contact is not None and days_since_contact < 30:
        score -= 1000
        signals.append("recent_contact_deprioritized")
    return score, signals


def build_eligible_backlog(*, threshold_days: int | None = None, today: date | None = None) -> list[dict[str, Any]]:
    """Compute ELIGIBLE_BACKLOG without materializing active queue."""
    today = today or _today()
    cfg = load_capacity_config()
    active_leases = _active_lease_property_ids()
    queue_items = {x.get("property_id"): x for x in _load_json(QUEUE_PATH, {"items": []}).get("items") or []}
    backlog_items = {x.get("property_id"): x for x in _load_json(BACKLOG_PATH, {"items": []}).get("items") or []}
    out: list[dict[str, Any]] = []

    for p in load_properties():
        pid = str(p.get("id") or "")
        kind = _listing_kind(p)
        th = threshold_days
        if th is None:
            th = cfg["rent_recheck_threshold_days"] if kind in {"rent", "both"} else cfg["sale_recheck_threshold_days"]
        entered = parse_legacy_record_entered_at(p.get(LEGACY_RECORD_ENTERED_AT_FIELD))
        age = record_age_days(entered, today=today)
        if age is None:
            state = RECHECK_NOT_ELIGIBLE
            reason = "missing_invalid_entry_date"
        elif age < th:
            state = RECHECK_NOT_ELIGIBLE
            reason = "under_threshold"
        elif pid in active_leases:
            state = RECHECK_NOT_ELIGIBLE
            reason = "active_lease"
        else:
            existing = queue_items.get(pid) or backlog_items.get(pid)
            if existing and existing.get("queue_state") in ACTIVE_QUEUE_STATES | {RECHECK_COMPLETED, RECHECK_DEFERRED}:
                state = existing.get("queue_state", RECHECK_ELIGIBLE_BACKLOG)
                reason = "already_tracked"
            elif existing and existing.get("queue_state") == RECHECK_WAITING_OWNER:
                state = RECHECK_WAITING_OWNER
                reason = "waiting_owner"
            elif existing and existing.get("next_followup_at"):
                state = RECHECK_FOLLOWUP_SCHEDULED
                reason = "followup_scheduled"
            else:
                state = RECHECK_ELIGIBLE_BACKLOG
                reason = "age_eligible"
        last_contact = _last_contact_days_ago(existing or {}, today=today) if existing else None
        score, signals = compute_priority_score(
            record_age_days=age or 0,
            listing_kind=kind,
            has_active_lease=pid in active_leases,
            days_since_contact=last_contact,
            waiting_owner=state == RECHECK_WAITING_OWNER,
            has_followup_scheduled=state == RECHECK_FOLLOWUP_SCHEDULED,
        )
        if state == RECHECK_ELIGIBLE_BACKLOG:
            out.append(
                {
                    "property_id": pid,
                    "property_code_display": p.get("code") or "",
                    "project_name_display": p.get("project_name") or "",
                    "listing_kind": kind,
                    "source_record_entered_at": entered.isoformat() if entered else "",
                    "record_age_days": age,
                    "queue_state": state,
                    "priority_score": score,
                    "priority_signals": signals,
                    "eligibility_reason": reason,
                }
            )
    out.sort(key=lambda x: (-int(x.get("priority_score") or 0), x.get("property_code_display") or ""))
    return out


def audit_backlog_by_listing_type(*, today: date | None = None) -> dict[str, Any]:
    today = today or _today()
    cfg = load_capacity_config()
    counts = {"rent": 0, "sale": 0, "both": 0, "unknown": 0}
    thresholds = {t: {"rent": 0, "sale": 0, "both": 0, "unknown": 0} for t in RECHECK_THRESHOLD_CANDIDATES}
    population = {"rent": 0, "sale": 0, "both": 0, "unknown": 0}
    age_by_kind: dict[str, dict[str, int]] = {k: defaultdict(int) for k in counts}

    for p in load_properties():
        kind = _listing_kind(p)
        population[kind] = population.get(kind, 0) + 1
        entered = parse_legacy_record_entered_at(p.get(LEGACY_RECORD_ENTERED_AT_FIELD))
        age = record_age_days(entered, today=today)
        if age is None:
            age_by_kind[kind]["missing_invalid"] += 1
            continue
        for t in RECHECK_THRESHOLD_CANDIDATES:
            if age >= t:
                thresholds[t][kind] += 1
        th = cfg["rent_recheck_threshold_days"] if kind in {"rent", "both"} else cfg["sale_recheck_threshold_days"]
        if age >= th:
            counts[kind] = counts.get(kind, 0) + 1

    return {
        "population": population,
        "eligible_backlog_by_kind": counts,
        "threshold_backlog_by_kind": thresholds,
        "age_bands_by_kind": {k: dict(v) for k, v in age_by_kind.items()},
        "test_only": True,
    }


def capacity_scenarios(*, backlog_sizes: dict[int, int] | None = None) -> dict[str, Any]:
    """Days to clear backlog at 10/25/50/100 new records per day."""
    if backlog_sizes is None:
        from src.hub.legacy_entry_date import audit_age_distribution

        audit = audit_age_distribution()
        workloads = audit["recheck_workload_by_threshold"]
        backlog_sizes = {90: workloads[90], 180: workloads[180], 270: workloads[270], 365: workloads[365]}
    daily_rates = [10, 25, 50, 100]
    operator_counts = [1, 2, 3, 5]
    scenarios: list[dict[str, Any]] = []
    for threshold, backlog in backlog_sizes.items():
        for rate in daily_rates:
            days = (backlog + rate - 1) // rate if rate else None
            for ops in operator_counts:
                effective_rate = rate * ops
                days_ops = (backlog + effective_rate - 1) // effective_rate if effective_rate else None
                scenarios.append(
                    {
                        "threshold_days": threshold,
                        "backlog_size": backlog,
                        "new_records_per_day": rate,
                        "operators": ops,
                        "effective_new_records_per_day": effective_rate,
                        "days_to_clear_backlog": days_ops,
                        "note": "new records/day != total touches/day",
                    }
                )
    return {"scenarios": scenarios, "hypothetical": True, "test_only": True}


def contact_workload_scenarios(
    *,
    new_per_day: int = 25,
    success_rates: list[float] | None = None,
    followup_attempts: list[int] | None = None,
) -> dict[str, Any]:
    """Planning-only touch workload estimates — NOT measured conversion."""
    success_rates = success_rates or [0.3, 0.5, 0.7]
    followup_attempts = followup_attempts or [0, 1, 2]
    rows: list[dict[str, Any]] = []
    for sr in success_rates:
        for fa in followup_attempts:
            first_contacts = new_per_day
            failed = int(new_per_day * (1 - sr))
            followup_touches = failed * fa
            total_touches = first_contacts + followup_touches
            rows.append(
                {
                    "new_records_per_day": new_per_day,
                    "first_contact_success_rate_hypothetical": sr,
                    "followup_attempts_per_failed_hypothetical": fa,
                    "estimated_first_contacts": first_contacts,
                    "estimated_followup_touches": followup_touches,
                    "estimated_total_touches_per_day": total_touches,
                    "disclaimer": "HYPOTHETICAL_PLANNING_ONLY",
                }
            )
    return {"rows": rows, "hypothetical": True, "test_only": True}


def _daily_release_count(today: date) -> int:
    key = today.isoformat()
    data = _load_json(DAILY_RELEASE_PATH, {})
    return int(data.get(key, 0))


def _increment_daily_release(today: date, count: int) -> None:
    data = _load_json(DAILY_RELEASE_PATH, {})
    key = today.isoformat()
    data[key] = int(data.get(key, 0)) + count
    _save_json(DAILY_RELEASE_PATH, data)


def _active_queue_items() -> list[dict[str, Any]]:
    return list(_load_json(QUEUE_PATH, {"items": []}).get("items") or [])


def _save_queue(items: list[dict[str, Any]]) -> None:
    _save_json(QUEUE_PATH, {"items": items, "updated_at": _now(), "test_only": True})


def active_capacity_summary(*, operator_id: str = "") -> dict[str, Any]:
    cfg = load_capacity_config()
    items = _active_queue_items()
    active = [x for x in items if x.get("queue_state") in ACTIVE_QUEUE_STATES]
    assigned = [x for x in active if x.get("assigned_operator_id")]
    if operator_id:
        assigned = [x for x in assigned if x.get("assigned_operator_id") == operator_id]
    today = _today()
    released_today = _daily_release_count(today)
    return {
        "active_count": len(active),
        "max_total_active_rechecks": cfg["max_total_active_rechecks"],
        "assigned_count": len(assigned),
        "max_active_rechecks_per_operator": cfg["max_active_rechecks_per_operator"],
        "released_today": released_today,
        "max_new_rechecks_per_day": cfg["max_new_rechecks_per_day"],
        "remaining_today": max(0, cfg["max_new_rechecks_per_day"] - released_today),
        "test_only": True,
    }


def release_batch_to_queue(
    *,
    operator_id: str,
    strategy: str = "oldest_first",
    limit: int | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """TEST_ONLY: pull up to daily capacity from backlog into active queue."""
    if strategy not in BATCH_STRATEGIES:
        raise ValueError(f"invalid strategy: {strategy}")
    cfg = load_capacity_config()
    today = _today()
    cap = active_capacity_summary(operator_id=operator_id)
    remaining_daily = cap["remaining_today"]
    if remaining_daily <= 0:
        return {"released": 0, "reason": "daily_capacity_exhausted", "test_only": True}
    active = _active_queue_items()
    active_ids = {x.get("property_id") for x in active if x.get("queue_state") in ACTIVE_QUEUE_STATES}
    if len(active) >= cfg["max_total_active_rechecks"]:
        return {"released": 0, "reason": "total_active_capacity_full", "test_only": True}

    backlog = [x for x in build_eligible_backlog(today=today) if x["property_id"] not in active_ids]
    if strategy == "oldest_first":
        backlog.sort(key=lambda x: (-int(x.get("record_age_days") or 0), x.get("property_code_display") or ""))
    elif strategy == "rent_first":
        backlog.sort(
            key=lambda x: (
                0 if x.get("listing_kind") == "rent" else 1,
                -int(x.get("record_age_days") or 0),
                x.get("property_code_display") or "",
            )
        )
    elif strategy == "random_sample":
        import random

        rng = random.Random(seed)
        rng.shuffle(backlog)
        backlog.sort(key=lambda x: -int(x.get("record_age_days") or 0))
    elif strategy == "freshness_risk":
        backlog.sort(key=lambda x: (-int(x.get("priority_score") or 0), x.get("property_code_display") or ""))

    max_release = min(
        remaining_daily,
        cfg["max_total_active_rechecks"] - len(active),
        limit or remaining_daily,
    )
    if operator_id:
        assigned = sum(1 for x in active if x.get("assigned_operator_id") == operator_id)
        max_release = min(max_release, cfg["max_active_rechecks_per_operator"] - assigned)

    released: list[dict[str, Any]] = []
    now = _now()
    for item in backlog[:max_release]:
        rec = {
            **item,
            "queue_state": RECHECK_ASSIGNED if operator_id else RECHECK_QUEUED,
            "assigned_operator_id": operator_id or "",
            "released_at": now,
            "batch_strategy": strategy,
            "test_only": True,
        }
        active.append(rec)
        released.append(rec)

    _save_queue(active)
    _increment_daily_release(today, len(released))
    return {
        "released": len(released),
        "strategy": strategy,
        "items": released,
        "capacity_after": active_capacity_summary(operator_id=operator_id),
        "test_only": True,
    }


def assign_operator(property_id: str, operator_id: str) -> dict[str, Any]:
    items = _active_queue_items()
    pid = (property_id or "").strip()
    for i, it in enumerate(items):
        if it.get("property_id") == pid:
            items[i] = {**it, "assigned_operator_id": operator_id, "queue_state": RECHECK_ASSIGNED, "updated_at": _now()}
            _save_queue(items)
            return items[i]
    raise ValueError("property not in active queue")


def unassign_operator(property_id: str) -> dict[str, Any]:
    items = _active_queue_items()
    pid = (property_id or "").strip()
    for i, it in enumerate(items):
        if it.get("property_id") == pid:
            items[i] = {**it, "assigned_operator_id": "", "queue_state": RECHECK_QUEUED, "updated_at": _now()}
            _save_queue(items)
            return items[i]
    raise ValueError("property not in active queue")


def defer_recheck(property_id: str, *, until: str = "", reason: str = "") -> dict[str, Any]:
    items = _active_queue_items()
    pid = (property_id or "").strip()
    for i, it in enumerate(items):
        if it.get("property_id") == pid:
            items[i] = {
                **it,
                "queue_state": RECHECK_DEFERRED,
                "deferred_until": until,
                "defer_reason": reason,
                "updated_at": _now(),
            }
            _save_queue(items)
            return items[i]
    raise ValueError("property not in active queue")


def check_contact_cooldown(*, property_id: str, last_contacted_at: str = "") -> dict[str, Any]:
    cfg = load_capacity_config()
    min_days = int(cfg["minimum_days_between_owner_contacts"])
    raw = (last_contacted_at or "")[:10]
    if not raw:
        return {"allowed": True, "days_since_contact": None, "minimum_days": min_days}
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        return {"allowed": True, "days_since_contact": None, "minimum_days": min_days}
    days = (_today() - d).days
    return {"allowed": days >= min_days, "days_since_contact": days, "minimum_days": min_days}


def privileged_contact_override(
    *,
    property_id: str,
    operator_id: str,
    reason: str,
    privileged: bool = False,
) -> dict[str, Any]:
    if not privileged:
        raise PermissionError("privileged override required")
    if not (reason or "").strip():
        raise ValueError("override reason required")
    evt = {
        "audit_id": f"oa_{uuid.uuid4().hex[:12]}",
        "property_id": property_id,
        "operator_id": operator_id,
        "reason": reason,
        "created_at": _now(),
        "test_only": True,
    }
    audits = list(_load_json(AUDIT_PATH, {"items": []}).get("items") or [])
    audits.append(evt)
    _save_json(AUDIT_PATH, {"items": audits, "updated_at": _now()})
    return {"ok": True, "audit": evt, "cooldown_bypassed": True}


def recommend_first_batch_strategy() -> dict[str, Any]:
    audit = audit_backlog_by_listing_type()
    pop = audit["population"]
    rent_ratio = pop.get("rent", 0) / max(1, sum(pop.values()))
    return {
        "recommended": "rent_first" if rent_ratio > 0.7 else "oldest_first",
        "rationale_th": (
            "คิวเช่ามีสัดส่วนสูง — เริ่มจาก rent-first ชุดเล็ก 25 รายการ/วัน"
            if rent_ratio > 0.7
            else "เริ่มจาก oldest-first ชุดเล็ก 25 รายการ/วัน เพื่อลดความเสี่ยงข้อมูลเก่า"
        ),
        "alternatives_compared": list(BATCH_STRATEGIES),
        "recommendation_only": True,
        "test_only": True,
    }


def build_capacity_api_payload() -> dict[str, Any]:
    backlog = build_eligible_backlog()
    return {
        "ok": True,
        "test_only": True,
        "policy_status": "POLICY_CANDIDATE",
        "config": load_capacity_config(),
        "eligible_backlog_count": len(backlog),
        "active_queue": _active_queue_items(),
        "capacity": active_capacity_summary(),
        "backlog_sample": backlog[:20],
        "listing_type_audit": audit_backlog_by_listing_type(),
        "capacity_scenarios": capacity_scenarios(),
        "contact_workload": contact_workload_scenarios(),
        "first_batch_recommendation": recommend_first_batch_strategy(),
        "legacy_wang_excluded": True,
    }
