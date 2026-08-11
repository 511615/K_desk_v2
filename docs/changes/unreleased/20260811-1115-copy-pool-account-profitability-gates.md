---
change_id: 20260811-1115-copy-pool-account-profitability-gates
features: ["AUT-POOL-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# AUT-POOL-001 account profitability hard gates

## Before and after

Previously, a positive same-product 30-day result could admit an account whose lifetime trading
result was deeply negative or whose recent sample was only one trade. The complete pool build now
rejects an account before product and factor logic unless both lifetime
and rolling-30-day comprehensive trading profit are strictly positive. Both measures include current
all-product floating P/L and exclude Balance funding/rebate movements, Credit, Charge, Correction
and Bonus. The recent window must also contain at least five complete closed Positions/Tickets
across at least three trading days.

Hourly ranking re-evaluates the same non-compensable account gate and cannot revive a failing account.
The Producer/cache contract advances to v11/v5; an older same-day cache without account evidence is
invalid and forces a complete read-only rebuild.
To keep that rebuild operationally bounded, lifetime ledger evidence is stored in a private
per-source v1 cache with Deal/Ticket highwaters. Missing candidates receive a historical backfill;
known accounts read only later ledger rows. Rolling sample evidence reuses the existing 30-day trade
shards. The cache changes query cost only and cannot turn absent evidence into a passing value.

## Impact

No public endpoint is removed. New public pool columns are additive. Rollback restores the prior
v10/v4 selection model. Remote AC/DBG and MT data access remains read-only.

## Documentation updated

Updated AUT-POOL-001, business rules, data/routing and test strategy for the account-first hard-gate
ordering, sample boundary, ledger exclusions, cache invalidation and hourly non-revival behavior.

## Verification

Producer tests cover strict zero boundaries, all-product aggregation, cashflow exclusion, complete
sample counts, hourly non-revival, cache backfill/delta behavior and cache-version behavior. Fast and Full K_desk verification plus
a read-only all-source preflight are required before merge or deployment.

## Deployment and rollback

Deploy only after Full verification by merging the tested development commit into main, stopping the
single Producer, forcing one complete pool rebuild, and starting one main-branch Producer. Rollback
to the preceding commit and perform another fresh pool build; do not reinterpret a v11 universe as
v10 evidence. Persisted source/Demo Ticket ownership remains subject to normal restart reconciliation.
