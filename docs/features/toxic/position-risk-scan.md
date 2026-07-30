---
feature_id: TOX-POSITION-SCAN-001
title: Platform heavy-position timing discovery
module: toxic
status: active
apis: ["POST /api/position-risk/scans", "GET /api/position-risk/scans/active", "GET /api/position-risk/scans/{job_id}"]
code: ["src/kdesk/application/position_risk_scan.py", "src/kdesk/infrastructure/position_risk_scan.py", "src/kdesk/worker/runner.py", "src/kdesk/api/account_app.py", "frontend/src/components/PositionRiskDiscoveryPanel.vue", "frontend/src/positionRiskDiscovery.ts", "frontend/src/pages/WorkbenchPage.vue", "frontend/src/styles.css"]
tests: ["tests/test_position_risk_scan.py", "tests/test_position_risk_infrastructure.py", "tests/test_api.py", "tests/test_worker.py", "frontend/src/positionRiskDiscovery.spec.ts"]
depends_on: ["TOX-POSITION-001", "JOB-RECOVERY-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Platform heavy-position timing discovery

## Purpose and user entry

Discover account-relative heavy positions around weekend closure and the low-liquidity opening window
across AC/DBG routes. The workbench exposes the fourth `重仓时点发现` tab in `全平台风险发现`.

## UI and behavior

Operators choose a time range, environments, deep-account limit, handled-account exclusion and result
level. Optional minimum position, peak-lot and event-profit inputs are blank by default. Position means
estimated event margin divided by event equity and is entered as a percentage; profit is event net
profit in the account display currency. Results can be reordered without another database scan by
score, event net profit or position fullness, all descending. Ranking rows show peak lots/order
count/notional, leverage, economic ratios, penetration status,
same-direction peers, opposite-direction suspected hedge peers and a wrapped plain-language conclusion.
Each row opens a compact analysis modal containing the complete conclusion, evidence limitations,
negative-balance clues, exact heavy-position orders, estimated margin amount, both margin ratios, full
peer-source coverage and exact matched target/peer orders. Durable job state survives navigation and transient polling failures.

## API contract

Submission accepts a maximum 90-day range, one or more known environments, a 1-300 deep limit, a
Boolean handled-account switch and nullable non-negative `minPositionPercent`, `minLots` and
`minProfit` values. The active and job endpoints follow existing native durable-job contracts.
Cancellation uses the shared job endpoint.

## Data, routing and read-only constraints

Candidate discovery scans only indexed MT5 `Time` or MT4 `OPEN_TIME` ranges in daily shards and
aggregates five-minute login/symbol/action batches in SQL; opening proximity is used only to prioritize
the queue and never enters the final score or displayed evidence. Deep verification searches every
configured AC/DBG MT4 and MT5 physical source, requiring canonical-symbol equality plus opening and
final closing deltas of at most five seconds. Direction splits exact order pairs into same-direction
coordination and opposite-direction suspected hedge lists; an opposite pair also requires at least 80%
lot similarity. Equivalent target time windows are queried once before a saturated multi-target
synchronized-order query recursively splits its target batch;
only a single target's own five-second window may still fail the source as incomplete. MT5 opening
candidates must already match a target symbol prefix inside the indexed five-second SQL window before complete Position deals
are loaded; opposite candidates also pass the 80% lot gate at this stage, while same-direction
coordination remains unrestricted by lots. Shared AC MT4 and DBG MT5 physical tables are
scanned once. CRM route validation plus current balance/equity/leverage use batches of 500. The candidate
stage never reads unindexed `mt5_daily_view` or AC `mt5_positions_snap`. Deep reads are limited to ranked
accounts and use indexed login/time history. DBG MT5 Live2 is a separate configured physical source
validated by `crm_vn` code 5. All queries are SELECT-only.

## Business rules and units

The candidate event window adds no final risk score. MT5 fast notional uses deal volume, contract size
and entry price; MT4 uses a conservative symbol-family contract estimate. Each account is ranked by its
single highest five-minute event's current-equity margin/stress proxy, configured leverage and peer
counts rather than cumulative multi-day turnover, after which `TOX-POSITION-001` reconstructs historical event equity
and provides the authoritative score. Final P/L is not a gate. Synchronized peers strengthen but are not
required. Estimated margin is peak notional divided by configured leverage. Margin/equity is higher when
fuller; estimated margin level is equity/margin times 100 and is lower when fuller.

Optional thresholds are exact post-analysis result filters and never alter the domain score. The
candidate queue uses the cheap initial position and lot estimates only to prioritize likely qualifying
accounts within the operator's deep limit; final inclusion always uses reconstructed event
`marginRatio`, `peakLots` and `netProfit`. Missing evidence cannot satisfy an enabled threshold.

## Loading, empty and failure behavior

At most four physical sources and three deep accounts run concurrently. Cancellation is checked between
daily shards and accounts. Source/account failures are additive and successful results remain visible.
Empty or lower-level results explain how to widen the display level without changing the scan.
Peer verification reports complete, partial-failure or data-insufficient coverage; it never treats a
failed physical source or an unclosed target order as a clean no-peer result.
Historical job snapshots without synchronized-close coverage are labeled `需重跑`; their opening-only
peer arrays are hidden. Missing additive margin amount/level fields are derived from the preserved
notional, leverage and margin/equity values for display compatibility.

## Code and dependencies

Application code owns sharding, merging, bounded concurrency and ranking. Infrastructure owns physical
source deduplication, batch routing/profile reads and SQL. The shared position-risk service owns scoring.

## Tests and acceptance

Tests cover option bounds, handled-account exclusion, economic warning output, exact five-second open
and close matching, rejection of opening-only candidates, all-source iteration and deduplication,
rejection of opposite pairs below 80% lot similarity, partial source failure, peak order/lot projection,
penetration states, persistent API submission/recovery,
Worker composition, routed links, optional threshold boundaries, result sorting, level filtering and
production frontend build. Query acceptance must
verify indexed time predicates and no unindexed MT5 daily-view scan.

## Compatibility and deprecation

This is additive. Existing push, rebate and bonus discovery tabs and contracts are unchanged. Older
workers ignore the new job kind; restart discovery workers after deployment.
