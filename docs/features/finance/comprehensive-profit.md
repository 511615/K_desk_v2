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
last_verified_date: 2026-07-17
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

## Business rules and units

Formulas and cashflow classifications are authoritative in `BUSINESS_RULES.md`. USC money is shown
as USD after `0.01` scaling.

## Loading, empty and failure behavior

An unavailable source returns `available=false` with a reason; it must not silently return a panel
of zeros. An account with genuinely no trades may validly have zero trading values.

## Code and dependencies

Current calculations remain behind LegacyBridge pending vertical extraction.

## Tests and acceptance

RiskDash-aligned samples include 7798437 (`19618` comprehensive), 5010772 (`243.38`), 113167
(`728.38`) and Live3 241003021 (`147.52`).

## Compatibility and deprecation

Calculation changes require contract evidence, this document and `BUSINESS_RULES.md` in one change.
