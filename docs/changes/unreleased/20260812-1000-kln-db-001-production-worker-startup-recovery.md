---
change_id: 20260812-1000-kln-db-001-production-worker-startup-recovery
features: ["KLN-DB-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Prevent a dev listener from masquerading as production K-line service

## Before and after

`start_prod.ps1` accepted an existing listener when its command line contained the expected FastAPI
module. A manually started dev-profile account service could therefore occupy port 8777 while the
production K-line service and interactive Worker were absent. Database K-line requests were saved
to the dev SQLite queue and remained `queued` with no consumer.

## Current behavior

Before accepting an existing 8777 or 8766 listener, the production launcher reads local
`/health/ready`. It accepts only `profile=prod`; otherwise it stops the matching Uvicorn supervisor,
waits for the port to clear, and starts the complete production service set. The standard health
check still verifies both web services plus interactive and discovery Workers.

## Impact and compatibility

No request path, payload, account data or remote source access changes. The change affects only
local startup recovery. It stops only a process already proven to be a K_desk FastAPI listener for
the requested service module; an unrelated port owner remains a startup error.

## Documentation updated

Updated `docs/features/kline/database-generation.md` and `docs/OPERATIONS.md`.
Added a production-launcher regression test and recorded the new production listener acceptance
rule.

## Verification

Ran the focused production-launcher regression suite and parsed the PowerShell launcher. Fast and
Full governed verification are required before deployment.

## Deployment and rollback

Deploy by restarting through `scripts/start_prod.ps1`. Rollback is the prior launcher commit; no
SQLite migration or source-data change is involved.
