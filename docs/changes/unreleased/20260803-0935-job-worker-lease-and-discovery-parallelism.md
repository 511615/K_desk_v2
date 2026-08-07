---
change_id: 20260803-0935-job-worker-lease-and-discovery-parallelism
features: ["JOB-RECOVERY-001", "TOX-PUSH-001"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Restore platform task execution and prevent discovery queue starvation

## Before and after

Production had been started in account-only mode, leaving `8777` available while no Worker could
claim durable jobs. After the full topology was restored, one long position-risk scan could occupy
the only discovery Worker and leave push, rebate and bonus tasks queued indefinitely. Workers now
claim jobs with an atomic SQLite transition, refresh a five-second SQLite lease, stale running rows are recovered only after 180 seconds, and
the production launcher starts two discovery Workers. Production readiness reports missing Worker
queues instead of declaring the account page healthy by itself.

## Impact

Worker recovery, production process startup/readiness, and discovery queue scheduling. Existing job
IDs, payloads, statuses, polling endpoints and read-only remote data behavior are unchanged.

## Documentation updated

Updated the persistent-job, market-pushing and operations authorities plus the test strategy.

## Verification

Focused SQLite lease/recovery tests, Worker tests, Ruff, PowerShell parser checks and Fast/Full
governance verification. Production validation includes both Worker processes, the queued platform
job claim and representative health endpoints.

## Deployment and rollback

No schema migration is required; `heartbeat_at` already exists. Restart the production web and
Worker processes with `scripts/start_prod.ps1`. Roll back the Worker/startup files together; queued
jobs remain compatible and can be recovered by the prior Worker after restart.
