---
change_id: 20260813-acc-rel-003-group-label
features: ["ACC-REL-003"]
change_type: modification
status: unreleased
compatibility: compatible
---

# Grouped relationship edge label

## Before and after

Grouped overview lines were visually indistinguishable from a single account edge. The line now
states that it is a representative for the relationship group and includes the member count.

## Impact

Presentation-only change in the read-only Kuzu risk canvas.

## Documentation updated

The existing ACC-REL-003 feature document remains the source of truth for the grouping behavior.

## Verification

Focused Kuzu API page test passes.

## Deployment and rollback

Restart only the account service. Roll back by restoring the prior page module.
