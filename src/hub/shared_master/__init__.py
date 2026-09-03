"""Shared Canonical Master contract — Phase Z3.

Schema alignment between Pantip and RealXtate. READ-ONLY promotion design only.
"""

from src.hub.shared_master.area_contract import (
    AREA_SEMANTIC_KINDS,
    build_shared_area_master_draft,
)
from src.hub.shared_master.project_contract import (
    CANONICAL_EXCLUDED_FIELDS,
    PANTIP_ONLY_CLASSES,
    build_cross_product_contract,
    canonical_project_id_policy,
)
from src.hub.shared_master.readiness import (
    FieldReadiness,
    build_field_readiness_matrix,
    summarize_readiness,
)
from src.hub.shared_master.schema import (
    ENTITY_TYPES,
    FIELD_CLASSIFICATIONS,
    READINESS_STATUSES,
    SHARED_MASTER_VERSION,
)
from src.hub.shared_master.source_authority import (
    SOURCE_TIERS,
    coordinate_promotion_policy,
    reference_assignment_policy,
)

__all__ = [
    "AREA_SEMANTIC_KINDS",
    "CANONICAL_EXCLUDED_FIELDS",
    "ENTITY_TYPES",
    "FIELD_CLASSIFICATIONS",
    "FieldReadiness",
    "PANTIP_ONLY_CLASSES",
    "READINESS_STATUSES",
    "SHARED_MASTER_VERSION",
    "SOURCE_TIERS",
    "build_cross_product_contract",
    "build_field_readiness_matrix",
    "build_shared_area_master_draft",
    "canonical_project_id_policy",
    "coordinate_promotion_policy",
    "reference_assignment_policy",
    "summarize_readiness",
]
