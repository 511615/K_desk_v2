---
feature_id: ACC-SEARCH-001
title: Account search and source routing
module: account
status: active
apis: ["GET /api/account-lookup", "GET /api/account-lookup-finance"]
code: ["src/kdesk/api/account_app.py", "legacy/apps/problem_account_registry/app.py"]
tests: ["tests/test_api.py", "legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["FIN-COMP-001", "FIN-REBATE-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-05
---

# Account search and source routing

## Purpose and user entry

Search from the production workbench by numeric login and return every verified logical server on
which the login exists. The selected result opens `/account/{login}` with platform/server filters.

## UI and behavior

Results show platform, logical server and account metadata. Shared numeric logins remain separate
rows. Search does not silently choose a different CRM route.

## API contract

`GET /api/account-lookup?account=` returns `database` for legacy callers and `databases` for all
matches. `GET /api/account-lookup-finance` accepts account/platform/server and preserves `AC MT4`
and `DBG MT5` aliases while resolving finance from the actual result server.
Each MySQL lookup may additionally expose `routeValidation`; existing response fields are unchanged.

## Data, routing and read-only constraints

CRM account mapping is checked before trading rows. Routes follow `DATA_AND_ROUTING.md`; all
queries are read-only. Related-account discovery follows the CRM user across server codes, then
routes each related login independently instead of reusing the selected account's trading source.
If CRM mapping is temporarily absent, an indexed trade-user match may be used only under the
documented unique physical-source fallback. It is marked `unique_trade_user_fallback`; duplicate,
shared-schema, unavailable and error cases stay unavailable rather than selecting a guessed route.
DBG MT5 Live2 is independently routed by `crm_vn` server code 5 to `crm_vn_mt5_live2`; code 2
continues to use `mt5_export_new`. Detail links emitted by logical services also accept the
legacy logical names `DBG CN MT4 Live1`, `DBG CN MT4 Live2`, `DBG VN MT4 Live3` and
`AC CN MT5 Live3`, resolving them to the canonical source names without changing the returned
server identity.

## Business rules and units

Money returned by the finance summary uses the account display currency and USC conversion rules.
MT5 currency resolution uses the indexed users-group path: `Cent`/`USC` confirms USC, explicit
currency segments are retained and otherwise the configured source currency defaults to USD. The
unindexed daily view is not queried synchronously.

## Loading, empty and failure behavior

No match returns an empty `databases` list. Provider failures surface as an explicit API error and
must not be presented as a valid zero-value account. Normal synchronous lookup and finance reads
must return complete results within 10 seconds from a cold cache.

## Code and dependencies

FastAPI composes local ledger state with the governed legacy account lookup and finance services.
Lookup-finance reuses the same account/source trade-analysis cache as detail and risk panels, so a
page load does not repeat the complete historical read and metric calculation.

## Tests and acceptance

The eleven-server matrix and shared login `10002` must route correctly. Old aliases must resolve GB
accounts to GB finance sources. Account 241003021 proves Live3 search. Newly registered Live3
account 241003365 proves cent detection before the first `mt5_daily_view` row exists and cross-server
same-name routing to Live1 account 245856. DBG account 5200101 proves Live2/code 5 routing without
changing the older DBG GB MT5/code 2 route.

## Compatibility and deprecation

The existing response fields and old server aliases are stable compatibility contracts.
