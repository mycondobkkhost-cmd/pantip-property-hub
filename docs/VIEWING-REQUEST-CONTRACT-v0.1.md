# Viewing Request Contract v0.1

## Flow

CUSTOMER selects listing → submits viewing request with consented profile snapshot → owner/agent notification → response → customer notification → viewing status updated.

## Response types

ACCEPT, DECLINE, PROPOSE_ALTERNATIVE_TIME, PROPERTY_NOT_AVAILABLE, NEED_MORE_INFORMATION

## Scheduling

Supports `requested_slots[]`, `accepted_slot`, `proposed_alternative_slots[]`, `timezone`, `response_deadline`.

## Recipient resolution

Listing may be managed by OWNER, AGENT, or authorized representative — separate from Project Master.
