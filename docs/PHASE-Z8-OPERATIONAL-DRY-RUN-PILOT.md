# Phase Z8 — Operational Dry-Run Pilot

Capacity-controlled recheck backlog vs active operator queue. TEST_ONLY local storage.

## Key concepts

- **ELIGIBLE_BACKLOG** — properties meeting age threshold
- **ACTIVE_OPERATOR_QUEUE** — capacity-limited actionable batch
- Default policy candidates: 25 new/day, 50 total active, 14-day contact cooldown

## Local QA

```bash
bash scripts/start_z8_operational_pilot.sh
python3 scripts/phase_z8_authenticated_qa.py
```
