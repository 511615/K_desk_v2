---
change_id: 20260807-1015-fin-history-001-liquidation-point-markers
features: ["FIN-HISTORY-001", "ACC-DETAIL-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# FIN-HISTORY-001 liquidation point markers

## Before and after

Historical funds backtrace displayed the complete raw event timeline but did not provide a direct
way to find platform Stop Out or negative-balance-clear events. It now exposes all fact-based
liquidation points as red curve markers and a jump list. Selecting either switches to the event
page and highlights the exact source row.

## Rule and scope

The marker is created only for MT4 `REASON=5`, MT5 `Reason=6`, or an explicit negative-balance-clear
ledger row. Stop loss, ordinary realized losses, deposits and withdrawals are excluded. The endpoint
adds `summary.liquidationCount`, event-level `liquidation`, and `liquidationPoints`; existing fields
and routes remain compatible.

## Impact

The MT5 ledger read now includes its existing `Reason` column. All reads remain account-routed and
read-only. No calculation used by finance panels changes, and no local or remote data is written.

## Documentation updated

Updated FIN-HISTORY-001, ACC-DETAIL-001, BUSINESS_RULES and TEST_STRATEGY.

## Verification

Domain regression fixtures prove that MT4 and MT5 Stop Out values plus clear rows are marked, while
ordinary stop loss and losses are not. API regression, legacy-page JavaScript parse, Ruff and the
governed Fast/Full suites are required before deployment.

## Deployment and rollback

The change is additive and requires an account-service restart. Rollback removes the additional
marker fields and legacy display only; it has no data migration or persisted state.
