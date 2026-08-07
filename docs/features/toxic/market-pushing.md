---
feature_id: TOX-PUSH-001
title: Market-pushing detection
module: toxic
status: active
apis: ["POST /api/accounts/by-login/{login}/toxic-checks", "GET /api/toxic/jobs/{job_id}", "POST /api/push-discovery/start", "GET /api/push-discovery/active"]
code: ["legacy/apps/problem_account_registry/app.py", "legacy/scripts/run_ac_mt5_push_validation.py", "legacy/scripts/run_platform_push_discovery.py", "src/kdesk/worker/runner.py", "frontend/src/pages/AccountPage.vue", "frontend/src/pages/WorkbenchPage.vue", "frontend/src/pushDiscovery.ts", "frontend/src/styles.css"]
tests: ["legacy/apps/problem_account_registry/test_app.py", "legacy/scripts/test_run_platform_push_discovery.py", "tests/test_worker.py", "frontend/src/pushDiscovery.spec.ts"]
depends_on: ["JOB-RECOVERY-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-04
---

# Market-pushing detection

## Purpose and user entry

Run selected Toxic checks for one account or discover platform candidates, with evidence for
coordinated peers, order timing and available ticks.

## UI and behavior

The old detail dialog shows real progress, stage messages, suspected accomplices and synchronized
order-by-order comparisons. Workbench discovery exposes configurable profit, order count, maximum
lot, total profit, deposit, active-ratio, handled-account and deep-analysis limits. Completed
discovery results list partial failures after successful accounts, including stage, account/source,
plain-language reason, impact and retry count. A temporary account-service disconnect preserves the
durable discovery job ID and displayed progress while polling retries with a bounded delay.
The latest discovery job ID is retained across account-detail navigation and page reloads.
The workbench section now uses fixed `推盘发现` and `刷返佣发现` tabs; switching tabs preserves the
push form, durable job and result contract.
Candidate aggregation reports shard and profile progress instead of holding at one source-level
percentage during a long database query.
The discovery result table lists only accounts that pass the fixed economic-evidence gate after
deep analysis. Its summary shows completed deep checks, economically qualified accounts and
low/negative-profit exclusions. Qualified rows expose suspected-interval return on cumulative
deposit when that denominator is available.

## API contract

Submission returns a durable job ID. Polling preserves the legacy progress/result contract while
reading native persistent jobs. Discovery filter values are validated and persisted in the job payload.
The additive discovery result fields are `failureTotal`, `failureSummary` and `failures`; existing
`summary` and `results` consumers remain compatible.
Additive summary fields `structuralEligible`, `lifetimeProfiled` and `unprofiledStructural` explain
progressive Top-N profiling without changing existing result rows.
Additive summary fields `economicQualified`, `economicallyRejected` and `economicRules` explain the
fixed final-result gate. Result rows add `suspectedIntervalReturnPct`, `economicQualified` and
`economicReason`.
`GET /api/push-discovery/active` returns the current running job, otherwise the latest queued job,
or `null` when no discovery job is active.

## Data, routing and read-only constraints

Trade databases and MT5 quote terminals are query-only. No detector can modify MT state.
The configured discovery set includes DBG MT5 Live2 on `crm_vn` code 5; its time-first and Position
completion reads use the verified `INDEX_TIME` and `INDEX_POSITIONID` names in `crm_vn_mt5_live2`.
Discovery aggregates MT5 windows in 12-hour shards and MT4 windows in daily shards. A timed-out
shard is bisected down to a 30-minute minimum rather than retrying the whole source with a larger
timeout. Profit and maximum lot merge exactly. MT4 trade counts are additive; MT5 shard counts are
an upper bound, so accounts that cross the configured order limit are re-counted with exact distinct
positions before exclusion. Candidate currency and Cent scaling come from the indexed users-group
path; discovery does not query the unindexed `mt5_daily_view`. Lifetime profile aggregation is
serialized per physical database while AC and DBG may run in parallel. Active-day distinct counting
is omitted unless the active-ratio filter is enabled. Lifetime queries use 10-account indexed
batches with a 45-second budget; a transient timeout reopens the connection with 5-account batches
without repeating the completed window aggregation.
Lifetime trading net preserves the platform accounting identity without scanning every trade row:
MT5 uses current `Balance` minus the net of `Action>=2` ledger deals, while MT4 uses current
`BALANCE` minus `CMD=6` balance rows. Deposit filtering remains the documented positive-deposit
subset of those ledger rows.
For query planning, window/order/lot/handled filters run before structural screening. Optional
lifetime profit, deposit and active-ratio filters run only on structurally eligible accounts, but
always before rank truncation and deep analysis. Because structure ranking does not depend on those
lifetime fields, candidates are profiled in structure-rank chunks until the requested deep limit is
filled. This produces the same Top-N filtered deep queue without profiling ordinary or lower-ranked
candidates. Summary fields distinguish `structuralEligible`, `lifetimeProfiled` and
`unprofiledStructural`.
Window-order loading scans the same bounded time shards through the native close-time index. MT5
selects exact closed `(Login, PositionID)` pairs and joins their complete deal histories through the
position index; deals repeated across partial-close shards are de-duplicated by primary deal ID.
MT4 reads the exact candidate logins through `INDEX_CLOSETIME`. The prior 50-account path remains an
automatic fallback and recursively reconnects/splits to five accounts when a time-first query cannot
complete. Structure scoring therefore receives the same reconstructed order rows without repeated
full-history login scans.

Single-account deep checks query independent same-platform server sources concurrently, then merge
them in the configured source order before applying the unchanged synchronization rules. Tick
analysis combines overlapping or nearby quote windows only when their total span is at most 15
minutes, then slices the returned ticks back to every order's original exact boundaries. An empty
slice is retried with the original per-order request, so batching cannot reduce quote coverage.
Independent structure scores are evaluated in 125-account batches with at most two worker processes
and restored to input order before ranking. A process-pool failure retries the complete stage through
the original serial path; the small worker cap bounds memory use on the production host.
Discovery always profiles lifetime trading net and cumulative deposit for structurally ranked
candidates because those values are required by the final economic definition even when the
optional candidate filters are disabled. Non-positive lifetime net is rejected before expensive
Tick and synchronization analysis. Completed deep checks that fail only the interval economics
gate are retained in `economic_rejections.json` for local audit and are not reported as failures.

## Business rules and units

Selected detector order sets remain isolated. Unavailable ticks or peers are limitations rather
than negative evidence; scoring uses only the documented filtered sample. Platform discovery
requires positive lifetime trading net and positive suspected-interval net. The interval is
economically meaningful when its normalized net is at least 100 display-currency units, or at
least 50 units and at least 10% of cumulative qualifying deposits. These inclusive thresholds are
classification evidence, not optional candidate breadth controls.

## Loading, empty and failure behavior

Queued/running stages provide messages and monotonic progress, including shard, server, order-load,
structure and ranked-profile phases. Failure, cancellation and partial
evidence are terminal explicit states; polling must not freeze on false progress. A completed job
may contain per-source or per-account failures, which remain visible instead of being discarded.
Network fetch errors are recoverable polling states, not terminal detection failures.
Cancellation remains visible until the persistent worker confirms the terminal cancelled state.
Every deep candidate runs in an isolated child process. The parent emits the current deep stage
(`load_history`, `build_context`, `finance`, `cross_account_sync`, `tick_analysis` or `score`) on
entry and a heartbeat at least every 10 seconds while remote reads are pending. A candidate that
exceeds the fixed 300-second budget is terminated without changing any remote state, persisted as a
recoverable deep-stage failure and does not block later candidates or the discovery queue. A timeout
is unavailable evidence, never a clean result or a no-risk conclusion.
The production discovery queue runs two independent Workers. A long-running position-risk,
rebate, bonus or push scan may continue independently while another discovery job is claimed.

## Code and dependencies

Persistent workers call governed legacy detector functions and persist progress snapshots/events.

## Tests and acceptance

Tests cover progress mapping, selected order filters, peer comparisons, quote-provider failures,
partial failure serialization, bounded candidate shards, exact cross-shard MT5 order reconciliation,
time-first order reconstruction and de-duplication, concurrent synchronization source ordering,
exact Tick-window slicing, serial/parallel structure-score equivalence, absence of candidate
daily-view queries, deep-stage heartbeat and timeout isolation, transient polling disconnects,
restart recovery and the inclusive absolute and
deposit-relative economic boundaries.

## Compatibility and deprecation

Legacy Toxic polling keys remain supported by `_legacy_job_view`.
