---
change_id: 20260807-1800-kln-timeline-clickable-liquidation
features: ["KLN-TIMELINE-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Make K-line liquidation evidence actionable

## Before and after

The standalone K-line funds panel drew red liquidation dots but did not bind a hit target, so users
could not navigate from the dot to its factual time. Red dots now focus the K-line viewport when
clicked. Liquidation rows in the funds/order event table also show an explicit `爆仓点位` action in
addition to the standard `定位` action.

## Impact

`KLN-TIMELINE-001` standalone generated HTML only. Existing routes, payloads, source reads and
business calculations are unchanged. The full replay still contains all returned account-history
order and funds events; a deliberately short `*_timeline_preview` artifact is only a fixture, not
an account-history result.

## Documentation updated

- `docs/features/kline/funds-and-position-replay.md`
- `docs/TEST_STRATEGY.md`

## Verification

- Timeline HTML regression verifies liquidation controls and JavaScript parsing.
- Governance Fast and Full checks are required before publication.

## Deployment and rollback

No production deployment is performed in this change. Rollback restores the prior HTML injection;
no source, database, cache or account state changes are involved.
