# Lease Record Contract v0.1

## Fields

`lease_record_id`, `property_id`, `listing_cycle_id`, `deal_id`, `contract_start`, `contract_end`, `lease_term_months`, `lease_status`, `source_type`, `evidence_level`, `renewed_from_lease_id`

## Statuses

PENDING_START, ACTIVE, RENEWED, ENDED_CONFIRMED, TERMINATED, STATUS_CONFIRMATION_DUE, UNKNOWN, DATA_COMPLETION_REQUIRED

## Rules

- `contract_end` passing → STATUS_CONFIRMATION_DUE, **not** AVAILABLE or ENDED_CONFIRMED automatically
- Renewal → old record RENEWED + new lease_record (history preserved)
- Capture at customer workflow **CONTRACT_STARTED** / เริ่มสัญญา

## Storage

`.local/lease_record_phase_z6/` — TEST_ONLY
