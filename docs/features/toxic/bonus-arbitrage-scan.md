---
feature_id: TOX-BONUS-SCAN-001
title: Platform bonus-arbitrage discovery
module: toxic
status: active
apis: ["POST /api/bonus-arbitrage/scans", "GET /api/bonus-arbitrage/scans/active", "GET /api/bonus-arbitrage/scans/{job_id}"]
code: ["src/kdesk/application/bonus_arbitrage_scan.py", "src/kdesk/infrastructure/bonus_arbitrage_scan.py", "src/kdesk/worker/runner.py", "src/kdesk/api/account_app.py", "frontend/src/components/BonusArbitrageDiscoveryPanel.vue", "frontend/src/bonusDiscovery.ts", "frontend/src/pages/WorkbenchPage.vue", "frontend/src/styles.css"]
tests: ["tests/test_bonus_arbitrage_scan.py", "tests/test_api.py", "tests/test_worker.py", "frontend/src/bonusDiscovery.spec.ts"]
depends_on: ["TOX-BONUS-001", "JOB-RECOVERY-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Platform bonus-arbitrage discovery

## Purpose and user entry

Find previously unreviewed bonus-arbitrage accounts across every configured AC and DBG route. The
workbench exposes this as the third `赠金套利发现` tab in `全平台风险发现`.

## UI and behavior

The form defaults to the last 30 days and all four CRM environments. The deep-account limit and
handled-account exclusion are directly editable alongside the date/environment controls. Operators
can also set a minimum normalized grant amount and displayed risk level. The result shows
candidate/deep/failure counts and a ranking with current margin, cumulative deposit,
margin-to-deposit ratio and the strongest cycle's funding, grant, full-cycle minimum margin level,
equity, used margin, concurrent standard lots/order count, profit, extraction, closure match and suspected visible-hedge state.
The conclusion column opens a compact detail card containing the full conclusion, minimum-margin timestamp,
equity, used margin, concurrent lots, the orders held at that point, exact opposing-order pairs,
triggered rules and known limitations. Older completed jobs remain readable and tell the operator to
rerun when their stored result predates order-level margin evidence. Account links retain
platform and logical server routing. The durable job ID survives navigation, reload and transient
polling errors; running work can be cancelled.

## API contract

Submission normalizes a maximum 180-day window, one or more environments, a 1-300 deep limit, a
non-negative minimum grant and a Boolean handled-account switch into an idempotent durable job.
The active endpoint restores the current queued/running bonus scan. Polling returns summary,
warning results, all concise deep results, additive minimum-margin/position/order and suspected-hedge
evidence, and additive partial-failure rows.

## Data, routing and read-only constraints

Candidate discovery reads bounded daily MT5 `Action IN (3,6)` or MT4 `CMD=7` positive credit rows.
A failed daily shard falls back to six-hour shards. Physical source groups are scanned once; each
source's daily event rows are first merged by login, then batch-validated once against the CRM
`(schema, server code, login)` route in 500-login batches. This avoids
double-scanning shared AC MT4 and DBG MT5 tables without conflating their logical accounts. The
independent DBG MT5 Live2 physical source is scanned once and validated only against `crm_vn` code 5.
All remote access is read-only and selects no password, contact or API-data fields.

Candidate discovery runs at most four physical sources concurrently while each source keeps its
daily shards serial. Before deep analysis, candidate current profiles and same-user families are
prefetched per logical source into the task-local cache. After handled/minimum-grant filtering,
current margin and qualifying cumulative deposits are read in indexed login batches over the same
registration-to-400-day boundary used by an unbounded account check. The candidate CRM mapping is passed to the
account detector so it does not repeat account-route lookup. Deep analysis runs at most three
accounts concurrently; a six-way live trial was rejected because same-database contention increased
elapsed time. These fixed bounds
reduce full-platform wall time without issuing competing shard queries against one physical table
or changing per-account history scope.

## Business rules and units

The candidate window discovers accounts; it does not score them. Optional minimum grants and
handled-account exclusion run before rank truncation. Remaining candidates rank first by reliable
`current occupied margin / cumulative qualifying deposit`, descending. Accounts without a positive
recognized deposit rank after accounts with a ratio; explicit bonus evidence, normalized grant
amount, count and recency break ties and provide the fallback order when a ratio source fails.
This ranking decides only which accounts consume the operator-set deep limit and contributes no
risk score.
Every selected account is deep-checked over the existing full historical bonus-cycle scope. Peer
coordination uses the indexed five-second matcher, so a high-volume account cannot force an
all-pairs comparison across every related-account trade. Final
60/75/90 levels, completed extraction, locked-profit and historical funded-loss gates are owned by
`TOX-BONUS-001`. Cent/USC candidate amounts use the same confirmed `0.01` money scale.
The deep result also inherits the detector's hard 20% cycle-level `赠金 / 入金` requirement. A
candidate below that ratio can still consume one requested deep slot and expose its evidence, but
cannot appear in warning/high/severe results solely through extraction, repetition or peer matching.
Deep results reach high risk before extraction when the lowest standard margin level anywhere inside
an eligible Credit cycle is at or below 200%. Direction concentration is not used. The concise result
retains the preventive summary, structured minimum-margin fields, compatibility aliases and any historical
breach evidence. Missing visible peer accounts does not clear or lower the result because a hedge
may be outside the platform; visible opposite matches increase confidence only. A historical loss
of at least 75% of funded cash plus Credit warns, while a reset/clearing event, 100% funded loss or
current negative balance/equity is severe even when later activity restored the account.

## Loading, empty and failure behavior

Progress distinguishes source/day candidate scanning, margin/deposit ranking, candidate selection, account deep checks and
result assembly. Empty routes contribute zero candidates. Source-shard or account failures are
listed while successful results remain available. A ranking-source failure is listed and falls back
to the existing bonus-evidence order without dropping candidates. Cancellation is checked between shards and deep
accounts and during CPU-intensive related-order matching. A completed scan with no visible level
matches explains how to display lower-level rows.

## Code and dependencies

Application code validates options, merges candidates, ranks the bounded deep queue and projects
concise results. Infrastructure owns physical-source grouping and indexed read-only SQL. The shared
bonus-cycle service owns account scoring. API and Worker modules only compose these parts.

## Tests and acceptance

Tests cover option limits, handled-account exclusion, margin/deposit ordering, ranking fallback,
deposit/reversal classification, severe extraction and historical-breach output, shard fallback,
persistent API submission/recovery, Worker composition, level filtering, routed account links, the
compact evidence card's minimum-margin order and visible-hedge projections, and large related-account
histories without quadratic peer matching. Concurrency tests assert the
four-source and three-account ceilings while preserving every result.
Read-only acceptance finds account 621928 from its exact one-hour AC GB MT5 grant window before the
existing detector reconstructs its 90-point cycle.

## Compatibility and deprecation

This feature is additive. Existing Toxic, push-discovery and rebate-discovery contracts remain
unchanged. Rollback leaves durable job rows intact; an older worker will not claim this new kind.
