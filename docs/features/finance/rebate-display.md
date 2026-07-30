---
feature_id: FIN-REBATE-001
title: Rebate aggregation and display
module: finance
status: active
apis: ["GET /api/accounts/by-login/{login}/risk-panels"]
code: ["legacy/apps/problem_account_registry/app.py", "legacy/apps/problem_account_registry/signal_copy_group.py"]
tests: ["legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Rebate aggregation and display

## Purpose and user entry

Display account rebate in finance, same-name, hierarchy and automation summaries instead of a
placeholder zero.

## UI and behavior

Rebate is shown separately from trading profit and contributes to comprehensive or after-rebate
totals where the panel explicitly labels that formula.

## API contract

Existing `rebate` fields remain numeric display-currency values.

## Data, routing and read-only constraints

Read `rebate_task_detail` only from the CRM route matching the logical server. Shared trading
schemas do not justify summing unrelated CRM routes.
DBG MT5 Live2 rebates therefore use `crm_vn` code 5 only; DBG GB MT5 continues to use code 2.

## Business rules and units

Aggregate hierarchy rows before joining. CRM `rebate_task_detail.rebate_amount` is summed unchanged;
`usd_or_usc` is retained as source metadata and never scales the CRM rebate amount.

## Loading, empty and failure behavior

No rebate rows returns zero. Query failure is reported in the owning panel and is not converted to
a verified zero.

## Code and dependencies

Finance and copy-group services share the route helper and aggregation semantics.

## Tests and acceptance

Tests cover multiple hierarchy rows, logical route isolation and multi-route aggregation only when
the source explicitly configures it.

## Compatibility and deprecation

The public field remains `rebate`; source/routing changes require live read-only comparison.
