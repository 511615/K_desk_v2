---
feature_id: AUT-FOLLOWER-001
title: Follower profit by copy source
module: automation
status: active
apis: ["GET /api/accounts/by-login/{login}/copy-origins", "GET /api/accounts/by-login/{login}/copy-group-profit", "GET /api/accounts/by-login/{login}/copy-report.xlsx"]
code: ["legacy/apps/problem_account_registry/app.py", "legacy/apps/problem_account_registry/signal_copy_group.py", "src/kdesk/api/account_app.py", "src/kdesk/infrastructure/automation_reports.py"]
tests: ["legacy/apps/problem_account_registry/test_app.py", "tests/test_api.py", "tests/test_automation_reports.py"]
depends_on: ["AUT-COPY-001", "FIN-REBATE-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-23
---

# Follower profit by copy source

## Purpose and user entry

For each detected source, list the source owner and every follower's orders, lots, gross profit,
costs and net profit.

## UI and behavior

The old account page expands source orders and follower summaries, clearly marking the current
account. Its Excel export is source-owner-centric: a summary sheet reports each owner's total
follower P/L, and one sheet per owner begins with follower profit summaries before complete matched
order detail. Signal groups and unrelated explanation/evidence sheets are intentionally excluded.
Successful dialog results remain in page memory and reopen without a second network query until the
filters change, the account is explicitly refreshed or the page reloads.

## API contract

Follower rows preserve account/platform/server, matched source IDs, order counts, volume and profit
fields. `origins[].followerOrders` additively preserves one row per matched MT5 Position or MT4
ticket for export. The report endpoint consumes only the copy-origin read model; the Signal JSON
endpoint remains unchanged and independent.

## Data, routing and read-only constraints

MT5 follower discovery uses exact indexed opening comments in complete batches, then calculates
each matched Position before aggregating follower summaries in application code. It does not stop after 200 source orders or
20,000 candidate rows. Independent source groups run concurrently with bounded workers. No trade or
copy configuration is changed.
DBG MT5 Live2 followers use the independent `crm_vn` code 5 / `crm_vn_mt5_live2` route.

## Business rules and units

`netProfit = grossProfit + commission + fee + swap + taxes`; display currency follows account
scaling. Money remains at source precision until account aggregation, then rounds for display, so
the current-account follower total reconciles exactly with the source-attributed account total.

## Loading, empty and failure behavior

Missing follower matches produce an empty list. Provider errors remain explicit and are not cached
as successful page results.

## Code and dependencies

Origin matching feeds the follower aggregation and signal-copy group service.

## Tests and acceptance

Tests prove exact-comment SQL, more than 200 complete source orders, batched origin lookup,
per-Position detail, per-follower totals, matched source counts, current-account reconciliation,
aggregate totals and the owner summary/per-owner Excel layout. The cold 641903 copy-origin response
must be complete and below 10 seconds.

## Compatibility and deprecation

The detailed follower fields are additive to the established origin payload.
