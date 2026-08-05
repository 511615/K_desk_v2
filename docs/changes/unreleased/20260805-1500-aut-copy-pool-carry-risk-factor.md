---
change_id: 20260805-1500-aut-copy-pool-carry-risk-factor
features: ["AUT-POOL-001"]
change_type: enhancement
status: unreleased
compatibility: additive
---

# Add bounded carry-risk filtering and ranking

## Before and after

Pool selection included current floating P/L, equity drawdown and holding quality, but did not expose
one auditable measure combining adverse depth, underwater time and simultaneous losing positions.
High after-cost profit could therefore rank well without an explicit composite carry-risk hard gate.

The complete build now calculates carry risk only after cheap profitability and risk filters. The
0-100 score combines depth, duration and losing-position count, applies non-compensable hard limits,
and contributes a 15% carry-quality percentile to the primary score. Carry risk does not change
intraday activity eligibility or copied Positions after selection; existing client and portfolio
loss limits remain responsible for trading-time intervention.

## Impact

The implementation reuses bounded 30-day equity/path evidence and the existing grouped current-
position read, extended with a conditional losing-position count. It performs no Tick replay and no
query before the established 61-day factor window. Historical maximum floating loss is therefore a
conservative low-cost proxy rather than exact Tick-level MAE.

The change affects pool eligibility, relative factor scores, cache compatibility and additive 8777
fields. It does not place orders, restart services or mutate remote MT/CRM state.

## Documentation updated

Updated AUT-POOL-001, business rules, data/routing authority and operations runbook with the formula,
thresholds, low-cost evidence limitations, v9/v3 cache contract and hourly behavior.

## Deployment and rollback

The dashboard contract is additive. Producer/schema identifiers advance to v9/v3 so a cache without
carry evidence cannot be restored as a current-model pool. Rollback restores the prior producer and
three-factor model; it requires rebuilding or restoring a matching prior-version cache.

## Verification

Unit and integration tests cover formula boundaries, hard-gate non-compensation, four-factor ranks,
current losing-position aggregation, absence of carry-driven intraday activity gates, cache
versioning and 8777 projection.
