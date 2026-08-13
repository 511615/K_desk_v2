---
change_id: 20260813-acc-rel-003-selected-community-toggle
features: ["ACC-REL-003"]
change_type: modification
status: unreleased
compatibility: compatible
---

# Selected relationship community aggregation

## Before and after

Selecting an account could re-expand every IB or copy member edge even though the overview used a
representative line. Selected branches now use the same one-line-per-parent/type community policy.
The selected relation control offers “展开当前关系群组” and “合并当前关系群组”; toggling it only
changes the canvas projection and does not rerun the database scan.

## Impact

This is a read-only canvas projection change. It reduces selected-view edge count and makes the
relationship community boundary explicit while preserving all nodes and detail evidence.

## Documentation updated

Updated `docs/features/account/score-propagated-kuzu-investigation.md`.

## Verification

Focused Kuzu API page test passes; full governance verification is required before release.

## Deployment and rollback

Restart only the 8777 account service. Rollback is a page-module restore with no data migration.
