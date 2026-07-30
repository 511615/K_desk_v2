---
feature_id: FIN-HIERARCHY-001
title: Hierarchy net-deposit and product analysis
module: finance
status: active
apis: ["GET /api/hierarchy-products", "GET /api/hierarchy-net-deposit"]
code: ["legacy/apps/problem_account_registry/hierarchy_net_deposit.py", "legacy/apps/problem_account_registry/app.py"]
tests: ["legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-27
---

# Hierarchy net-deposit and product analysis

## Purpose and user entry

The workbench hierarchy query resolves an IB, CRM customer or trading login, walks the complete CRM
descendant tree, and summarizes deposits, withdrawals, net deposit, closed orders, standard lots and
trading profit by user and account for a selected period and product scope.

## UI and behavior

Users can query a numeric target, an explicit account/login target or an environment-qualified CRM
user. Existing `gb:` and `cn:` selectors remain valid; `dbg-cn:` and `dbg-vn:` disambiguate DBG CRM
users. Product choices are combined from every configured, route-backed physical trading source.

## API contract

`GET /api/hierarchy-products` returns the combined product list and promotion-product group.
`GET /api/hierarchy-net-deposit` accepts `target`, `start`, `end`, optional `product` and optional
`activityRules`. Existing response fields, aggregation shape and error responses remain compatible.

## Data, routing and read-only constraints

CRM environments and allowed server codes are derived from the central source registry's
`crm_routes`, `account_route` or legacy top-level route fields. Every account is resolved by the
exact `(CRM schema, mt_server_code)` pair before its trading source is queried. DBG Vietnam code 2
continues to use `mt5_export_new`; code 5 uses only `crm_vn_mt5_live2`. Product discovery de-duplicates
shared physical schemas and scans Live2 independently. All CRM and trading reads are SELECT-only.

## Business rules and units

MT5 closed execution volume uses `/10000`; MT4 closed trade volume uses `/100`. Confirmed Cent/USC
money and trading profit use the existing `0.01` display scale. Promotion mode keeps its existing
forex/metals eligibility, standard-account-only and descendant attribution rules.

## Loading, empty and failure behavior

An unknown target or a CRM route without a configured trading source returns an explicit error.
Individual product-source failures are retained while other sources can still contribute; the API
fails only when no product source succeeds. Unsupported server codes are not guessed or silently
routed to another database.

## Code and dependencies

The governed legacy account service owns HTTP compatibility. Route extraction, subject resolution,
tree loading, physical-source de-duplication and metric aggregation live in
`hierarchy_net_deposit.py`.

## Tests and acceptance

Tests pin `crm_vn` code 5 to `crm_vn_mt5_live2`, retain code 2 on `mt5_export_new`, reject unknown
codes, cover `dbg-cn:`/`dbg-vn:` selectors, require dynamic server-code predicates in account and
tree reads, and require product discovery to query Live2 exactly once.

## Compatibility and deprecation

Existing AC selectors, API paths, query parameters, response fields, financial rules and UI layout
are unchanged. New environment selectors and Live2 rows are additive.
