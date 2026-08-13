---
change_id: 20260813-acc-rel-003-page-script-syntax
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Fix blank relationship canvas

## Before and after

An extra closing brace in the selected-group interaction wrapper caused a browser syntax error.
The page stopped at “读取中…” and never rendered the first graph snapshot. The wrapper is corrected
and the generated page script is checked with Node syntax validation.

## Impact

Read-only frontend rendering only. No relationship query, score or database behavior changes.

## Documentation updated

Updated the ACC-REL-003 current-state feature document.

## Verification

Kuzu API page tests pass and the extracted browser script passes `node --check`.

## Deployment and rollback

Restart only the 8777 account service. Rollback is the prior page-module commit; no data migration
is required.
