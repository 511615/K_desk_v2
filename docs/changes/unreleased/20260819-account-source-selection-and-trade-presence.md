---
change_id: 20260819-account-source-selection-and-trade-presence
features: ["ACC-SEARCH-001", "ACC-DETAIL-001"]
change_type: fix
status: unreleased
compatibility: compatible
---

# Preserve account trade presence and require source selection

## Before and after

Account lookup could place a CRM-confirmed zero-order route before a route with real orders, and
direct detail requests could begin analysis without a server filter. MT5 reversal/out-by deals were
also dropped when no ordinary open/close pair existed. The lookup now orders non-empty sources first,
the detail API returns an explicit source-selection payload for multiple unfiltered routes, and
reversal/out-by deals remain as zero-duration factual rows.

The Vue workbench and legacy detail-page search both show a platform/server selection dialog whenever
one Login maps to multiple sources.

## Impact

The change preserves existing API fields and selected-source URLs. It prevents cross-server data
merging and false empty-account states. All remote AC/DBG and MT4/MT5 reads remain read-only.

## Documentation updated

Updated `docs/features/account/account-search.md` and `docs/features/account/account-detail-legacy.md`.

## Verification

Focused regression tests, the legacy account/API suite, Vue component tests, and production frontend
build pass. Live checks cover accounts with orders, a CRM-confirmed zero-order account, AC Live3
cent data, DBG MT5 data, and an MT4 account.

## Deployment and rollback

Requires a controlled 8777 restart after the clean production release. Rollback is the preceding
commit and restart; no remote or trading state is modified.
