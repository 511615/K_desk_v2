---
change_id: 20260813-job-worker-heartbeat-readiness-marker
features: ["JOB-RECOVERY-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Make Worker readiness independent of Windows command-line inspection

## Before and after

Health checks identified Workers by querying every Windows process command line. On this host those
queries can be denied or return incomplete data, so running Workers were reported missing and the
startup sequence could leave durable jobs without a visible consumer.

## Current behavior

Each Worker writes a queue-specific runtime marker containing its PID, profile and queue while alive,
and removes it on exit. Production health checks validate live marker PIDs for the interactive and
discovery queues, while listener ownership checks remain strict.

## Impact and compatibility

Only local Worker readiness detection changes. Job APIs, SQLite schema, ports and all remote
read-only access remain compatible.

## Documentation updated

Updated `docs/features/jobs/job-progress-recovery.md`.

## Verification

The marker readiness regression is covered by the production-versioning tests; the Python worker and
PowerShell health script are parser/compile validated.

## Deployment and rollback

Deploy through the clean main checkout and `scripts/start_prod.ps1`. Rollback is the preceding
commit and controlled restart; no data migration is involved.
