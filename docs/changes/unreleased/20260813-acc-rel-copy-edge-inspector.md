---
change_id: 20260813-acc-rel-copy-edge-inspector
features: ["ACC-REL-001", "ACC-REL-003", "AUT-COPY-001"]
change_type: feature
status: unreleased
compatibility: compatible
---

# Add copy-edge evidence inspector

## Before and after

Copy-order edges explained their matching rule but did not expose the matched orders. Clicking a
visible copy-order edge now opens an on-demand modal with a pair-specific matched-order tab and a
master-centred all-followers tab.

## Impact

The modal reuses the existing read-only Copy-origin endpoint and the current page filters. It is
loaded only after a user clicks a copy edge, so graph expansion requests stay bounded and unchanged.
No relationship scoring, graph expansion, database or MT state changes.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Focused Kuzu page API contract test verifies the modal, lazy loader and both tab labels.
- Full verification is required before deployment.

## Deployment and rollback

Deploy through the account-only production service after full verification. Roll back to the prior
account-service revision if the modal or graph page fails to load.
