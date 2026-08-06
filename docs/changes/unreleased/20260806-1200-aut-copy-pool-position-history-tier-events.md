---
change_id: 20260806-1200-aut-copy-pool-position-history-tier-events
features: ["AUT-POOL-001"]
change_type: enhancement
title: Present completed Positions once and align events with pool tiers
status: unreleased
compatibility: compatible
---

The Demo ledger now keeps open Positions exclusively in the current-position table and presents
each completed Position once in history. Closing Deals are grouped by Position, with final close
evidence and realized P/L summarized into one row.

The real-time event stream moves into the scheduling panel and uses the exact pool-tier projection
shown in the adjacent account table. The tier controls are synchronized in both directions.

## Before and after

Previously history repeated the opening and closing Deal legs, and the event stream was a separate
unsegmented panel. The page now shows one business transaction per completed Position and lets the
operator inspect events for the same activity, monitor, reserve and risk tiers used by the pool.

## Impact

This is a Vue presentation change only. Producer snapshots, execution behavior, remote data and API
contracts are unchanged.

## Documentation updated

- `docs/features/automation/dynamic-copy-pool-monitor.md`

## Deployment and rollback

Deploy by rebuilding the frontend in the verified main checkout. Rollback restores the prior Vue
bundle; runtime snapshots require no migration.

## Verification

- Component tests cover Position aggregation, open/incomplete exclusion and shared event-tier tabs.
- Frontend type checking and project Fast/Full verification are required before deployment.
