---
change_id: 20260806-1015-fin-history-001-historical-funds-backtrace
features: ["FIN-HISTORY-001", "ACC-DETAIL-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# FIN-HISTORY-001 Historical funds backtrace

## Before and after

The legacy detail page had no factual full-history view for balance, Credit, internal transfers and
negative-balance clearing. It now has an additive `历史资金回溯` control immediately after Toxic,
with a route-scoped read-only timeline, balance/Credit chart and paged event evidence.

## Impact

Adds `GET /api/accounts/by-login/{login}/historical-funds`. The endpoint reads complete routed MT4
or MT5 ledger/trade facts and daily anchors only. No local or remote business data is written. The
event classifier separates external cash, internal transfers, Credit, clears, compensation and
adjustments. Equity between snapshots is intentionally unknown.

## Documentation updated

Added `FIN-HISTORY-001`; updated the legacy account-detail feature, finance business rules,
data/routing, module catalog, API catalog and test strategy.

## Verification

Focused Domain and API tests cover timestamp ordering, external versus internal cash, Credit,
negative-balance clear, first-anchor coverage and read-only source composition. Full governance and
regression checks are required before release. Manual read-only checks use MT4 5005187/5012309 and
an MT5 cash-plus-Credit sample.

## Deployment and rollback

The change is additive to the existing account service. Rollback removes the route and control; it
does not require data migration or restore because the feature owns no stored business data.
