"""Cross-source coordinate agreement resolver — Phase Z2."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from src.hub.coordinate_sources.base import CoordinateCandidate

STRONG_AGREEMENT_M = 75.0
WEAK_AGREEMENT_MAX_M = 250.0
CONFLICT_M = 250.0


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def classify_pairwise_distance(meters: float) -> str:
    if meters <= STRONG_AGREEMENT_M:
        return "STRONG_AGREEMENT"
    if meters <= WEAK_AGREEMENT_MAX_M:
        return "WEAK_AGREEMENT"
    return "CONFLICT"


@dataclass
class AgreementResult:
    agreement_class: str
    independent_lineage_count: int
    lineage_ids: list[str]
    pairwise: list[dict[str, Any]]
    promoted_tier: str | None
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agreement_class": self.agreement_class,
            "independent_lineage_count": self.independent_lineage_count,
            "lineage_ids": self.lineage_ids,
            "pairwise": self.pairwise,
            "promoted_tier": self.promoted_tier,
            "notes": self.notes,
            "thresholds": {
                "strong_m": STRONG_AGREEMENT_M,
                "weak_max_m": WEAK_AGREEMENT_MAX_M,
                "conflict_m": CONFLICT_M,
            },
        }


def resolve_agreement(candidates: list[CoordinateCandidate]) -> AgreementResult:
    if not candidates:
        return AgreementResult("NO_CANDIDATES", 0, [], [], None, [])

    independent = [c for c in candidates if c.independence == "INDEPENDENT"]
    unknown = [c for c in candidates if c.independence == "INDEPENDENCE_UNKNOWN"]
    lineage_ids = sorted({c.evidence_lineage_id for c in candidates})
    indep_lineages = sorted({c.evidence_lineage_id for c in independent})

    pairwise: list[dict[str, Any]] = []
    worst = "STRONG_AGREEMENT"
    order = {"STRONG_AGREEMENT": 0, "WEAK_AGREEMENT": 1, "CONFLICT": 2}
    for i, a in enumerate(candidates):
        for b in candidates[i + 1 :]:
            m = haversine_meters(a.latitude, a.longitude, b.latitude, b.longitude)
            cls = classify_pairwise_distance(m)
            pairwise.append(
                {
                    "from_lineage": a.evidence_lineage_id,
                    "to_lineage": b.evidence_lineage_id,
                    "distance_m": round(m, 1),
                    "classification": cls,
                    "same_lineage": a.evidence_lineage_id == b.evidence_lineage_id,
                }
            )
            if order[cls] > order[worst]:
                worst = cls

    notes: list[str] = []
    promoted: str | None = None

    if len(indep_lineages) < 2:
        if unknown and len(lineage_ids) >= 2:
            notes.append("INDEPENDENCE_UNKNOWN — cannot promote to T3 automatically")
        return AgreementResult(
            "SINGLE_SOURCE" if len(candidates) == 1 else "SAME_LINEAGE_FAMILY",
            len(indep_lineages),
            lineage_ids,
            pairwise,
            None,
            notes,
        )

    if worst == "CONFLICT":
        notes.append("Coordinate sources conflict beyond tolerance")
        return AgreementResult("CONFLICT", len(indep_lineages), lineage_ids, pairwise, None, notes)

    if worst == "WEAK_AGREEMENT":
        notes.append("Sources agree weakly — remain candidate")
        return AgreementResult("WEAK_AGREEMENT", len(indep_lineages), lineage_ids, pairwise, "T4_COORD", notes)

    promoted = "T3_COORD"
    notes.append("Two or more independent lineages strongly agree")
    return AgreementResult("STRONG_AGREEMENT", len(indep_lineages), lineage_ids, pairwise, promoted, notes)
