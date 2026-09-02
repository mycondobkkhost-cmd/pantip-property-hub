"""Property identity resolution — property_id is canonical; property_code may duplicate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ResolveStatus = Literal["found", "not_found", "ambiguous", "id_required"]

STATUS_FOUND: ResolveStatus = "found"
STATUS_NOT_FOUND: ResolveStatus = "not_found"
STATUS_AMBIGUOUS: ResolveStatus = "ambiguous"
STATUS_ID_REQUIRED: ResolveStatus = "id_required"

ERROR_NOT_FOUND = "PROPERTY_NOT_FOUND"
ERROR_AMBIGUOUS = "PROPERTY_CODE_AMBIGUOUS"
ERROR_ID_REQUIRED = "PROPERTY_ID_REQUIRED"


def normalize_code(code: str | None) -> str:
    return str(code or "").strip().upper().replace(" ", "")


def normalize_id(property_id: str | None) -> str:
    return str(property_id or "").strip()


def find_all_by_code(properties: list[dict], code: str) -> list[dict]:
    want = normalize_code(code)
    if not want:
        return []
    return [
        p
        for p in properties
        if isinstance(p, dict) and normalize_code(p.get("code")) == want
    ]


def find_by_id(properties: list[dict], property_id: str) -> dict | None:
    want = normalize_id(property_id)
    if not want:
        return None
    for p in properties:
        if isinstance(p, dict) and normalize_id(p.get("id")) == want:
            return p
    return None


def candidate_summary(prop: dict) -> dict[str, Any]:
    """Minimal public-safe candidate row for ambiguity responses."""
    return {
        "property_id": normalize_id(prop.get("id")),
        "property_code": normalize_code(prop.get("code")),
        "project_id": str(prop.get("project_id") or ""),
        "project_name": str(prop.get("project_name") or ""),
        "rent_price": str(prop.get("rent_price") or ""),
        "sale_price": str(prop.get("sale_price") or ""),
        "import_status": str(prop.get("import_status") or ""),
    }


@dataclass
class PropertyResolveResult:
    status: ResolveStatus
    record: dict | None = None
    candidates: list[dict] | None = None
    match_count: int = 0
    error_code: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_FOUND and self.record is not None

    def to_api_dict(self, *, message: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "match_count": self.match_count,
        }
        if message:
            out["error"] = message
        elif self.error_code == ERROR_NOT_FOUND:
            out["error"] = "ไม่พบทรัพย์"
        elif self.error_code == ERROR_AMBIGUOUS:
            out["error"] = (
                f"รหัสทรัพย์ซ้ำ {self.match_count} รายการ — ต้องระบุ property_id"
            )
        elif self.error_code == ERROR_ID_REQUIRED:
            out["error"] = "ต้องระบุ property_id"
        if self.record is not None:
            out["property"] = self.record
        if self.candidates:
            out["candidates"] = self.candidates
        if self.error_code:
            out["error_code"] = self.error_code
        return out


def resolve_by_id(properties: list[dict], property_id: str) -> PropertyResolveResult:
    prop = find_by_id(properties, property_id)
    if not prop:
        return PropertyResolveResult(
            status=STATUS_NOT_FOUND,
            match_count=0,
            error_code=ERROR_NOT_FOUND,
        )
    return PropertyResolveResult(
        status=STATUS_FOUND,
        record=prop,
        match_count=1,
    )


def resolve_by_code(
    properties: list[dict],
    code: str,
    *,
    allow_ambiguous: bool = False,
) -> PropertyResolveResult:
    matches = find_all_by_code(properties, code)
    n = len(matches)
    if n == 0:
        return PropertyResolveResult(
            status=STATUS_NOT_FOUND,
            match_count=0,
            error_code=ERROR_NOT_FOUND,
        )
    if n == 1:
        return PropertyResolveResult(
            status=STATUS_FOUND,
            record=matches[0],
            match_count=1,
        )
    if allow_ambiguous:
        return PropertyResolveResult(
            status=STATUS_AMBIGUOUS,
            candidates=[candidate_summary(p) for p in matches],
            match_count=n,
            error_code=ERROR_AMBIGUOUS,
        )
    return PropertyResolveResult(
        status=STATUS_AMBIGUOUS,
        candidates=[candidate_summary(p) for p in matches],
        match_count=n,
        error_code=ERROR_AMBIGUOUS,
    )


def resolve_for_action(
    properties: list[dict],
    *,
    property_id: str | None = None,
    property_code: str | None = None,
) -> PropertyResolveResult:
    """Resolve for mutation / external side effects — never first-match on duplicate code."""
    pid = normalize_id(property_id)
    if pid:
        return resolve_by_id(properties, pid)
    code = normalize_code(property_code)
    if not code:
        return PropertyResolveResult(
            status=STATUS_ID_REQUIRED,
            match_count=0,
            error_code=ERROR_ID_REQUIRED,
        )
    return resolve_by_code(properties, code, allow_ambiguous=False)


def resolve_job_property(
    properties: list[dict],
    job: dict,
) -> PropertyResolveResult:
    """Resolve property attached to a queued job (prefer stored property_id)."""
    pid = normalize_id(job.get("property_id"))
    if pid:
        res = resolve_by_id(properties, pid)
        if res.ok:
            return res
    code = normalize_code(job.get("property_code") or job.get("code"))
    if not code:
        return PropertyResolveResult(
            status=STATUS_ID_REQUIRED,
            match_count=0,
            error_code=ERROR_ID_REQUIRED,
        )
    return resolve_by_code(properties, code, allow_ambiguous=False)


def find_property_by_code_unique(properties: list[dict], code: str) -> dict | None:
    """Legacy helper — returns a row only when code maps to exactly one property."""
    res = resolve_by_code(properties, code, allow_ambiguous=False)
    return res.record if res.ok else None


def find_property_by_code(properties: list[dict], code: str) -> dict | None:
    """Backward-compatible alias — never returns first of ambiguous matches."""
    return find_property_by_code_unique(properties, code)


def list_candidates_by_code(properties: list[dict], code: str) -> list[dict]:
    """Human search — may return multiple candidates."""
    return find_all_by_code(properties, code)


def overlay_blocked_codes(properties: list[dict]) -> set[str]:
    """Codes that must not use code-only overlay (ambiguous)."""
    from collections import Counter

    counts = Counter(
        normalize_code(p.get("code"))
        for p in properties
        if isinstance(p, dict) and normalize_code(p.get("code"))
    )
    return {code for code, n in counts.items() if n > 1}
