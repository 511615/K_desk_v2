---
feature_id: ACC-DETAIL-001
title: Legacy account detail page
module: account
status: active
apis: ["GET /account/{login}", "GET /api/accounts/by-login/{login}/detail", "GET /api/accounts/by-login/{login}/risk-panels"]
code: ["src/kdesk/api/account_app.py", "legacy/apps/problem_account_registry/app.py", "frontend/src/main.ts"]
tests: ["tests/test_api.py", "legacy/apps/problem_account_registry/test_app.py", "frontend/e2e/legacy-account.spec.ts"]
depends_on: ["ACC-SEARCH-001", "FIN-COMP-001", "AUT-COPY-001", "TOX-PUSH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-07-17
---

# Legacy account detail page

## Purpose and user entry

All `/account/{login}` links render the familiar legacy account detail HTML from the new production
service. Platform/server query parameters select the account source.

## UI and behavior

The page contains ledger controls, finance and risk panels, order paging, chart generation, copy
origin, EA comment and Toxic controls. It is intentionally not replaced by the Vue AccountPage.

## API contract

The HTML URL and supporting detail/risk API response structures remain backward compatible.

## Data, routing and read-only constraints

Analytics use the selected read-only server route; local edits go only to authoritative SQLite.

## Business rules and units

Displayed finance and automation values defer to their feature documents.

## Loading, empty and failure behavior

Panels load independently where supported. A failed panel shows its own reason and must not block
the complete page or leave a false 100% progress state.

## Code and dependencies

FastAPI calls `LegacyBridge.account_page`; no other v2 module imports the copied page module.

## Tests and acceptance

Account 302360 returns HTTP 200, includes the legacy control IDs (controls may be conditionally
hidden when their feature has no data) and contains no Vue `#app` mount.

## Compatibility and deprecation

This is the required production detail UI until an explicit, documented replacement is approved.
