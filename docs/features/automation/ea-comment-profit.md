---
feature_id: AUT-EA-001
title: EA comment group profit
module: automation
status: active
apis: ["GET /api/accounts/by-login/{login}/ea-comment-profit"]
code: ["legacy/apps/problem_account_registry/ea_comment_group.py", "legacy/apps/problem_account_registry/app.py"]
tests: ["legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# EA comment group profit

## Purpose and user entry

The EA query next to copy query finds accounts using the same normalized EA comment and compares
their profit and costs.

## UI and behavior

Groups list exact EA name, accounts, profitable/losing counts, orders, lots and profit components.

## API contract

The endpoint returns `detected`, normalized comment groups, members, totals and limitations.

## Data, routing and read-only constraints

Trade comments and rows are queried read-only within the selected account source.

## Business rules and units

Generic `EA`, copy comments, signal tags and origin references are excluded. Net profit includes costs.

## Loading, empty and failure behavior

No valid EA comment returns empty groups. Query limitations are explicit.

## Code and dependencies

EA grouping is isolated in `ea_comment_group.py` and exposed through the compatibility API.

## Tests and acceptance

Tests cover exact normalization, exclusions, member totals and UI placement after copy query.

## Compatibility and deprecation

This endpoint and UI control are additive.
