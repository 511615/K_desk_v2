---
change_id: 20260807-1530-kln-timeline-white-kline-theme
features: ["KLN-TIMELINE-001"]
change_type: ui_detail
status: unreleased
compatibility: compatible
---

# Keep the historical-funds K-line replay in the chart's white theme

## Before and after

The new historical-funds layout copied the legacy dialog's dark palette. The layout now remains,
but the standalone chart uses the existing white K-line visual system: white background, dark text,
soft gray table headers and borders. Color is reserved for Balance, Credit, positive/negative money
and liquidation evidence.

## Impact

`KLN-TIMELINE-001` standalone HTML styling only. Event data, Position folding, APIs, cache, source
reads, calculation rules and liquidation behavior are unchanged.

## Documentation updated

- `docs/features/kline/funds-and-position-replay.md`

## Verification

- K-line HTML regression asserts the white high-contrast container and rejects the former dark panel.
- Existing timeline, Position folding and JavaScript parsing regressions remain required.

## Deployment and rollback

The normal release rebuilds new artifacts with the white theme. Rollback restores only the former
artifact styling; no database, account, trade or MT state changes.
