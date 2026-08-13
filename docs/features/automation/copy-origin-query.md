---
feature_id: AUT-COPY-001
title: Copy origin query
module: automation
status: active
apis: ["GET /api/accounts/by-login/{login}/copy-origins", "GET /api/accounts/by-login/{login}/copy-report.xlsx"]
code: ["legacy/apps/problem_account_registry/app.py", "src/kdesk/api/account_app.py", "src/kdesk/infrastructure/automation_reports.py"]
tests: ["legacy/apps/problem_account_registry/test_app.py", "tests/test_api.py", "tests/test_automation_reports.py"]
depends_on: ["ACC-SEARCH-001"]
last_verified_version: 2.1.0
last_verified_date: 2026-08-05
---

# Copy origin query

## Purpose and user entry

The old detail page's copy query lists detected source accounts and their matched source orders.

## UI and behavior

Each source is shown separately with matching ratio, source order samples and linked follower details.
The relationship-network copy-edge inspector may also consume this same payload on demand. It keeps
the clicked follower/master pair in its first tab and the identified master with all discovered
followers in its second tab; it does not create a second matching implementation or preload the
complete order detail into the relationship graph.
The dialog provides optional opening-time start/end controls shared by CPT and Signal results.
Blank dates retain complete-history behavior; an end earlier than the start is rejected before any
request. The selected range is included in the page-local cache key; explicit account refresh or
page reload clears it.
The query dialog provides one-click Excel export organized by source owner. The workbook contains
only one owner summary sheet and one sheet per owner. Each owner sheet starts with follower profit
totals and account summaries, then lists the complete matched follower orders. It does not add a
queried-account sheet, Signal sheet, source-evidence sheet or definition sheet. Account and order
identifiers remain text and positive/negative profit is visually distinguished.

## API contract

The JSON endpoints accept account source filters plus optional `start` and `end` opening-time
filters and return `detected`, `origins`, `primaryOrigin` and errors. Each origin additively exposes
`followerOrders` for report detail. The `.xlsx` endpoint accepts exactly the same filters and
downloads a no-store owner-centric workbook; existing JSON fields are unchanged.

## Data, routing and read-only constraints

Only read-only trade rows are inspected. Source identifiers are resolved in complete indexed
batches; the former first-1,000 identifier cutoff is not applied.
The configured source set includes DBG MT5 Live2 through `crm_vn` code 5 and never substitutes the
older code 2 `mt5_export_new` route.

## Business rules and units

For MT5 reconstructed trades, the opening deal comment is authoritative. A combined display comment
such as `CPT-SS#open / CPT-SS#close` contributes only the opening source Position ID; the closing
deal ID must not create a second source or unresolved group.

## Loading, empty and failure behavior

No source signal returns `detected=false`. Provider errors are exposed in the JSON payload; report
generation fails rather than silently exporting incomplete owner pages. A valid empty query exports
an explicit empty owner-summary sheet.

## Code and dependencies

The current service is legacy-backed and called through LegacyBridge.

## Tests and acceptance

Tests cover multiple sources, more than 1,000 identifiers, opening/closing comment separation,
complete assignment, ratios, matched identifiers, error preservation, page-local caching, download
headers, owner-oriented workbook sheets, typed account/profit cells, detailed order rows and
empty-result exports. Time-range tests prove opening-time filtering and range forwarding to CPT
followers and Signal statistics. AC GB MT5 account
641903 must resolve all 895 copied positions to 640598 (625) and 632824 (270), with zero unresolved.

## Compatibility and deprecation

Existing `/copy-origins` response keys remain compatible.
