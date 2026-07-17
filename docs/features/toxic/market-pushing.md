---
feature_id: TOX-PUSH-001
title: Market-pushing detection
module: toxic
status: active
apis: ["POST /api/accounts/by-login/{login}/toxic-checks", "GET /api/toxic/jobs/{job_id}", "POST /api/push-discovery/start"]
code: ["legacy/apps/problem_account_registry/app.py", "legacy/scripts/run_ac_mt5_push_validation.py", "legacy/scripts/run_platform_push_discovery.py", "src/kdesk/worker/runner.py", "frontend/src/pages/AccountPage.vue", "frontend/src/pages/WorkbenchPage.vue", "frontend/src/styles.css"]
tests: ["legacy/apps/problem_account_registry/test_app.py", "legacy/scripts/test_run_platform_push_discovery.py"]
depends_on: ["JOB-RECOVERY-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# Market-pushing detection

## Purpose and user entry

Run selected Toxic checks for one account or discover platform candidates, with evidence for
coordinated peers, order timing and available ticks.

## UI and behavior

The old detail dialog shows real progress, stage messages, suspected accomplices and synchronized
order-by-order comparisons. Workbench discovery exposes configurable profit, order count, maximum
lot, total profit, deposit, active-ratio, handled-account and deep-analysis limits.

## API contract

Submission returns a durable job ID. Polling preserves the legacy progress/result contract while
reading native persistent jobs. Discovery filter values are validated and persisted in the job payload.

## Data, routing and read-only constraints

Trade databases and MT5 quote terminals are query-only. No detector can modify MT state.

## Business rules and units

Selected detector order sets remain isolated. Unavailable ticks or peers are limitations rather
than negative evidence; scoring uses only the documented filtered sample.

## Loading, empty and failure behavior

Queued/running stages provide messages and monotonic progress. Failure, cancellation and partial
evidence are terminal explicit states; polling must not freeze on false progress.

## Code and dependencies

Persistent workers call governed legacy detector functions and persist progress snapshots/events.

## Tests and acceptance

Tests cover progress mapping, selected order filters, peer comparisons, quote-provider failures and restart recovery.

## Compatibility and deprecation

Legacy Toxic polling keys remain supported by `_legacy_job_view`.
