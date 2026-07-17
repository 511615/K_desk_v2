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
last_verified_date: 2026-07-17
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

## Data, routing and read-only constraints

CRM account mapping is checked before trading rows. Routes follow `DATA_AND_ROUTING.md`; all
queries are read-only.

## Business rules and units

Money returned by the finance summary uses the account display currency and USC conversion rules.

## Loading, empty and failure behavior

No match returns an empty `databases` list. Provider failures surface as an explicit API error and
must not be presented as a valid zero-value account.

## Code and dependencies

FastAPI composes local ledger state with the governed legacy account lookup and finance services.

## Tests and acceptance

The ten-server matrix and shared login `10002` must route correctly. Old aliases must resolve GB
accounts to GB finance sources. Account 241003021 proves Live3 search.

## Compatibility and deprecation

The existing response fields and old server aliases are stable compatibility contracts.
