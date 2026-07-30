---
change_id: 20260730-1420-aut-copy-pool-hourly-column-collision
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Separate hourly current-position columns from build-time evidence

## Before and after

The hourly refresh merged current product floating P/L and hedge ratio into an accepted universe
that already contained the same build-time column names. Pandas suffixed both copies, and the next
read raised `KeyError: product_floating_pnl` once per discovery retry.

Current product values now use explicit collision-free names. Build-time evidence remains intact,
and an empty current-position frame produces zero current floating P/L without changing historical
columns.

## Impact

Hourly dynamic ranking can complete during Shadow instead of retrying every minute. No threshold,
database, MT account, order or Manager state changes.

## Verification

Producer tests cover a factor-ready sleeve with existing build columns and no current product
position. Full verification and a fresh 30-minute Shadow remain required.

## Documentation updated

Updated the AUT-POOL-001 lifecycle description for collision-free hourly evidence.

## Deployment and rollback

Rollback restores the merge collision and is not suitable for Shadow. No migration exists; Demo
Live remains disabled.
