---
feature_id: JOB-RECOVERY-001
title: Persistent job progress and recovery
module: jobs
status: active
apis: ["GET /api/kline/jobs/{job_id}", "GET /api/toxic/jobs/{job_id}", "GET /api/push-discovery/jobs/{job_id}", "GET /api/push-discovery/active", "GET /api/rebate-churning/scans/{job_id}", "GET /api/bonus-arbitrage/scans/active", "GET /api/bonus-arbitrage/scans/{job_id}", "GET /api/position-risk/scans/active", "GET /api/position-risk/scans/{job_id}", "POST /api/jobs/{job_id}/cancel"]
code: ["src/kdesk/infrastructure/database.py", "src/kdesk/worker/runner.py", "src/kdesk/api/account_app.py", "frontend/src/pushDiscovery.ts", "frontend/src/frontendUpdate.ts", "frontend/src/components/BonusArbitrageDiscoveryPanel.vue", "frontend/src/components/PositionRiskDiscoveryPanel.vue", "scripts/start_dev.ps1", "scripts/start_prod.ps1", "scripts/stop_prod.ps1", "scripts/health_check_prod.ps1", "scripts/promote_dev.ps1"]
tests: ["tests/test_api.py", "tests/test_ledger.py", "tests/test_worker.py", "frontend/src/pushDiscovery.spec.ts", "frontend/src/frontendUpdate.spec.ts", "frontend/src/bonusDiscovery.spec.ts", "frontend/src/positionRiskDiscovery.spec.ts", "legacy/apps/problem_account_registry/test_app.py"]
depends_on: []
last_verified_version: 2.1.0
last_verified_date: 2026-08-13
---

# Persistent job progress and recovery

## Purpose and user entry

Provide durable K-line, Toxic, push-discovery, rebate-discovery, bonus-discovery and position-risk jobs with progress, events,
retry/cancel and restart recovery.

## UI and behavior

Pages poll stable job IDs. Queued, running, done, failed and cancelled states have clear messages.
Completed discovery jobs retain and display non-fatal source/account failures alongside successes.
K-line jobs likewise retain per-symbol failures and mark the result partial when at least one other
symbol generated successfully. The upload page treats inspection and generation as two durable job
stages: after inspection reaches `done`, it submits the generation job from the parsed symbol and
time range, then exposes the generated chart link. Inspection completion alone is not a chart
completion signal.
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
existing result fields. The active-job lookup is read-only and deterministically prefers a running
job over queued work, including when both rows have equal or empty timestamp fields.

## Data, routing and read-only constraints

Jobs and events are stored in SQLite. Workers may call only governed read-only remote adapters.
Production launcher configuration is inherited by the web and Worker child processes. K-line jobs
therefore use the same dedicated read-only quote Terminal after a controlled service restart; a
stale interactive Terminal is not an implicit Worker fallback.
On Windows, the launcher explicitly pins `PYTHONPATH` to the current main checkout's `src` and
disables user-site packages before spawning Uvicorn and Worker children. This prevents the
virtualenv launcher from resolving an older K_desk package from the developer runtime while the
health endpoint still reports production paths.
Readiness binds process ownership to the production runtime, not merely to a port or FastAPI module:
8777 must report `profile=prod` and the production `kdesk.sqlite`; 8766 must report that same file as
`workerQueue`; each listener's Uvicorn supervisor must originate from the current main worktree's
`.venv`. A mismatch is replaced before jobs can be accepted.
Process discovery skips unrelated protected Windows processes; a permission-denied system process
cannot abort K_desk stop/start recovery.
Each Worker publishes a short-lived JSON marker under `runtime/prod/workers` while alive. Production
health checks use these queue-specific markers when Windows process command-line inspection is
restricted, so readiness cannot silently pass without an interactive or discovery consumer.

## Business rules and units

Idempotency keys prevent duplicate logical submissions; progress is clamped to 0–100 and terminal
states are not overwritten by stale updates.

## Loading, empty and failure behavior

Unknown IDs return 404. Interrupted running work is recoverable according to queue policy; failure
events retain a sanitized reason. A browser fetch/network error does not convert a durable running
discovery job into a terminal failed state.
Workers claim jobs with an atomic SQLite status transition and refresh a five-second lease while executing. A running job is only re-queued after its
lease has been stale for 180 seconds, so a second Worker cannot reset a healthy long-running scan.
The production launcher starts one interactive Worker and two discovery Workers by default; a long
position-risk scan therefore cannot block every other discovery kind.
Subprocess output is read independently so cancellation is checked at least every 250 milliseconds,
including database phases that emit no progress lines.
Push discovery additionally receives a stage heartbeat from its isolated per-account deep-check
child at least every 10 seconds. A child exceeding its documented budget is terminated and retained
as a recoverable account failure, allowing the durable parent job to continue and preserving its
completed checkpoint rows. A push-discovery Worker restart requeues one interrupted attempt; a
second interruption remains terminal and explicit.

## Code and dependencies

Web processes submit/read only; interactive and discovery workers execute separate queues and only
claim/recover their assigned job kinds. Production readiness also checks that both Worker queues
have a live process; an account-only start must explicitly use the account-only health check.
The controlled promotion script reads full Git output lines before checking branch names and SHAs;
PowerShell scalar-string indexing must not turn those values into individual characters.
The controlled stop script waits for each owned web listener to exit before the start phase. A
successful readiness response alone is insufficient because an old Uvicorn process can otherwise
keep a previous legacy-page module in memory while exposing current file-based release metadata.

## Tests and acceptance

Tests cover persistence, events, cancellation, deep-check timeout isolation, legacy mapping and
recovery after worker restart.

## Compatibility and deprecation

Existing Toxic and K-line polling contracts remain supported.
K-line result additions are stored in the existing `result_json`; no SQLite migration is required.
