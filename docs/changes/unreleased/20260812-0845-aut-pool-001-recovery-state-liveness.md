---
change_id: 20260812-0845-aut-pool-001-recovery-state-liveness
features: ["AUT-POOL-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Make recovery state terminal and isolate product target failures

## Before and after

A completed runtime-recovery revision could be overwritten to `running` by the daily rebuild
heartbeat. If that rebuild then failed, the exception path left recovery running forever. A single
MT5 product whose margin calculation was unavailable could also fail the entire target refresh.

Completed recovery states are now terminal. A rebuild failure closes an active recovery with a
bounded failure code, and a stopped recovery heartbeat is projected as failed and retryable after
fifteen seconds. Failed/rebuilding phases are always displayed as stale. Product target calculation
failures now disable only the affected product while the remaining products continue.

## Impact

The existing recovery API contract is unchanged and gains the bounded error codes
`recovery_heartbeat_stale` and `synchronization_failed`. No database, MT Manager, account, order or
server-side state is modified by this change.

## Documentation updated

Updated AUT-POOL-001 recovery liveness, stale-state projection and per-product target isolation.

## Verification

Producer tests cover terminal recovery revisions and per-product target failure isolation. Snapshot
repository tests cover failed rebuild phases and expired recovery heartbeats. Fast and Full governed
verification run before deployment.

## Deployment and rollback

Deploy by restarting the single main-branch Producer and the single 8777 account service after Full
verification. Verify that recovery reaches `synchronized`, phase reaches `live`, data becomes fresh
and only one Producer exists. Roll back to the preceding main commit and restart the same two single
instances; persisted cursors and Ticket ownership are retained.
