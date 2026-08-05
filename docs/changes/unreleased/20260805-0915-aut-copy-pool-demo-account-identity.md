---
change_id: 20260805-0915-aut-copy-pool-demo-account-identity
features: ["AUT-POOL-001"]
change_type: bug-fix
status: unreleased
compatibility: compatible
---

# Pin Demo account identity for equity and execution

## Before and after

The Producer previously verified `ACCMGlobal-Demo` only during startup. Concurrent MT5 Python IPC
activity could later return samples from another terminal account while the process remained live.
Those samples produced impossible equity values such as `0.00` and `499.61` between valid
`9818.24` observations and could temporarily alter sizing and cycle-P/L output.

The MT5 adapter now pins the positive Demo Login observed at initialization. Every subsequent
account read must match that Login, Demo server and Demo trade mode. A mismatch raises before risk,
sizing, status publication or broker execution, leaving the last valid snapshot to age stale rather
than publishing crossed-account values.

Status and timeline contracts add the pinned Demo Login. The timeline schema change archives the
legacy current CSV and starts a clean identity-bearing curve after deployment.

## Impact

This is an additive dashboard contract and a Producer execution-safety correction. Remote MySQL
remains read-only and no MT4/MT5 Manager operation is introduced.

## Verification

Producer tests reject a changed runtime Login and require the timeline identity column. Snapshot
repository tests pin `accountLogin` on both current status and timeline rows. Existing CSV schema
rotation coverage verifies byte-preserved archival of the prior timeline.

## Documentation updated

Updated AUT-POOL-001, Ports and APIs, and Operations with runtime Login pinning, stale-snapshot
behavior and timeline rotation.

## Deployment and rollback

Promote through `develop`, cherry-pick to `main`, then restart only the Producer. Rollback restores
the prior adapter and snapshot shape; the archived legacy timeline remains recoverable.
