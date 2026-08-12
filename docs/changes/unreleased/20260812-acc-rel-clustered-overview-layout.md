---
change_id: 20260812-acc-rel-clustered-overview-layout
features: ["ACC-REL-001", "ACC-REL-003"]
change_type: enhancement
status: unreleased
compatibility: compatible
---

# Group related siblings in the relationship overview

## Before and after

The one-node-per-coordinate overview made dense results visible, but all nodes in a ring were evenly
spaced. Operators could not immediately distinguish accounts sharing the same parent account and
relationship family, such as a group of same-name accounts or an IB's direct rebate recipients.

Each ring now forms a visual cluster only when nodes share both the immediate evidence owner and
relationship family. Members sit together inside a subtle arc-band, clusters have deliberate gaps,
and selecting a member highlights every member of its cluster. The larger desktop board and initial
fit show the full ring layout; resize re-fits it, while wheel zoom and pan retain their interactive
viewpoint controls.

## Impact and compatibility

This is a local Canvas presentation enhancement. It does not change account discovery, propagation
scores, graph membership, response contracts, source routing, query budgets, or database access.

## Documentation updated

Updated `ACC-REL-001` and `ACC-REL-003` with the exact sibling-cluster rule, group highlighting and
fit behavior.

## Verification

The Kuzu page contract regression asserts the relationship-group and group-band rendering functions.
Full governed verification is required before deployment.

## Deployment and rollback

Deploy by restarting only the 8777 account service. No database, CRM, MT4, MT5 Manager, Kuzu
persistent data, or 8766 service changes. Roll back to the preceding verified account-service commit.
