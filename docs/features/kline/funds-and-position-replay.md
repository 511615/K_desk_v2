---
feature_id: KLN-TIMELINE-001
title: K-line funds and position replay
module: kline
status: active
apis: ["POST /api/kline/generate-from-db", "GET /api/kline/jobs/{job_id}", "GET /output/{name}"]
code: ["src/kdesk/application/kline_timeline_cache.py", "src/kdesk/domain/kline_timeline.py", "src/kdesk/api/account_app.py", "src/kdesk/worker/runner.py", "frontend/src/pages/AccountPage.vue", "legacy/apps/problem_account_registry/app.py", "legacy/tools/trade_kline_tool/generate_trade_kline_from_statement.py", "legacy/tools/trade_kline_tool/fused_trade_kline_features.py", "legacy/tools/trade_kline_tool/account_timeline_features.py", "legacy/tools/trade_kline_tool/position_fused_trade_kline.py"]
tests: ["tests/test_kline_timeline_cache.py", "tests/test_kline_timeline.py", "tests/test_kline.py", "tests/test_historical_funds.py"]
depends_on: ["KLN-DB-001", "FIN-HISTORY-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-07
---

# K-line funds and position replay

## Purpose and user entry

This extends the existing database K-line action and output HTML; it introduces no new page, port,
or user-facing request path. The user can choose whether a generated database chart includes the
selected account route's factual Balance/Credit replay and chronological funds-and-order event table.

## UI and behavior

The database K-line controls include an unchecked `包含资金与 Credit 回放` option and a dependent
`刷新全量资金缓存` option. Dates are blank by default, which means complete history for the selected
account/order scope. With replay disabled, the chart retains the pre-existing order-only behavior.
With replay enabled, the first request reads the entire selected account-route funds history and saves
it locally; later chart requests reuse that complete cache even when the visible date range changes.
Only the explicit refresh option reads the remote source again.

The bottom chart switcher adds `资金` beside the existing Profit, hand-size and position panels.
It draws Balance in blue, Credit in orange and red liquidation dots for the factual liquidation
points already identified by `FIN-HISTORY-001`. The original raw order table remains unchanged. A
second paged `资金与订单事件` table lists order opening/closing and balance/Credit actions in timestamp
order; selecting a row moves the K-line viewport to that timestamp.

The `仓位` panel displays exact open-order count and lots from the chart order scope. Its Balance and
Credit card is sourced from the same replay. It no longer defaults to a 10,000 balance or 1:500
leverage. Historical intraday margin, margin level and equity are unavailable unless a platform
snapshot is supplied, so this panel deliberately labels them as unavailable rather than calculating
an apparently precise value from a fake opening balance. Floating P/L remains explicitly quote-based.

## API contract

`POST /api/kline/generate-from-db` remains compatible and additively accepts boolean
`includeTimeline` (default `false`) and `refreshTimelineCache` (effective only when replay is
included, default `false`). An opted-in job writes a versioned, runtime-private `*_timeline.json`
input and embeds it in the existing standalone `*_trade_kline.html`; opening the artifact does not
need another 8777/8766 request. Job result data additively exposes timeline availability, event
counts, liquidation count, cache status and a sanitized reason when the timeline is unavailable.
Existing chart names, preview URLs and task polling are unchanged.

## Data, routing and read-only constraints

The job uses the requested single platform/server route for both orders and the funds replay. It
reuses the `FIN-HISTORY-001` raw source and pure replay rules directly; it does not make an HTTP call
back into the account service. The complete replay cache is keyed by account, platform and server,
is stored under `runtime/<profile>/cache/kline_timeline`, and contains no data from another logical
route. The visible timeline is then bounded to the requested K-line time range and carries the most
recent known Balance/Credit state before the range. If no authoritative carry-in exists, the state
remains unknown, never zero or a default balance.

## Business rules and units

Funding rows retain the established distinction between external cash, internal transfer, Credit,
negative-balance clear, compensation and adjustment. The output is factual evidence only: it does
not decide whether Credit is loss-resistant, whether it should be deducted, or whether the customer
is owed compensation. MT4/MT5/CRM reads stay read-only. USD/USC money uses the account money scale.

## Loading, empty and failure behavior

Quote/chart generation can complete when an opted-in funds replay is unavailable; the chart then
displays an explicit unavailable state rather than zero lines. A source ambiguity or database failure
cannot be silently merged with another route. Event tables paginate at 200 rows. The complete cache,
worker-owned input JSON and final HTML remain inside the configured runtime directory.

## Code and dependencies

The application `KlineTimelineCache` owns durable full-replay reuse. The pure `kline_timeline`
Domain module trims that replay and preserves an explicit carry-in state. The legacy K-line adapter
only reads routed source facts on cache build/explicit refresh, writes a local runtime input JSON and
invokes the existing generator. The generator and its versioned HTML feature modules embed the data;
no browser-side API call or write adapter is introduced.

## Tests and acceptance

Cache tests prove the first complete build, reuse without another source read, explicit refresh and
invalid-local-cache recovery. Pure tests prove a selected window receives a known carry-in state,
categorizes order/funds events, and preserves unknown pre-anchor state. HTML tests prove the artifact
embeds the timeline, funds switcher, event table and corrected position wording, and JavaScript parses.
Historical-funds fixtures continue to cover MT4 cash/Credit/clear, MT5 Action 2/3 and liquidation
markers. Manual acceptance checks both checkbox states, an MT4 and MT5 chart, USD and USC scaling,
a cache reuse, explicit refresh, a chart with unavailable funds data, an event-table jump and an HTML
opened without the web services.

## Compatibility and deprecation

This is additive to existing K-line outputs. Older artifacts remain unchanged and readable. Rollback
removes the timeline input and injected controls from newly generated artifacts only; it has no
database migration and does not alter source account data.
