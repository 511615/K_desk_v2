---
change_id: 20260731-1810-aut-copy-pool-hard-deadline-current-copies
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Enforce every entry deadline and show current copies

## Before and after

The first retry-expiry repair covered a source Position without a Demo child. An existing child
could still make a delayed addition or reversal reach the shared open path without another deadline
check. The dashboard also separated source Positions and Demo Tickets without showing exact
Position-level source and Demo P/L in one operational row.

Every source Position now persists the latest opening, increase or reversal timestamp. All first
entries, additions and reversal open legs check that timestamp in the central risk-increase path and
again immediately before the broker request. Expired reversals may close the old side but cannot
open the opposite side. The dashboard additively exposes and renders one `currentCopies` row per
actual owned Demo Ticket with real Login, source/Demo order evidence, lots, delay, holding time,
source floating P/L and Demo comment-attributed P/L.

## Impact

The change removes every known delayed-open bypass while preserving risk reductions and closes.
Source current-position fields add no database round trip; they are selected by the existing bounded
position reconciliation query. Demo P/L reuses the existing ten-second comment attribution read.
Legacy snapshots remain readable and display unavailable per-position values instead of zero.

## Documentation updated

Updated AUT-POOL-001 current state plus API, data/routing, business-rule, operations and test
authorities. Generated registry and changelog artifacts are refreshed in the same change.

## Verification

Regressions cover a 40-second no-child retry, an expired addition with an existing Ticket, an
expired reversal, the final pre-broker deadline check, persisted risk-signal clocks, source money
normalization, exact/null current-copy P/L projection and the Chinese current-copy table.

## Deployment and rollback

Promote only after Full verification in both worktrees. Stop the old Producer only after the Demo is
flat with no pending order, keep 8777 available, deploy `main`, restart 8777 AccountOnly and then the
Producer. Rollback stops the Producer after another flat-account check, restores the prior main
commit and restarts the previous 8777/Producer versions; no database migration or remote MT/CRM
change is involved.
