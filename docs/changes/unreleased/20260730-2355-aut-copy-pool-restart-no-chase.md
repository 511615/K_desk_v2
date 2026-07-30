---
change_id: 20260730-2355-aut-copy-pool-restart-no-chase
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Prevent restart from chasing an orphan source position

## Before and after

A persisted source Position could retain `copy_eligible=true` even when its Demo child Ticket no
longer existed. Exact Ticket validation saw no mismatch because neither side owned a Ticket, so a
later live reconciliation could open a replacement order for that old source Position.

Startup now performs exact actual-Ticket recovery first. Every restored open source Position still
without a child Ticket is then persisted as `restart_without_demo_ticket`, remains monitor-only in
all later reconciliation, and is deleted after its source closes. A uniquely recovered or already
mapped Ticket remains owned and can still be reduced or closed.

## Impact

Restart cannot create a new Demo order from an old persisted source Position merely because its
previous copy-eligible flag survived. The change does not weaken unknown/missing Ticket hard stops,
does not change new live signal handling and does not touch remote database or MT Manager state.

## Verification

Focused regressions cover no replacement open in live reconciliation, persistent monitor reason,
unique real-Ticket recovery and close management, and source-close cleanup with no Demo action.
Fast and Full verification cover the remaining application, Producer and frontend contracts.

## Documentation updated

Updated AUT-POOL-001 current state, data/routing authority, business rules, operations and test
strategy.

## Deployment and rollback

Deploy only after Full verification on both `develop` and `main`. Keep the Producer stopped during
promotion, confirm the Demo account is flat, restart the 8777 account service from clean `main`, then
start the Producer without `-ForceRebuild`. Rollback stops the Producer and returns to the previous
commit; do not run the earlier version with live Demo authorization because it can chase orphaned
persisted source Positions.
