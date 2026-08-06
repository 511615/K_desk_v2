---
change_id: 20260805-1700-aut-copy-pool-7d-30d-rebuild
features: ["AUT-POOL-001"]
change_type: business-rule
title: Seven-day activity and thirty-day core profitability rebuild
status: unreleased
compatibility: compatible
---

The copy-pool rebuild starts with all routed sources and keeps only account-product sleeves with a
close in the rolling seven-day window. Account equity minimums and the retired 60-day history
dependency are removed. Rolling 30-day normalized comprehensive profit, stress profit,
copy-cost-adjusted profit and non-compensable account risk remain core admission evidence.

Factor quality, drawdown, holding, carry and recent performance are exposed for ranking and weight
allocation only. They may produce warnings and a lower weight, but cannot turn a core-qualified
sleeve into `factor_ready=false`. The producer/cache schema is bumped to force a complete rebuild
before restoring an accepted snapshot.

## Before and after

Before this change, the builder discovered a 60-day universe and then applied factor-like cost,
drawdown and carry rejection gates. After this change, recent activity is the rolling seven-day
candidate boundary, core evidence is rolling 30 days, and quality factors only rank core-qualified
sleeves.

## Impact

The pool snapshot and factor schema are incompatible with the previous same-day cache and force a
read-only full rebuild. Demo order ownership and the existing no-chase execution contract remain
unchanged.

## Documentation updated

- `docs/features/automation/dynamic-copy-pool-monitor.md`
- `docs/BUSINESS_RULES.md`
- `docs/DATA_AND_ROUTING.md`

## Deployment and rollback

The Producer will be restarted only after verification, using one `-ForceRebuild` instance. Rollback
is stopping that Producer and restoring the prior source revision and snapshots.

## Verification

- `services/copy_pool_runtime/tests`: all tests passing.
- Fast and Full governance verification required before live restart.
