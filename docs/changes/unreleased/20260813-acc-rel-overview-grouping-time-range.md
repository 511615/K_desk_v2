---
change_id: 20260813-acc-rel-003-overview-grouping-time-range
features: ["ACC-REL-003"]
change_type: modification
status: unreleased
compatibility: compatible
---

# ACC-REL-003 — Relationship overview grouping and time range

## Change

- Group identical relationship branches into one representative overview edge; member evidence remains available in the detail panel.
- Keep a complete ancestry path from every rendered node to the investigation subject.
- Place ring captions on their actual ring and hide empty-ring captions.
- Add optional start/end datetime controls before the scan. Blank values mean full history.
- Highlight both endpoints and the selected edge when a copy relation line is clicked.

## Before and after

Before, each discovered member in a same-name or copy branch could draw a separate overview
line and empty ring captions could make the layer appear shifted. After, one representative line
is drawn per relationship group, all nodes retain the subject path, and captions are aligned.

## Impact

The change is limited to the read-only Kuzu risk page. It reduces canvas edge count without
removing evidence from the detail panel and adds two optional query filters.

## Documentation updated

Updated `docs/features/account/score-propagated-kuzu-investigation.md`.

## Verification

`tests/test_api.py` focused test and the complete pytest suite pass.

## Compatibility and verification

The change is read-only and keeps the existing relationship-network contract. It forwards `start`
and `end` through the existing filter boundary and does not change database schema or MT4/MT5 state.

## Deployment and rollback

Deploy the account-only service after normal governance verification. Roll back by restoring the
previous page module; no database or external state migration is required.
