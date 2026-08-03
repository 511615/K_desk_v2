---
change_id: 20260803-1140-aut-copy-pool-cost-profit-factor
features: ["AUT-POOL-001"]
change_type: behavior
status: unreleased
compatibility: compatible
---

# Replace copy-pool ranking with the cost-profit primary model

## Before and after

The daily pool previously ranked hard-qualified sleeves with six normalized return, stress,
PF, drawdown and holding factors. It now ranks them with 50% cost-adjusted profit per copied trade,
30% recent five-day cost-adjusted profit per copied trade and 20% copy-cost coverage. Source P/L is
normalized to USD and scaled from average closed execution size to the selected Demo product's
actual minimum lot before deducting the product round-trip spread plus a 25% execution reserve.
MT5 close counts and lots both use exit/reversal Deals. Five-day and 20-day after-cost profit must
both be positive and coverage must be at least one; only rows passing every hard gate participate in
percentile ranking, and missing cost evidence fails closed. Existing drawdown, holding, negative-equity,
stop-out, margin and comprehensive-profit hard gates remain mandatory.

## Full-source cache upgrade

The v7 producer can re-rank a same-day v6 full universe without repeating the expensive 60-day
database history query. Upgrade is allowed only after exact eleven-route and nine-source coverage
validation; it preserves every prior hard rejection, rewrites the selected pool and stamps v7
metadata. It also restores persisted independent Ticket ownership instead of treating the migration
as a daily reset. The next 05:15 schedule still performs a complete database build.

## API and UI impact

The existing dashboard contract is additive. Pool rows now expose the factor model, the three
primary percentile scores, normalized copied P/L, estimated copy cost, after-cost P/L and cost
coverage. Existing fields and URLs remain compatible.

## Impact

This changes only the copy-pool producer's candidate ordering and hard eligibility. It keeps the
read-only database contract, Demo execution ownership, 8777 endpoints and deferred historical Tick
factor compatible. A same-day cache migration is additive and preserves persisted source-position
to Demo-Ticket ownership; it does not issue orders during preflight.

## Documentation updated

Updated AUT-POOL-001 business rules, data-routing, operations and current-state documentation to
record the cost model, product-specific minimum-lot scaling, hard-filter-first ranking, fail-closed
evidence behavior and same-day cache migration contract.

## Verification

Domain and factor-service tests cover the 50/30/20 formula, non-compensable hard gates and
source-average-lot normalization. Multi-source regression tests and an isolated full-cache
PreflightOnly upgrade cover the runtime contract. Fast and Full governance verification are
required before deployment.

## Deployment and rollback

Deploy from the verified development branch, stop only the existing copy-pool producer and restart
it from main with the existing Demo execution flags. Rollback restores the prior producer code
and the timestamped pre-deployment pool files; source and Demo Ticket ownership state remains
compatible and is never rebuilt from missed opens.
