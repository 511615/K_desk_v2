---
feature_id: JOB-RECOVERY-001
title: Persistent job progress and recovery
module: jobs
status: active
apis: ["GET /api/kline/jobs/{job_id}", "GET /api/toxic/jobs/{job_id}", "GET /api/push-discovery/jobs/{job_id}", "POST /api/jobs/{job_id}/cancel"]
code: ["src/kdesk/infrastructure/database.py", "src/kdesk/worker/runner.py", "src/kdesk/api/account_app.py", "scripts/start_dev.ps1", "scripts/start_prod.ps1", "scripts/stop_prod.ps1"]
tests: ["tests/test_api.py", "tests/test_ledger.py", "legacy/apps/problem_account_registry/test_app.py"]
depends_on: []
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# Persistent job progress and recovery

## Purpose and user entry

Provide durable K-line, Toxic and discovery jobs with progress, events, retry/cancel and restart recovery.

## UI and behavior

Pages poll stable job IDs. Queued, running, done, failed and cancelled states have clear messages.

## API contract

Legacy polling views expose percent/message/result fields while native job rows/events remain authoritative.

## Data, routing and read-only constraints

Jobs and events are stored in SQLite. Workers may call only governed read-only remote adapters.

## Business rules and units

Idempotency keys prevent duplicate logical submissions; progress is clamped to 0–100 and terminal
states are not overwritten by stale updates.

## Loading, empty and failure behavior

Unknown IDs return 404. Interrupted running work is recoverable according to queue policy; failure
events retain a sanitized reason.

## Code and dependencies

Web processes submit/read only; interactive and discovery workers execute separate queues and only
claim/recover their assigned job kinds.

## Tests and acceptance

Tests cover persistence, events, cancellation, legacy mapping and recovery after worker restart.

## Compatibility and deprecation

Existing Toxic and K-line polling contracts remain supported.
