---
feature_id: FIN-HISTORY-001
title: Historical funds backtrace
module: finance
status: active
apis: ["GET /api/accounts/by-login/{login}/historical-funds"]
code: ["src/kdesk/domain/historical_funds.py", "src/kdesk/application/historical_funds.py", "src/kdesk/api/account_app.py", "legacy/apps/problem_account_registry/app.py"]
tests: ["tests/test_historical_funds.py", "tests/test_api.py", "legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-DETAIL-001", "ACC-SEARCH-001", "FIN-COMP-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-07
---

# Historical funds backtrace

## Purpose and user entry

`历史资金回溯` is a factual account-history view for reviewing the state around large losses,
negative balances, clear-to-zero entries, Credit changes and later funding. It is opened from the
legacy account detail toolbar immediately after `Toxic 检测` and always uses the selected
platform/server route. Its control remains visible and enabled when an account has no completed
order; the dialog then reports the available funding-history facts or its explicit empty state.

## UI and behavior

The dialog shows external deposits, external withdrawals, net external funding, internal transfers,
Credit granted/removed, negative-balance clear amount and daily-anchor count. It then renders a
balance/Credit curve and a paged event table. Events include market order opening/closing, platform
balance actions, Credit actions and daily snapshots. The page reports the exact source-row counts.

Balance and Credit after the first daily anchor are reconstructed from sourced event deltas. Equity
is displayed only at a sourced daily anchor; every other replayed event is explicitly marked as
having no intraday snapshot. Events before the first daily anchor remain visible but their
post-event balance, Credit and equity are unknown. The view never interpolates equity, margin or
margin level.

The response identifies a `liquidationPoint` only when the source event is a platform Stop Out
(MT4 `REASON=5` or MT5 `Reason=6`) or an explicit negative-balance clear row. The dialog shows the
complete set as red curve markers and jump controls. Selecting either moves to the exact raw event,
switches to its page and highlights the row. Stop loss, ordinary loss and ordinary withdrawal are
not liquidation points.

## API contract

`GET /api/accounts/by-login/{login}/historical-funds?platform=&server=` returns `ok`, `available`,
selected source identity, display currency, coverage, `summary`, complete `events` and display
`curve`. Existing account-detail URLs and query parameters remain compatible. The optional page
symbol filter is intentionally not used: funding and Credit history is account-wide.

When a Login is present on multiple routes without a selected route, the response returns
`available=false` and asks the caller to select platform/server. Database failures return a clear
unavailable response; a source must never be represented as a zero-value timeline. MT5 daily
snapshots are not queried by the online endpoint because the configured view is not indexed by
Login. If the complete indexed deal ledger and current account state were read successfully, the
response remains available and discloses `dailyAnchorsAvailable=false` with a safe reason instead
of returning HTTP 503.

## Data, routing and read-only constraints

The LegacyBridge resolves the selected account through the normal source registry, then reads its
complete MT4 trade/balance ledger or MT5 deal ledger and daily-account anchors. MT4 uses
`mt4_trades`, `mt4_daily` and users metadata; MT5 uses indexed `mt5_deals` and account metadata
plus the current `mt5_accounts` balance/Credit/equity row. The MT5 daily view is not read online:
it lacks a Login index and can turn an account query into a full-view scan. The current account row
calibrates balance/Credit reconstruction from the complete ledger; historical equity remains
unavailable. All operations are read-only. Neither this feature nor its code exposes an MT4/MT5/CRM
write operation. USD/USC money is scaled with the established account money metadata; lots, prices,
identifiers and timestamps are not scaled.

## Business rules and units

Market close amount is profit plus commission, swap/storage, fee and taxes where present. MT4
closed market rows use close time; open or sentinel rows use open time and do not create realized
P/L. Recognized external `DEP-`/`CRM-DP-` positives are deposits and negative `WDR-`/`CRM-CW`/`IPD`
rows are withdrawals. `TFM-`, `TFH-`, `TRS-`, `CRM-T` and explicit internal-transfer comments are
internal transfers, not external funding. Credit actions are separate from balance actions.

`RST-`, `CCB-` and explicit negative/zero-balance entries are shown as negative-balance clearing;
`CPS_`/compensation, reversal and other balance adjustments remain distinct. The output is evidence
for a reviewer. It does not declare that a clear amount, Credit amount or subsequent deposit should
be deducted, forgiven or repaid.

## Loading, empty and failure behavior

The modal opens immediately with a loading state. The table renders 100 events per page so a large
history does not block the browser. No history, an ambiguous route, unavailable database or missing
daily anchors is described explicitly. When daily anchors are missing but a current account anchor
is available, balance/Credit remain replayed and the UI states that only the current equity snapshot
is factual. Missing historical equity is never replaced with estimates.

## Code and dependencies

`historical_funds.py` in Domain performs pure normalization/classification/replay. The Application
service composes only routed raw facts provided through LegacyBridge. FastAPI and the legacy page
provide the API and UI boundary. This respects `interfaces -> application -> domain`; only the
LegacyBridge imports legacy data access.

`KLN-TIMELINE-001` reuses this same pure replay in its Worker-owned K-line artifact path. It passes
the selected account's normalized facts directly to the generator rather than calling this HTTP API,
so the generated chart stays standalone and route-consistent.

## Tests and acceptance

Unit fixtures cover MT4 external cash, internal transfer, Credit grant/removal, negative-balance
clear, close-time ordering, events before the first daily anchor and MT5 current-account-anchor
fallback. API tests prove that only routed raw source facts are replayed and that an unavailable
source returns a readable sanitized error. Live read-only acceptance samples are MT4 5005187 (forced
close followed by `RST` and later `TRS`), MT4 5012309 (deposit/Credit/removal/clear sequence), and
an MT5 account with Action 2 cash plus Action 3 Credit rows. DBG GB MT5 account 3066617 validates
the daily-view timeout fallback. The UI button must remain immediately
after Toxic, open/close correctly, load the selected route, page events, and visibly label missing
intraday equity rather than producing a value. Stop Out and negative-balance-clear fixtures must
produce all and only their clickable liquidation markers.

## Compatibility and deprecation

This is additive. It changes no existing finance calculation and no existing endpoint response.
Any new event classifier, reconstruction rule or compensation decision requires this document,
`BUSINESS_RULES.md`, focused fixtures and an immutable change record in the same change.
