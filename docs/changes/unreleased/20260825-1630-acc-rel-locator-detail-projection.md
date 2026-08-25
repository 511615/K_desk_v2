---
change_id: 20260825-1630-acc-rel-locator-detail-projection
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: ui
status: unreleased
compatibility: compatible
---

# Project the Galaxy locator from detailed-track coordinates

## Before and after

The global locator independently redistributed accounts across depth circles. Its nodes could therefore
have a different direction and relative position from the corresponding account in the detailed Galaxy.

The locator now takes the already generated detailed Galaxy `layout` coordinate for each account and
projects it at a uniform scale around the same subject. It remains an overview and keeps collapsed-track
members visible, but it does not invent a second layout.

## Impact

This is a presentation-only change for `ACC-REL-001` and `ACC-REL-003`; relationship discovery,
scores, evidence, API contracts and read-only data access are unchanged.

## Documentation updated

Updated the account relationship-network current-state document with the shared-coordinate rule.

## Verification

The Galaxy page regression requires the locator projection helper and its detailed-layout coordinate
lookup. Browser acceptance compares the same account's relative position in both canvases.

## Deployment and rollback

Promote the verified dev commit and release from clean `main`. Rollback restores the previous revision
and restarts 8777; no migration or external-state rollback is required.
