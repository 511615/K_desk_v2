---
feature_id: TOX-POSITION-001
title: Heavy-position weekend and opening risk detection
module: toxic
status: active
apis: ["GET /api/toxic/check-types", "POST /api/accounts/by-login/{login}/toxic-checks", "GET /api/toxic/jobs/{job_id}"]
code: ["src/kdesk/domain/position_risk.py", "src/kdesk/application/position_risk.py", "src/kdesk/infrastructure/position_risk.py", "src/kdesk/worker/runner.py", "legacy/apps/problem_account_registry/app.py"]
tests: ["tests/test_position_risk.py", "tests/test_position_risk_infrastructure.py", "tests/test_worker.py"]
depends_on: ["JOB-RECOVERY-001", "ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Heavy-position weekend and opening risk detection

## Purpose and user entry

Replace the legacy time-only `周末跳空交易` and burst-only `赌开盘` Toxic rules with one
account-relative position-risk model. Operators run either check from the existing account detail page.

## UI and behavior

Each result explains the event in ordinary language and shows event cash equity, configured leverage,
peak lots, peak concurrent entry-order count, peak gross notional, gross notional/equity, estimated
margin amount, margin/equity, estimated margin level, stress loss/equity, normal-exposure multiple, direction concentration, five-minute
entry concentration, holding time and final P/L. The evidence payload lists the exact MT4 ticket or
MT5 Order/Position identifiers that formed the peak heavy position. Profit is descriptive and never
decides eligibility. Peer evidence names the matched account, platform, logical server/database,
target order, peer order/position/deal, lots, timestamps and open/close deltas.
Shared physical tables resolve each matched login back to its CRM logical server. Unique account and
order-pair totals remain complete; each direction retains at most 500 detailed pairs to bound job size.

## API contract

Existing Toxic endpoints and type IDs remain unchanged. The Worker replaces only the two legacy result
rows and additively stores `positionRisk`; other Toxic rows retain their prior schema and behavior.
`open_betting` no longer requests Tick data because this rule depends on position exposure and timing.

## Data, routing and read-only constraints

The selected CRM schema/server/login route is authoritative for the target account. Indexed account-and-time reads load at
most a 400-day analysis history, or the requested event window plus a 180-day baseline. Current account
balance, equity and leverage come from the routed user/account view. Remote access is SELECT-only and
never uses Manager mutation operations. Final peer verification reads every configured AC/DBG MT4 and
MT5 physical trade source, deduplicating shared AC MT4 and DBG MT5 tables. Each source uses bounded
opening-time windows; MT5 candidate positions are completed by bounded position batches. Ledger comments
are retained only to recognize a post-event negative-balance reset/clear clue. DBG MT5 Live2
contributes its independent `crm_vn_mt5_live2` physical source and code 5 route.

## Business rules and units

Economic heavy positioning is a hard gate: estimated peak margin/equity must reach 30%, or historical
event stress loss/equity must reach 10%. High/severe reference thresholds are 50%/70% margin and
20%/35% stress. Relative exposure references are 2x/3x/5x and net-direction references are
70%/85%/95%. Gross notional is inferred first from realized P/L sensitivity to relative price movement,
then from volume, contract size and price when sensitivity is unavailable. Estimated margin divides
notional by configured leverage, while gross notional/equity remains visible so 1:500 or 1:1000 leverage
cannot hide a large economic position. Leverage contributes only a small contextual score and cannot
create a finding without the hard gate.

`estimatedMargin = peakGrossExposure / configuredLeverage`. `marginRatio = estimatedMargin /
eventEquity`, so a higher value means the account is fuller. `estimatedMarginLevel = eventEquity /
estimatedMargin * 100%`, so a lower value means the account is fuller. Both are historical-event
estimates rather than the current platform margin fields.

Weekend events require Friday evening exposure held at least 30 hours into Sunday/Monday. Opening
events require concentrated entries between 21:45 and 22:30 in database time `+08:00`. Weekend
positions followed by new/reversed reopening exposure are classified as combined. Five-minute batch
entry/exit and short open-event holding strengthen evidence. A peer counts only when both accounts are
fully closed, the canonical symbol matches, and both opening and final closing differ by at most five
seconds. Same-direction pairs strengthen coordination; opposite-direction pairs additionally require
`min(target lots, peer lots) / max(target lots, peer lots) >= 80%` and are exposed separately
as suspected hedge clues and never labeled as confirmed hedging. Candidate opening-only proximity never
enters the final score or evidence. An actual event
loss above reconstructed event equity is reported as penetration `是`; a reset/clear clue without that
calculation is `疑似`; a completed event without either is `否`; open events or an unreliable equity
fallback are `数据不足`. The response separately states `事件仍有未平仓订单` and/or
`事件前权益无法从历史现金流水可靠倒推`. Staggered additions,
long holding and weak economic exposure reduce or cap the score.

## Loading, empty and failure behavior

Missing event timing produces a zero result. Timing without heavy positioning is capped below concern.
Missing baseline history is disclosed and does not invent a relative multiple. A routed history failure
returns a per-type evidence-unavailable result without removing other Toxic results.
Peer coverage reports total/scanned physical sources, per-source failures and target orders skipped for
missing close time. One failed source is `部分失败`; no closed target order is `数据不足`.

## Code and dependencies

Pure exposure reconstruction and scoring live in the domain module. Application code coordinates the
analysis. Infrastructure owns routed SELECT queries. Worker/API modules only compose existing jobs.

## Tests and acceptance

Tests cover the economic hard gate, 1:1000 leverage, margin formulas, explicit penetration gaps,
open-and-close synchronization, missing/late closes, cross-platform order detail, source deduplication,
partial peer coverage, combined weekend and reopening behavior, staggered-entry counterevidence and replacement of both legacy Toxic rows. Labeled
acceptance accounts include 624221, 632185, 205537 and 5005153; 639631 remains a counterexample for
batch-style inference when entries are progressively added while prior positions remain open.

## Compatibility and deprecation

The two legacy heuristics remain in copied code only as rollback behavior. Their public IDs and account
page controls are compatible; the native Worker result is authoritative.
