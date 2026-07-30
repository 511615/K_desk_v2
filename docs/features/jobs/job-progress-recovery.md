---
feature_id: JOB-RECOVERY-001
title: Persistent job progress and recovery
module: jobs
status: active
apis: ["GET /api/kline/jobs/{job_id}", "GET /api/toxic/jobs/{job_id}", "GET /api/push-discovery/jobs/{job_id}", "GET /api/push-discovery/active", "GET /api/rebate-churning/scans/{job_id}", "GET /api/bonus-arbitrage/scans/active", "GET /api/bonus-arbitrage/scans/{job_id}", "GET /api/position-risk/scans/active", "GET /api/position-risk/scans/{job_id}", "POST /api/jobs/{job_id}/cancel"]
code: ["src/kdesk/infrastructure/database.py", "src/kdesk/worker/runner.py", "src/kdesk/api/account_app.py", "frontend/src/pushDiscovery.ts", "frontend/src/frontendUpdate.ts", "frontend/src/components/BonusArbitrageDiscoveryPanel.vue", "frontend/src/components/PositionRiskDiscoveryPanel.vue", "scripts/start_dev.ps1", "scripts/start_prod.ps1", "scripts/stop_prod.ps1"]
tests: ["tests/test_api.py", "tests/test_ledger.py", "tests/test_worker.py", "frontend/src/pushDiscovery.spec.ts", "frontend/src/frontendUpdate.spec.ts", "frontend/src/bonusDiscovery.spec.ts", "frontend/src/positionRiskDiscovery.spec.ts", "legacy/apps/problem_account_registry/test_app.py"]
depends_on: []
last_verified_version: 2.1.0
last_verified_date: 2026-07-20
---

# Persistent job progress and recovery

## Purpose and user entry

Provide durable K-line, Toxic, push-discovery, rebate-discovery, bonus-discovery and position-risk jobs with progress, events,
retry/cancel and restart recovery.

## UI and behavior

Pages poll stable job IDs. Queued, running, done, failed and cancelled states have clear messages.
Completed discovery jobs retain and display non-fatal source/account failures alongside successes.
K-line jobs likewise retain per-symbol failures and mark the result partial when at least one other
symbol generated successfully.
Transient polling disconnects retain the last progress and job ID, then reconnect automatically.
The workbench restores the latest discovery job after navigation or reload.
After a task reaches a terminal state, the page advances to the next running or queued discovery job.
The Vue index is not cached; an open workbench detects a changed entry-asset hash and reloads while
durable job recovery preserves task state across the deployment.
Rebate discovery checks cancellation at environment and IB-batch boundaries and retains successful
rankings when another environment or IB fails.
Bonus discovery restores its own job after navigation, checks cancellation between source shards and
accounts and inside large related-account matching loops, and retains successful rankings when
another shard or account fails.
Its candidate stage reports a distinct profile/relationship preparation step before bounded deep
analysis; this preparation populates only task-local read caches and remains cancellation-neutral.
Position-risk discovery restores its own job and checks cancellation between indexed daily source
shards and bounded account deep checks.

## API contract

Legacy polling views expose percent/message/result fields while native job rows/events remain authoritative.
Push-discovery results add failure totals, stage counts and normalized failure rows without removing
existing result fields.
The active-job lookup is read-only and prefers a running discovery job over queued work.

## Data, routing and read-only constraints

Jobs and events are stored in SQLite. Workers may call only governed read-only remote adapters.

## Business rules and units

Idempotency keys prevent duplicate logical submissions; progress is clamped to 0–100 and terminal
states are not overwritten by stale updates.

## Loading, empty and failure behavior

Unknown IDs return 404. Interrupted running work is recoverable according to queue policy; failure
events retain a sanitized reason. A browser fetch/network error does not convert a durable running
discovery job into a terminal failed state.
Subprocess output is read independently so cancellation is checked at least every 250 milliseconds,
including database phases that emit no progress lines.

## Code and dependencies

Web processes submit/read only; interactive and discovery workers execute separate queues and only
claim/recover their assigned job kinds.

## Tests and acceptance

Tests cover persistence, events, cancellation, legacy mapping and recovery after worker restart.

## Compatibility and deprecation

Existing Toxic and K-line polling contracts remain supported.
K-line result additions are stored in the existing `result_json`; no SQLite migration is required.
