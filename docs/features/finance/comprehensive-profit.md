---
feature_id: FIN-COMP-001
title: Comprehensive profit calculation
module: finance
status: active
apis: ["GET /api/accounts/by-login/{login}/risk-panels", "GET /api/account-lookup-finance"]
code: ["legacy/apps/problem_account_registry/app.py"]
tests: ["legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-SEARCH-001", "FIN-REBATE-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Comprehensive profit calculation

## Purpose and user entry

Show the account's current balance/equity and explain trading, cashflow, cost, holding and rebate
components in the old account detail finance panel and workbench summaries.

## UI and behavior

The panel lists balance, equity, closed gross/net P/L, fees, interest, net deposit, holding P/L,
rebate, compensation, reward, negative-balance clearing and comprehensive P/L.

## API contract

Finance fields in risk panels and lookup-finance remain stable numeric JSON fields.

## Data, routing and read-only constraints

MT4/MT5 users, accounts, trades/deals and CRM rebates are queried through the verified account route.
DBG MT5 Live2 uses `crm_vn` code 5 and `crm_vn_mt5_live2`; code 2 remains on `mt5_export_new`.
For MT4, finance uses the complete closed-order history and shares its normalized rows, costs and
metrics with account detail and risk panels during the bounded cache window.

## Business rules and units

Formulas and cashflow classifications are authoritative in `BUSINESS_RULES.md`. USC money is shown
as USD after `0.01` scaling. Currency metadata uses `mt5_users_view.Group`: `Cent` or `USC` confirms
USC, an explicit currency segment is retained and a standard group uses the source's configured USD
default. Prices, lots, identifiers, timestamps and CRM rebate amounts are not money-scaled. MT4
closed profit includes only market trades whose close time is later than their open time; current
positions are represented by current holding P/L and are not counted again as closed profit.

## Loading, empty and failure behavior

An unavailable source returns `available=false` with a reason; it must not silently return a panel
of zeros. An account with genuinely no trades may validly have zero trading values.

## Code and dependencies

Current calculations remain behind LegacyBridge pending vertical extraction.

## Tests and acceptance

RiskDash-aligned samples include 7798437 (`19618` comprehensive), 5010772 (`243.38`), 113167
(`728.38`) and Live3 241003021 (`147.52`). Live3 241003365 verifies a new USC account with no daily
row: balance/equity, trade P/L, cashflows and same-name totals use `0.01`, while rebate remains USD.
MT4 account 5013015 verifies that `1970-01-01` open-position rows do not affect closed profit.
High-volume MT4 account 8208074 verifies that finance and risk calculations include all 59,504
closed orders instead of a 50,000-row prefix and still return within the ten-second cold budget.

## Compatibility and deprecation

Calculation changes require contract evidence, this document and `BUSINESS_RULES.md` in one change.
