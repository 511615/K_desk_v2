---
change_id: 20260804-1050-aut-copy-pool-bounded-history-concurrency
features: ["AUT-POOL-001"]
change_type: performance
status: unreleased
compatibility: compatible
---

# Bound copy-pool history and parallelize physical sources

## Before and after

Factor-history equity loading previously searched 7, 14, 28 and progressively larger pre-window
ranges for unresolved accounts, up to 2,048 days. Nine physical-source history bundles then loaded
serially. A complete all-source rebuild consequently spent most wall time waiting for remote reads.

History is now restricted to the existing 61-day daily range, which supplies at most one extra day
for the 60-day baseline. Missing older evidence does not trigger another query and remains
fail-closed under the existing equity-coverage gates. Physical-source risk, holding and factor-history
bundles load with at most four workers per stage, one task per source, and merge in stable source
order. Any source exception fails the whole build. Coverage additively records bounded stage timings.

## Impact

Remote MT4/MT5 and CRM access remains SELECT-only. Hard risk, drawdown, after-cost profitability,
holding and source-coverage gates are unchanged. The running producer, 8777 routes, dashboard JSON
contracts and Demo Ticket ownership are not modified by development testing.

## Documentation updated

Updated AUT-POOL-001 plus Data and Routing, Business Rules, Operations and Test Strategy to define
the bounded history window, source concurrency and failure behavior.

## Verification

Repository tests prohibit MT4 and MT5 pre-window history SQL and assert the exact 61-day lower
bound. Factor-service tests cover bounded concurrent loads, one call per source, stage timings and
whole-evaluation failure. Multi-source tests cover the shared risk/holding physical-source scheduler,
stable result order and contextual whole-stage failure. The complete versioned Producer regression
suite must pass before Full project verification and any isolated all-source performance preflight.

## Deployment and rollback

No deployment occurs from the development worktree. Promotion requires Full verification and a
separate producer restart from main. Rollback restores the prior repository/factor-service files;
existing cache, snapshots and Ticket ownership remain readable because no persisted schema changed.
