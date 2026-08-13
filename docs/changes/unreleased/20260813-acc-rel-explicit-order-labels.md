---
change_id: 20260813-acc-rel-explicit-order-labels
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Clarify order-related relationship labels

## Before and after

The relationship network previously displayed the generic label `同步订单`, which did not explain
whether the edge represented copy-trading evidence or Toxic timing evidence. The UI now distinguishes
matched copy-trading open/close orders, shared copy-source groups, Toxic same-direction open/close time
matches, and Toxic opposite-direction open/close time matches. The optional slow-query checkbox uses the
same explicit Toxic wording.

## Impact

This is a presentation and explanation change only. Graph expansion, scores, routing, and relationship
matching rules are unchanged. Existing stored data and API contracts remain compatible.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Focused API page test passed.
- Embedded JavaScript parser passed.
- `git diff --check` passed.

## Deployment and rollback

Deploy with the account-only production service after the standard governance and full test checks.
Rollback is the prior account-service revision if the page fails to load.
