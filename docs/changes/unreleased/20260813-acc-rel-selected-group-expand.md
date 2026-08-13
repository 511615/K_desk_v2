---
change_id: 20260813-acc-rel-003-selected-group-expand
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Unify selected-account relationship aggregation

## Before and after

The overview used representative lines, but selecting an account could re-render every sibling
IB or copy edge. The selected path now uses the same relationship-group aggregation. A user can
click a coloured group band or the relation-card control to expand that one group, then click it
again to merge it.

## Impact

Canvas rendering only. The relationship evidence, score, API response and read-only data sources
are unchanged.

## Documentation updated

Updated the ACC-REL-003 current-state feature document.

## Verification

Focused Kuzu page API test passes before implementation and after implementation.

## Deployment and rollback

Restart the account service only. Rollback is the prior server-rendered page commit; no migration
or external-state rollback is required.
