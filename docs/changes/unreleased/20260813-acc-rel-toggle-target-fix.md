---
change_id: 20260813-acc-rel-003-toggle-target-fix
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Fix relationship-group toggle target

## Before and after

The detail-panel toggle could derive its key from the selected account instead of the actual
relationship target, so an IB or copy community could remain expanded or fail to collapse. The
toggle now resolves the first matching relationship edge and uses that edge's target community key.

## Impact

Read-only canvas projection only. No scan, database, relationship score or API payload changes.

## Documentation updated

Updated the ACC-REL-003 current-state feature document.

## Verification

The focused Kuzu API page test passes.

## Deployment and rollback

Restart the 8777 account service only. Rollback is the prior page-module commit; no migration is
required.
