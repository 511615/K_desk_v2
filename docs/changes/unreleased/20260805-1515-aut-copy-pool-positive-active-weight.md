---
change_id: 20260805-1515-aut-copy-pool-positive-active-weight
features: ["AUT-POOL-001"]
title: Enforce positive effective weight for active product sleeves
change_type: bugfix
status: unreleased
compatibility: compatible
---

## Before and after

Before this fix, a stale daily pool row or a client risk-ledger weight could make an account look
active while its dynamic account-product sleeve had a final effective weight of zero.

After this fix, the dynamic account-product sleeve is the single execution-state authority. A sleeve
with a final `effective_weight` of zero cannot remain in the `active` tier: the domain state falls
back to monitoring and the dashboard projects it as execution-suspended. The dashboard also derives
`activityEligible` from the positive final dynamic weight.

## Impact

No running service or MT4/MT5 state was changed by this fix. Existing source positions remain
subject to the no-chase rule.

## Documentation updated

- `docs/features/automation/dynamic-copy-pool-monitor.md`

## Deployment and rollback

The main service was not restarted or deployed. The change is source-compatible and can be rolled
back by reverting this single Git change; existing runtime snapshots remain readable.

## Verification

- `services/copy_pool_runtime/tests/test_copy_dynamic_pool_domain.py`: zero target cannot promote to active.
- `tests/test_copy_pool_monitor.py`: zero-weight dynamic active sleeve is projected as execution-suspended.
- `frontend/src/copyPool.spec.ts`: zero-weight dynamic sleeve is not resolved as active.
