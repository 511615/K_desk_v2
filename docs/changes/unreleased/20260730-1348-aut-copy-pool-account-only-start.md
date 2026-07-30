---
change_id: 20260730-1348-aut-copy-pool-account-only-start
features: ["AUT-POOL-001"]
change_type: operations
status: unreleased
compatibility: compatible
---

# AUT-POOL-001: Add an account-only production start mode

## Before and after

The governed production start script always launched both web services and production workers. It
now accepts `-AccountOnly`, which starts only the main account service on 8777 and skips 8766 and all
workers. Default behavior remains unchanged when the switch is absent.

## Impact

The copy-pool dashboard can be deployed on the requested single main service without opening an
unneeded web port or background worker. No API, database, MT account, order or Manager state changes.

## Verification

PowerShell parser validation, Full verification, listener ownership checks and 8777 readiness are
required. Acceptance also requires 8766 and 8891 to remain closed.

## Documentation updated

Updated the operations runbook with the account-only invocation and its skipped processes.

## Deployment and rollback

Run the script without `-AccountOnly` to restore the standard two-service plus worker topology.
