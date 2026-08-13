---
change_id: 20260813-job-process-guard-permission-tolerance
features: ["JOB-RECOVERY-001", "KLN-DB-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Tolerate protected Windows processes during K_desk recovery

## Before and after

The production stop script could abort while enumerating all Windows processes when an unrelated
protected process returned `Access denied`. This left the web ports stopped but prevented the normal
restart sequence from completing.

## Current behavior

Start, stop and health-check process enumeration skips uninspectable unrelated processes. Expected
K_desk listeners still require explicit process inspection; if the expected listener itself cannot
be inspected, startup fails safely instead of killing an unknown owner.

## Impact and compatibility

Only local process recovery behavior changes. Ports, job payloads, SQLite data and read-only remote
providers are unchanged.

## Documentation updated

Updated the JOB-RECOVERY-001 and KLN-DB-001 feature documents.

## Verification

PowerShell scripts were parser-validated and production ownership tests passed. Full governed
verification remains required before deployment.

## Deployment and rollback

Deploy with the clean main checkout through `scripts/start_prod.ps1`. Rollback is the preceding
launcher commit and controlled restart; no data migration is involved.
