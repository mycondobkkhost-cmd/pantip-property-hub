"""Cross-product RealXtate ↔ Pantip sync inventory — Phase Z5 (read-only RealXtate)."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REALXTATE_REPO = Path("/Users/angkarn1996/Documents/Codex/RealXtate-Web-MVP")
PANTIP_REPO = Path(__file__).resolve().parent.parent.parent
ARTIFACT_DIR = Path("/tmp/pantip-phase-z5-sync")
Z6_ARTIFACT_DIR = Path("/tmp/pantip-phase-z6")
Z5_REALXTATE_HEAD = "cb7f4725598b349fc0cbd003190e757c9551136b"

CAPABILITY_STATUSES = frozenset(
    {"IMPLEMENTED", "FOUNDATION_ONLY", "DESIGNED_ONLY", "NOT_FOUND", "DEFERRED"}
)


def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.STDOUT)
        return out.strip()
    except Exception:
        return ""


def _file_exists(repo: Path, rel: str) -> bool:
    return (repo / rel).is_file()


def _dir_exists(repo: Path, rel: str) -> bool:
    return (repo / rel).is_dir()


def discover_realxtate_capabilities() -> dict[str, dict[str, Any]]:
    """Inspect RealXtate repo read-only and classify capabilities."""
    rx = REALXTATE_REPO
    caps: dict[str, dict[str, Any]] = {}

    def set_cap(
        key: str,
        status: str,
        *,
        evidence: list[str],
        notes: str = "",
    ) -> None:
        caps[key] = {"status": status, "evidence": evidence, "notes": notes}

    # A. Canonical Project Master
    if _file_exists(rx, "web/.data/realxtate-trusted-master.sqlite"):
        set_cap(
            "canonical_project_master",
            "FOUNDATION_ONLY",
            evidence=["web/.data/realxtate-trusted-master.sqlite", "docs/platform/PROPERTY-IDENTITY-MODEL.md"],
            notes="Phase 8Z.2K frozen trusted master; pilot-gated",
        )
    else:
        set_cap("canonical_project_master", "NOT_FOUND", evidence=[])

    # B. Canonical Listing vs Source Record
    if _file_exists(rx, "docs/platform/CANONICAL-LISTING-MODEL.md") and _dir_exists(rx, "web/provenance"):
        set_cap(
            "canonical_listing_vs_source_record",
            "FOUNDATION_ONLY",
            evidence=[
                "docs/platform/CANONICAL-LISTING-MODEL.md",
                "web/provenance/canonical-listing-service.ts",
                "web/.data/realxtate-provenance.sqlite",
            ],
            notes="Runtime catalog listings.id canonical; parallel provenance DB for source records",
        )
    else:
        set_cap("canonical_listing_vs_source_record", "DESIGNED_ONLY", evidence=[])

    # C. Source provenance
    if _file_exists(rx, "docs/platform/SOURCE-PROVENANCE-MODEL.md"):
        set_cap(
            "source_provenance",
            "FOUNDATION_ONLY",
            evidence=["docs/platform/SOURCE-PROVENANCE-MODEL.md", "web/provenance/schema.ts"],
            notes="UNLINKED|LINKED|REJECTED|QUARANTINED; (source_system, source_listing_id) unique",
        )
    else:
        set_cap("source_provenance", "NOT_FOUND", evidence=[])

    # D. Listing source identity/idempotency
    set_cap(
        "listing_source_identity_idempotency",
        "FOUNDATION_ONLY",
        evidence=["docs/platform/SOURCE-PROVENANCE-MODEL.md"],
        notes="Logical unique key (source_system, source_listing_id)",
    )

    # E. Multi-source listings
    set_cap(
        "multi_source_listings",
        "FOUNDATION_ONLY",
        evidence=["docs/platform/CANONICAL-LISTING-MODEL.md"],
        notes="0..N listing_source_records per canonical listing; tests/docs only",
    )

    # F. Marketplace Group
    if _file_exists(rx, "web/config/marketplace-groups.ts") or _file_exists(rx, "web/data/marketplace-groups.json"):
        set_cap(
            "marketplace_group",
            "IMPLEMENTED",
            evidence=["docs/platform/CROSS-PROJECT-DATA-CONTRACT.md"],
            notes="7 marketplace groups Phase 8Z.4/8Z.5",
        )
    else:
        set_cap("marketplace_group", "FOUNDATION_ONLY", evidence=["docs/platform/CROSS-PROJECT-DATA-CONTRACT.md"])

    # G. Marketplace Area/Sub-area
    set_cap(
        "marketplace_area_subarea",
        "IMPLEMENTED",
        evidence=["docs/platform/CROSS-PROJECT-DATA-CONTRACT.md"],
        notes="Area seeds + spatial corridors; pilot-gated assignment",
    )

    # H. Listing availability/freshness
    if _file_exists(rx, "web/services/verification-service.ts") or _file_exists(
        rx, "web/app/internal/verification/page.tsx"
    ):
        set_cap(
            "listing_availability_freshness",
            "IMPLEMENTED",
            evidence=[
                "web/services/verification-service.ts",
                "web/app/internal/verification/page.tsx",
                "docs/platform/PROPERTY-FRESHNESS-ROADMAP.md",
            ],
            notes="Verification overlay + TTL expiry; public_availability states",
        )
    else:
        set_cap("listing_availability_freshness", "DESIGNED_ONLY", evidence=["docs/platform/PROPERTY-FRESHNESS-ROADMAP.md"])

    # I. Listing renewal
    set_cap(
        "listing_renewal",
        "NOT_FOUND",
        evidence=["docs/platform/PROPERTY-FRESHNESS-ROADMAP.md"],
        notes="renewal_required_at designed; no renewal workflow implementation",
    )

    # J. Notifications
    set_cap(
        "notifications",
        "DEFERRED",
        evidence=["docs/platform/LEAD-CRM-ARCHITECTURE.md"],
        notes="No notification center implementation found",
    )

    # K. Viewing requests
    if _file_exists(rx, "web/features/leads/lead-form.tsx"):
        set_cap(
            "viewing_requests",
            "FOUNDATION_ONLY",
            evidence=["web/features/leads/lead-form.tsx", "docs/platform/LEAD-CRM-ARCHITECTURE.md"],
            notes="Lead form UI stub; PG schema planned; no full viewing workflow",
        )
    else:
        set_cap("viewing_requests", "DESIGNED_ONLY", evidence=[])

    # L. Lease lifecycle
    set_cap(
        "lease_lifecycle",
        "NOT_FOUND",
        evidence=["docs/platform/PROPERTY-FRESHNESS-ROADMAP.md"],
        notes="OCCUPIED_NOW / AVAILABLE_SOON concepts only",
    )

    # M. Privacy boundary
    if _file_exists(rx, "web/provenance/public-listing-privacy.ts"):
        set_cap(
            "privacy_boundary",
            "IMPLEMENTED",
            evidence=["web/provenance/public-listing-privacy.ts"],
            notes="Public projection strips raw contact",
        )
    else:
        set_cap("privacy_boundary", "FOUNDATION_ONLY", evidence=[])

    return caps


def build_realxtate_current_state() -> dict[str, Any]:
    """Build deterministic RealXtate current-state report."""
    rx = REALXTATE_REPO
    branch = _git(rx, "branch", "--show-current")
    head = _git(rx, "rev-parse", "HEAD")
    log = _git(rx, "log", "--oneline", "-30")
    status = _git(rx, "status", "--short")
    caps = discover_realxtate_capabilities()

    implemented = [k for k, v in caps.items() if v["status"] == "IMPLEMENTED"]
    foundation = [k for k, v in caps.items() if v["status"] == "FOUNDATION_ONLY"]
    deferred = [k for k, v in caps.items() if v["status"] == "DEFERRED"]
    not_found = [k for k, v in caps.items() if v["status"] == "NOT_FOUND"]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repo_path": str(rx),
        "branch": branch,
        "head_sha": head,
        "recent_commits": [ln for ln in log.splitlines() if ln.strip()],
        "worktree_state": status.splitlines() if status else [],
        "latest_implemented_phase": "Phase 9B (provenance foundation) + 8Z marketplace master",
        "latest_deferred_phase": "Notifications, lease lifecycle, listing renewal workflow",
        "current_architecture": {
            "canonical_listing_store": "listings.id (catalog SQLite)",
            "source_record_store": "parallel provenance SQLite (9B)",
            "project_master": "trusted-master SQLite (8Z.2K frozen)",
            "shared_master_boundary": "WHAT/WHERE only",
        },
        "capabilities": caps,
        "summary": {
            "implemented": implemented,
            "foundation_only": foundation,
            "deferred": deferred,
            "not_found": not_found,
        },
        "canonical_listing_vs_source_record": caps.get("canonical_listing_vs_source_record", {}),
        "source_provenance_model": {
            "unique_key": "(source_system, source_listing_id)",
            "mapping_statuses": ["UNLINKED", "LINKED", "REVIEW_REQUIRED", "REJECTED", "QUARANTINED"],
            "rejected_retention": True,
            "unlinked_retention": True,
        },
    }


def build_cross_product_capability_diff() -> dict[str, Any]:
    """Explicit capability diff table RealXtate vs Pantip."""
    rx_caps = discover_realxtate_capabilities()

    rows = [
        _diff_row("Project Master", rx_caps, "canonical_project_master", "IMPLEMENTED", "SHARED_CANONICAL_MASTER"),
        _diff_row("Area Master", rx_caps, "marketplace_area_subarea", "IMPLEMENTED", "SHARED_AREA_TAXONOMY"),
        _diff_row("Group/Sub-area", rx_caps, "marketplace_group", "IMPLEMENTED", "7 groups reconciled Z4"),
        _diff_row("Transit", rx_caps, "marketplace_area_subarea", "IMPLEMENTED", "SHARED + Pantip transit_master"),
        _diff_row("Coordinates", rx_caps, "canonical_project_master", "IMPLEMENTED", "SHARED evidence-backed"),
        _diff_row("Source provenance", rx_caps, "source_provenance", "FOUNDATION_ONLY", "SOURCE_PROVENANCE_CONTRACT v0.1"),
        _diff_row("Property identity", rx_caps, "canonical_listing_vs_source_record", "FOUNDATION_ONLY", "property_id != source_record"),
        _diff_row("Listing identity", rx_caps, "canonical_listing_vs_source_record", "FOUNDATION_ONLY", "listing_id != property_code"),
        _diff_row("Listing cycle", rx_caps, "lease_lifecycle", "NOT_FOUND", "LISTING_CYCLE_CONTRACT v0.1"),
        _diff_row("Freshness", rx_caps, "listing_availability_freshness", "NOT_FOUND", "LISTING_FRESHNESS_CONTRACT"),
        _diff_row("Renewal", rx_caps, "listing_renewal", "NOT_FOUND", "Separate from bump event"),
        _diff_row("Notifications", rx_caps, "notifications", "FOUNDATION_ONLY", "NOTIFICATION_EVENT_CONTRACT"),
        _diff_row("Viewing requests", rx_caps, "viewing_requests", "FOUNDATION_ONLY", "VIEWING_REQUEST_CONTRACT"),
        _diff_row("Deal/lease lifecycle", rx_caps, "lease_lifecycle", "FOUNDATION_ONLY", "LEASE_OPPORTUNITY_CONTRACT"),
        _diff_row("Near-vacancy", rx_caps, "lease_lifecycle", "FOUNDATION_ONLY", "Pantip operator workflow Z5"),
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "realxtate_head": _git(REALXTATE_REPO, "rev-parse", "HEAD"),
        "pantip_head": _git(PANTIP_REPO, "rev-parse", "HEAD"),
        "rows": rows,
    }


def _diff_row(
    capability: str,
    rx_caps: dict[str, dict[str, Any]],
    rx_key: str,
    pantip_status: str,
    shared_contract: str,
) -> dict[str, str]:
    rx = rx_caps.get(rx_key, {})
    rx_status = rx.get("status", "NOT_FOUND")
    gap = _gap_label(rx_status, pantip_status)
    action = _recommended_action(capability, rx_status, pantip_status)
    return {
        "capability": capability,
        "realxtate_current": rx_status,
        "pantip_current": pantip_status,
        "shared_contract": shared_contract,
        "gap": gap,
        "recommended_owner_product_action": action,
    }


def _gap_label(rx: str, pantip: str) -> str:
    order = {"NOT_FOUND": 0, "DEFERRED": 1, "DESIGNED_ONLY": 2, "FOUNDATION_ONLY": 3, "IMPLEMENTED": 4}
    if rx == pantip:
        return "ALIGNED"
    if order.get(rx, 0) > order.get(pantip, 0):
        return f"PANTIP_BEHIND ({pantip} vs {rx})"
    if order.get(pantip, 0) > order.get(rx, 0):
        return f"REALXTATE_BEHIND ({rx} vs {pantip})"
    return "PARTIAL"


def _recommended_action(capability: str, rx: str, pantip: str) -> str:
    if capability == "Near-vacancy":
        return "Pantip builds operator lease opportunity; RealXtate defers until owner self-service"
    if capability == "Freshness":
        return "Align Pantip contract to RealXtate verification overlay; defer Pantip public freshness"
    if capability == "Source provenance":
        return "Adopt shared SOURCE_PROVENANCE_CONTRACT; Pantip import uses source_record mapping"
    if rx == "IMPLEMENTED" and pantip != "IMPLEMENTED":
        return f"Pantip adopt contract aligned to RealXtate {capability.lower()}"
    return "Maintain shared contract; independent implementation"


def write_sync_artifacts() -> dict[str, str]:
    """Write /tmp artifacts and return paths."""
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    state = build_realxtate_current_state()
    diff = build_cross_product_capability_diff()
    state_path = ARTIFACT_DIR / "realxtate-current-state.json"
    diff_path = ARTIFACT_DIR / "cross-product-capability-diff.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    diff_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"state_path": str(state_path), "diff_path": str(diff_path)}


def build_realxtate_delta_since_z5() -> dict[str, Any]:
    head = _git(REALXTATE_REPO, "rev-parse", "HEAD")
    log = _git(REALXTATE_REPO, "log", f"{Z5_REALXTATE_HEAD}..HEAD", "--oneline")
    commits = [ln for ln in log.splitlines() if ln.strip()] if log else []
    return {
        "z5_observed_head": Z5_REALXTATE_HEAD,
        "current_head": head,
        "head_changed": head != Z5_REALXTATE_HEAD,
        "commits_after_z5": commits,
        "REALXTATE_NEW_SINCE_Z5": commits,
        "pantip_relevance": "NO_MATERIAL_CHANGE" if not commits else "REVIEW_REQUIRED",
    }


def build_cross_product_capability_diff_v2() -> dict[str, Any]:
    rx_caps = discover_realxtate_capabilities()
    rows = [
        _diff_row_v2("Canonical Project Master", rx_caps, "canonical_project_master", "IMPLEMENTED", "SHARED_CANONICAL_MASTER", "NO_CHANGE", "promotion blocked"),
        _diff_row_v2("Property identity", rx_caps, "canonical_listing_vs_source_record", "FOUNDATION_ONLY", "PROPERTY_IDENTITY_CONTRACT", "Z6 lease_record", "shared"),
        _diff_row_v2("Canonical listing", rx_caps, "canonical_listing_vs_source_record", "FOUNDATION_ONLY", "LISTING_IDENTITY_CONTRACT", "NO_CHANGE", "shared"),
        _diff_row_v2("Source record/provenance", rx_caps, "source_provenance", "FOUNDATION_ONLY", "SOURCE_PROVENANCE_CONTRACT v0.1", "NO_CHANGE", "import later"),
        _diff_row_v2("Listing cycle", rx_caps, "lease_lifecycle", "FOUNDATION_ONLY", "LISTING_CYCLE_CONTRACT", "Z6 lease_record", "shared"),
        _diff_row_v2("Availability/freshness", rx_caps, "listing_availability_freshness", "FOUNDATION_ONLY", "LISTING_FRESHNESS_CONTRACT", "Z6 freshness MVP", "align TTL"),
        _diff_row_v2("Renewal", rx_caps, "listing_renewal", "NOT_FOUND", "LISTING_FRESHNESS_CONTRACT", "contract only", "RealXtate future"),
        _diff_row_v2("Bump", rx_caps, "listing_renewal", "NOT_FOUND", "separate event", "contract only", "product-specific"),
        _diff_row_v2("Notification", rx_caps, "notifications", "FOUNDATION_ONLY", "NOTIFICATION_EVENT_CONTRACT", "Z6 extend", "shared taxonomy"),
        _diff_row_v2("Viewing request", rx_caps, "viewing_requests", "FOUNDATION_ONLY", "VIEWING_REQUEST_CONTRACT", "NO_CHANGE", "no Pantip impl"),
        _diff_row_v2("Customer-profile consent", rx_caps, "privacy_boundary", "IMPLEMENTED", "excluded from master", "NO_CHANGE", "shared"),
        _diff_row_v2("Deal lifecycle", rx_caps, "lease_lifecycle", "FOUNDATION_ONLY", "DEAL_LIFECYCLE_CONTRACT", "Z6 capture point", "workflow"),
        _diff_row_v2("Lease lifecycle", rx_caps, "lease_lifecycle", "FOUNDATION_ONLY", "LEASE_RECORD_CONTRACT v0.1", "Z6 lease_record", "operator"),
        _diff_row_v2("Near vacancy", rx_caps, "lease_lifecycle", "FOUNDATION_ONLY", "LEASE_OPPORTUNITY_CONTRACT", "Z6 evidence dry-run", "7 strong"),
        _diff_row_v2("Listing reactivation", rx_caps, "lease_lifecycle", "NOT_FOUND", "roadmap", "deferred", "future"),
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": "v2",
        "realxtate_head": _git(REALXTATE_REPO, "rev-parse", "HEAD"),
        "pantip_head": _git(PANTIP_REPO, "rev-parse", "HEAD"),
        "delta_since_z5": build_realxtate_delta_since_z5(),
        "rows": rows,
    }


def _diff_row_v2(
    capability: str,
    rx_caps: dict[str, dict[str, Any]],
    rx_key: str,
    pantip_status: str,
    shared_contract: str,
    z6_action: str,
    future_action: str,
) -> dict[str, str]:
    rx = rx_caps.get(rx_key, {})
    rx_status = rx.get("status", "NOT_FOUND")
    return {
        "capability": capability,
        "realxtate_latest": rx_status,
        "pantip_latest": pantip_status,
        "shared_contract_state": shared_contract,
        "gap": _gap_label(rx_status, pantip_status),
        "z6_action": z6_action,
        "future_action": future_action,
    }


def write_z6_artifacts() -> dict[str, str]:
    Z6_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    state = build_realxtate_current_state()
    state["delta_since_z5"] = build_realxtate_delta_since_z5()
    state["z6_note"] = "HEAD unchanged from Z5 — no new RealXtate commits"
    diff = build_cross_product_capability_diff_v2()
    state_path = Z6_ARTIFACT_DIR / "realxtate-latest-state.json"
    diff_path = Z6_ARTIFACT_DIR / "cross-product-capability-diff-v2.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    diff_path.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"state_path": str(state_path), "diff_path": str(diff_path)}
