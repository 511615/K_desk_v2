---
change_id: 20260804-1430-aut-copy-pool-hourly-discovery-retention
features: ["AUT-POOL-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Retain the accepted pool on an undersized hourly refresh

## Before and after

The hourly discovery path raised an exception whenever its current hard-qualified result contained
fewer than ten unique accounts. The exception escaped the producer's dynamic-refresh step, so the
same main-loop iteration skipped risk checks and could hold a completed recovery shadow below the
live transition.

Any non-empty hourly result now publishes normally, including one to nine qualified accounts. Only
an empty result records `insufficient_qualified_accounts`, retains the last accepted pool and leaves
the successful hourly cursor unchanged. The existing one-minute retry floor applies, while the main
risk, reconciliation and recovery state machine continues normally.

## Impact

No daily hard gate is weakened and no new account is promoted from an empty result. Existing
source-to-Demo ownership, current pool rows and execution limits remain unchanged until a later
successful hourly rotation. The source-coverage JSON gains diagnostic fields for the rejected empty
hourly attempt only; the 8777 dashboard contract remains additive and compatible.

Remote database access remains read-only. This change neither restarts the producer nor performs
any MT4/MT5 Manager operation.

## Documentation updated

Updated the AUT-POOL-001 current-state document to define the empty-hourly-result retention,
diagnostic status and retry behavior. No API or generated contract changed.

## Verification

A Producer regression verifies that a three-account hourly result publishes normally. A separate
empty-result regression verifies retained-pool diagnostics and leaves the successful hourly schedule
cursor unset for retry.

## Deployment and rollback

Development verification does not change the running service. Promotion requires the normal
main-branch deployment and controlled producer restart. Rollback restores the prior exception
behavior without any state migration; existing snapshots and ticket mappings remain readable.
