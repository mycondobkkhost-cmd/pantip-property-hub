"""Legacy location token classification and evidence lineage — Phase Z1."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Evidence lineages — same original source must share lineage id.
LINEAGE_LEGACY_SHEET = "lineage:legacy_employee_sheet"
LINEAGE_PANTIP_ZONE = "lineage:pantip_zone_field"
LINEAGE_CATALOG_BAG = "lineage:catalog_listing_bag"
LINEAGE_COORDINATE = "lineage:coordinate_pin"
LINEAGE_TRANSIT_FIELD = "lineage:transit_field"
LINEAGE_REALXTATE_RX = "lineage:realxtate_assignment"
LINEAGE_NAME_BRANDING = "lineage:project_name"

TOKEN_MARKETPLACE = "MARKETPLACE_AREA"
TOKEN_ADMIN_DISTRICT = "ADMIN_DISTRICT"
TOKEN_ADMIN_SUBDISTRICT = "ADMIN_SUBDISTRICT"
TOKEN_TRANSIT = "TRANSIT"
TOKEN_ROAD_CORRIDOR = "ROAD_CORRIDOR"
TOKEN_UNKNOWN = "UNKNOWN"
TOKEN_CONFLICTING = "CONFLICTING"

BANGKOK_DISTRICTS = frozenset(
    {
        "วัฒนา", "คลองเตย", "บางรัก", "สาทร", "ปทุมวัน", "ราชเทวี", "ดินแดง", "ห้วยขวาง",
        "พญาไท", "บางกะปิ", "ลาดพร้าว", "จตุจักร", "บางนา", "พระโขนง", "สวนหลวง",
        "ประเวศ", "บางขุนเทียน", "ทุ่งครุ", "ภาษีเจริญ", "ธนบุรี", "บางกอกใหญ่",
        "บางกอกน้อย", "บางพลัด", "ตลิ่งชัน", "ทวีวัฒนา", "หนองแขม", "บางแค",
        "บางซื่อ", "ดุสิต", "พระนคร", "สัมพันธวงศ์", "คลองสาน", "ยานนาวา",
    }
)

MARKETPLACE_TOKENS = {
    "อ่อนนุช": "onnut",
    "on nut": "onnut",
    "onnut": "onnut",
    "อโศก": "asoke",
    "asoke": "asoke",
    "พระราม 9": "rama9",
    "พระราม9": "rama9",
    "rama 9": "rama9",
    "ทองหล่อ": "thonglor",
    "thonglor": "thonglor",
    "เอกมัย": "ekkamai",
    "ekkamai": "ekkamai",
    "เจริญนคร": "charoen_nakhon",
    "charoen nakhon": "charoen_nakhon",
    "คลองเตย": "khlong_toei",
    "khlong toei": "khlong_toei",
    "บางนา": "bangna",
    "bangna": "bangna",
    "สุขุมวิท": "sukhumvit",
    "sukhumvit": "sukhumvit",
    "รัชดา": "ratchada",
    "ratchada": "ratchada",
    "ลาดพร้าว": "ladprao",
    "ladprao": "ladprao",
    "สาทร": "sathorn",
    "sathorn": "sathorn",
    "เพชรบุรี": "phetchaburi",
    "phetchaburi": "phetchaburi",
    "พัฒนาการ": "phatthanakan",
    "pattanakarn": "phatthanakan",
    "phatthanakan": "phatthanakan",
    "สวนหลวง": "suan_luang",
    "suan luang": "suan_luang",
}


@dataclass
class EvidenceRecord:
    evidence_type: str
    evidence_family: str
    evidence_lineage_id: str
    source: str
    source_record_id: str
    value: str
    confidence: str
    tier: str


@dataclass
class TokenClassification:
    token: str
    semantic_kind: str
    marketplace_identity_key: str | None = None
    notes: str = ""


def classify_location_token(token: str) -> TokenClassification:
    raw = (token or "").strip()
    low = raw.lower()
    if not raw:
        return TokenClassification(raw, TOKEN_UNKNOWN)

    if re.search(r"\b(bts|mrt|arl|srt|รถไฟฟ้า|สถานี)\b", low) or raw.startswith("BTS ") or raw.startswith("MRT "):
        return TokenClassification(raw, TOKEN_TRANSIT, notes="Transit label — not marketplace area")

    if raw.startswith("เขต") or low.startswith("district "):
        return TokenClassification(raw, TOKEN_ADMIN_DISTRICT, notes="Administrative district label")

    if raw.startswith("แขวง"):
        return TokenClassification(raw, TOKEN_ADMIN_SUBDISTRICT, notes="Administrative subdistrict label")

    if re.search(r"\b(ถนน|ซอย|soi)\b", low) or re.search(r"สุขุมวิท\s*\d+", raw):
        return TokenClassification(raw, TOKEN_ROAD_CORRIDOR)

    if raw in BANGKOK_DISTRICTS:
        return TokenClassification(raw, TOKEN_ADMIN_DISTRICT, notes="Bangkok khet token in legacy bag")

    for key, identity in MARKETPLACE_TOKENS.items():
        if key in low or low == key:
            return TokenClassification(
                raw,
                TOKEN_MARKETPLACE,
                marketplace_identity_key=identity,
                notes="Marketplace-style token",
            )

    # สวนหลวง as market label vs เขตสวนหลวง admin — disambiguate by prefix.
    if "สวนหลวง" in raw and raw.startswith("เขต"):
        return TokenClassification(raw, TOKEN_ADMIN_DISTRICT, notes="Khet Suan Luang admin")

    if "สวนหลวง" in raw:
        return TokenClassification(
            raw,
            TOKEN_MARKETPLACE,
            marketplace_identity_key="suan_luang",
            notes="Marketplace Suan Luang — distinct from khet unless prefixed",
        )

    return TokenClassification(raw, TOKEN_UNKNOWN)


def legacy_bag_lineage_shared(pantip_zones: list[str], catalog_locations: list[str]) -> bool:
    """Detect when Pantip zone and catalog bag are the same historical copy."""
    if not pantip_zones or not catalog_locations:
        return False
    a = {z.strip() for z in pantip_zones if z}
    b = {x.strip() for x in catalog_locations if x}
    if not a or not b:
        return False
    overlap = len(a & b) / max(len(a), len(b))
    return overlap >= 0.8


def build_legacy_evidence_records(
    *,
    project_id: str,
    pantip_zones: list[str],
    catalog_locations: list[str],
    listing_transit: list[str],
    project_name: str,
) -> list[EvidenceRecord]:
    records: list[EvidenceRecord] = []
    shared_lineage = legacy_bag_lineage_shared(pantip_zones, catalog_locations)
    bag_lineage = LINEAGE_LEGACY_SHEET if shared_lineage else LINEAGE_CATALOG_BAG
    zone_lineage = LINEAGE_LEGACY_SHEET if shared_lineage else LINEAGE_PANTIP_ZONE

    for zone in pantip_zones:
        cls = classify_location_token(zone)
        records.append(
            EvidenceRecord(
                evidence_type="legacy_zone_token",
                evidence_family="LEGACY_SHEET" if shared_lineage else "ADMIN_GEOGRAPHY",
                evidence_lineage_id=zone_lineage,
                source="pantip_zone_verified",
                source_record_id=project_id,
                value=zone,
                confidence="LOW",
                tier="T4",
            )
        )
    for loc in catalog_locations:
        cls = classify_location_token(loc)
        family = "LEGACY_SHEET" if shared_lineage else "MARKETPLACE_REFERENCE"
        records.append(
            EvidenceRecord(
                evidence_type="catalog_listing_token",
                evidence_family=family,
                evidence_lineage_id=bag_lineage,
                source="catalog_listing_bag",
                source_record_id=project_id,
                value=loc,
                confidence="LOW",
                tier="T4",
            )
        )
    for tr in listing_transit:
        records.append(
            EvidenceRecord(
                evidence_type="transit_label",
                evidence_family="TRANSIT",
                evidence_lineage_id=LINEAGE_TRANSIT_FIELD,
                source="catalog_transit_json",
                source_record_id=project_id,
                value=tr,
                confidence="MEDIUM",
                tier="T3",
            )
        )
    if project_name:
        records.append(
            EvidenceRecord(
                evidence_type="project_name",
                evidence_family="NAME_BRANDING",
                evidence_lineage_id=LINEAGE_NAME_BRANDING,
                source="catalog_name",
                source_record_id=project_id,
                value=project_name,
                confidence="MEDIUM",
                tier="T3",
            )
        )
    return records


def count_independent_lineages(records: list[EvidenceRecord]) -> int:
    return len({r.evidence_lineage_id for r in records})


def independent_family_lineages(records: list[EvidenceRecord]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in records:
        out.setdefault(r.evidence_family, set()).add(r.evidence_lineage_id)
    return out


def measure_duplicate_lineage_problem(
    contexts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate how often Pantip zone and catalog bag are same lineage."""
    total = 0
    shared = 0
    for ctx in contexts:
        zones = ctx.get("pantip_zones") or []
        locs = ctx.get("listing_locations") or []
        if zones and locs:
            total += 1
            if legacy_bag_lineage_shared(zones, locs):
                shared += 1
    return {
        "projects_with_both_bags": total,
        "same_lineage_count": shared,
        "same_lineage_pct": round(100 * shared / total, 1) if total else 0.0,
    }
