---
change_id: 20260731-1340-aut-copy-pool-holding-timeout-split
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Subdivide holding-history reads after a timeout

## Before and after

The daily all-source pool build queried twenty days of holding history in Login batches. Unlike the
other high-volume build reads, this query had no adaptive fallback. On 2026-07-31 an MT5 batch
exceeded the read-only connection's 30-second timeout and stopped the Producer before MT5 startup.

Holding reads now recursively split a failed Login batch. If one Login still times out, the same
twenty-day range is read in five-day windows with recursive subdivision down to six hours. MT5 open
and close timestamps are merged by Position across windows before the exact holding duration is
calculated. Exhausting the minimum window still fails the build.

## Impact

The factor definition, twenty-day horizon, account population and hard gates are unchanged. The
change only makes the complete read resilient to slow physical sources. Remote MySQL remains
strictly read-only, MT Manager is not used, and no Demo order occurs during pool construction.

## Verification

A regression forces the original twenty-day MT5 aggregate to time out and places one Position's
opening and close in adjacent five-day windows. It requires one retained sample with the exact
7,200-second duration. Fast and Full verification cover governance, application, legacy, Producer,
frontend and production build contracts.

## Documentation updated

Updated AUT-POOL-001 current state, data/routing, operations and test strategy.

## Deployment and rollback

Keep the Producer stopped while promoting. After both branches pass Full verification, restart from
clean `main` without `-ForceRebuild`; the daily build must complete all eleven routes and nine
physical sources before MT5 initialization. Rollback restores fail-fast timeout behavior and cannot
be used to bypass the required complete holding evidence.
