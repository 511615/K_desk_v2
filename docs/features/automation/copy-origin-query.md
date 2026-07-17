---
feature_id: AUT-COPY-001
title: Copy origin query
module: automation
status: active
apis: ["GET /api/accounts/by-login/{login}/copy-origins"]
code: ["legacy/apps/problem_account_registry/app.py"]
tests: ["legacy/apps/problem_account_registry/test_app.py"]
depends_on: ["ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# Copy origin query

## Purpose and user entry

The old detail page's copy query lists detected source accounts and their matched source orders.

## UI and behavior

Each source is shown separately with matching ratio, source order samples and linked follower details.

## API contract

The endpoint accepts account source filters and returns `detected`, `origins`, `primaryOrigin` and errors.

## Data, routing and read-only constraints

Only read-only trade rows are inspected; bounded time windows and order limits prevent broad scans.

## Business rules and units

Explicit copied-order identifiers are preferred; ambiguous comments do not become confirmed sources.

## Loading, empty and failure behavior

No signal returns `detected=false`. Truncation and provider errors are exposed in the payload.

## Code and dependencies

The current service is legacy-backed and called through LegacyBridge.

## Tests and acceptance

Tests cover multiple sources, ratios, matched identifiers, bounded windows and error preservation.

## Compatibility and deprecation

Existing `/copy-origins` response keys remain compatible.
