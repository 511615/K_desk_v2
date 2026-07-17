---
feature_id: AUT-FOLLOWER-001
title: Follower profit by copy source
module: automation
status: active
apis: ["GET /api/accounts/by-login/{login}/copy-origins", "GET /api/accounts/by-login/{login}/copy-group-profit"]
code: ["legacy/apps/problem_account_registry/app.py", "legacy/apps/problem_account_registry/signal_copy_group.py"]
tests: ["legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["AUT-COPY-001", "FIN-REBATE-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# Follower profit by copy source

## Purpose and user entry

For each detected source, list the source owner and every follower's orders, lots, gross profit,
costs and net profit.

## UI and behavior

The old account page expands source orders and follower summaries, clearly marking the current account.

## API contract

Follower rows preserve account/platform/server, matched source IDs, order counts, volume and profit fields.

## Data, routing and read-only constraints

Queries are source-scoped and time-bounded. No trade or copy configuration is changed.

## Business rules and units

`netProfit = grossProfit + commission + swap + taxes`; display currency follows account scaling.

## Loading, empty and failure behavior

Missing follower matches produce an empty list; truncation flags disclose bounded scanning.

## Code and dependencies

Origin matching feeds the follower aggregation and signal-copy group service.

## Tests and acceptance

Tests prove per-follower totals, matched source counts, current-account marking and aggregate totals.

## Compatibility and deprecation

The detailed follower fields are additive to the established origin payload.
