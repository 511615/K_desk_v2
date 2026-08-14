---
change_id: 20260814-acc-rel-007-cross-type-lanes
features: ["ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Share routing lanes across relation types

## Before and after

The first curved lane was allocated independently for each relation family. When one source had
multiple relation types with similar target angles, each type still started on lane zero and the
lines remained nearly coincident. Lane allocation now uses the source account alone, so all outgoing
relation types share one ordered fan-out.

## Impact

Read-only canvas geometry only. Relationship semantics, group anchors, API data and hit testing are
unchanged.

## Documentation updated

- `docs/features/account/score-propagated-kuzu-investigation.md`
- This change record.

## Deployment and rollback

- Deploy the account service on port 8777 only after verification.
- Roll back by reverting this implementation commit; no database migration is required.

## Verification

- Focused page contract and JavaScript syntax checks.
- Full K_desk verification before deployment.
