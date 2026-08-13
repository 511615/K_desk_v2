---
change_id: 20260813-acc-rel-order-label-source-fix
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: bugfix
status: unreleased
compatibility: compatible
---

# Make order relationship labels source-of-truth

## Before and after

The newly explicit order labels were applied through duplicated late JavaScript wrappers while the
initial source mapping still retained `同步订单`. A duplicated definition could prevent the page script
from loading, and the legacy term remained in the HTML. The initial mapping, detail explanation,
Toxic control and loading state now contain the explicit terms directly; late wrappers were removed.

## Impact

This fixes presentation and page-load reliability only. Copy matching, Toxic matching, graph expansion,
scores, endpoint contracts and read-only data access are unchanged.

## Documentation updated

- `docs/features/account/relationship-network.md`
- `docs/features/account/score-propagated-kuzu-investigation.md`

## Verification

- Focused Kuzu page contract test proves no ambiguous order label or duplicate wrapper remains.
- Full verification is required before deployment.

## Deployment and rollback

Deploy through the account-only production service after full verification. Roll back to the prior
account-service revision if the graph page fails to load.
